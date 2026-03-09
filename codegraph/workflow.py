"""codegraph.workflow — Workflow builder (execution graph).

Covers tasks F-001, F-009 through F-035:
  F-001  Static call graph builder
  F-009  Coverage.py integration for runtime tracing
  F-010  Trace data parser
  F-011  Test-execution edge builder
  F-012  Dynamic edge builder
  F-013  Edge merging from multiple sources
  F-014  Workflow graph writer
  F-015  Module-level workflow compression
  F-016  Class-level workflow compression
  F-017  Import edge builder
  F-018  Workflow build orchestrator
  F-019  Workflow loading
  F-020  Workflow validation
  F-021  Orphan node detection
  F-022  Workflow edge counting
  F-023  Workflow incremental update
  F-024  Self-call detection
  F-025  Coverage.py pytest plugin hook (see pytest_plugin.py)
  F-026  Trace fallback on failure
  F-027  Architecture test trace mode
  F-028  Edge source tracking metadata
  F-029  Workflow graph statistics summary
  F-030  Workflow diff for delta verification
  F-031  Import dependency tracker
  F-032  Workflow build performance optimization
  F-033  Conditional edge detection
  F-034  Workflow level validation
  F-035  Workflow metadata header
"""

from __future__ import annotations

import ast
import csv
import io
import json
import subprocess
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from codegraph.config import CodegraphConfig, load_config
from codegraph.constants import (
    CODEGRAPH_DIR,
    GRAPHS_DIR,
    LAYER_PROJECT,
    LAYER_TEST,
    TEST_ARCHI_DIR,
    WORKFLOW_DIR,
    WORKFLOW_FILE,
)
from codegraph.logging_config import get_logger
from codegraph.models.graph0 import Graph0, Graph0Node
from codegraph.models.workflow import (
    Workflow,
    WorkflowEdge,
    WorkflowLevel,
    deduplicate_edges,
)
from codegraph.storage import atomic_write, ensure_codegraph_dir, resolve_path
from codegraph.utils.formatting import iso_now

logger = get_logger("workflow")


# ═══════════════════════════════════════════════════════════════════════
# Helper dataclasses
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class ValidationIssue:
    """A single workflow validation issue (F-020)."""

    severity: str  # "error" or "warning"
    message: str


@dataclass
class WorkflowDiffEntry:
    """A single difference between two workflows (F-030)."""

    kind: str  # "added", "removed", "changed"
    source: str
    target: str
    old_edge_type: str = ""
    new_edge_type: str = ""
    old_confidence: str = ""
    new_confidence: str = ""


@dataclass
class WorkflowDiff:
    """Differences between two workflow graphs (F-030)."""

    added: List[WorkflowDiffEntry] = field(default_factory=list)
    removed: List[WorkflowDiffEntry] = field(default_factory=list)
    changed: List[WorkflowDiffEntry] = field(default_factory=list)

    def format(self) -> str:
        lines: List[str] = []
        if self.added:
            lines.append(f"Added edges: {len(self.added)}")
            for e in self.added[:20]:
                lines.append(f"  + {e.source} → {e.target} ({e.new_edge_type}/{e.new_confidence})")
        if self.removed:
            lines.append(f"Removed edges: {len(self.removed)}")
            for e in self.removed[:20]:
                lines.append(f"  - {e.source} → {e.target} ({e.old_edge_type}/{e.old_confidence})")
        if self.changed:
            lines.append(f"Changed edges: {len(self.changed)}")
            for e in self.changed[:20]:
                lines.append(
                    f"  ~ {e.source} → {e.target}: "
                    f"{e.old_edge_type}/{e.old_confidence} → {e.new_edge_type}/{e.new_confidence}"
                )
        if not lines:
            lines.append("No differences.")
        return "\n".join(lines)


@dataclass
class EdgeStats:
    """Workflow edge statistics (F-022)."""

    total: int = 0
    by_type: Dict[str, int] = field(default_factory=dict)
    by_confidence: Dict[str, int] = field(default_factory=dict)
    dynamic_count: int = 0
    self_referencing: int = 0

    def format(self) -> str:
        lines = [f"Total edges: {self.total}"]
        if self.by_type:
            lines.append("  By type: " + ", ".join(f"{k}={v}" for k, v in sorted(self.by_type.items())))
        if self.by_confidence:
            lines.append("  By confidence: " + ", ".join(f"{k}={v}" for k, v in sorted(self.by_confidence.items())))
        if self.dynamic_count:
            lines.append(f"  Dynamic (unresolved): {self.dynamic_count}")
        if self.self_referencing:
            lines.append(f"  Self-referencing: {self.self_referencing}")
        return "\n".join(lines)


@dataclass
class ImportEdge:
    """Module-level import dependency (F-031)."""

    source_module: str
    target_module: str
    names: List[str] = field(default_factory=list)


@dataclass
class ImportGraph:
    """All module-level import dependencies (F-031)."""

    edges: List[ImportEdge] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "edges": [
                {
                    "source": e.source_module,
                    "target": e.target_module,
                    "names": e.names,
                }
                for e in self.edges
            ],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ImportGraph":
        edges = [
            ImportEdge(
                source_module=e["source"],
                target_module=e["target"],
                names=e.get("names", []),
            )
            for e in data.get("edges", [])
        ]
        return cls(edges=edges)


# ═══════════════════════════════════════════════════════════════════════
# F-001 — Static call graph builder
# ═══════════════════════════════════════════════════════════════════════


def build_static_edges(
    graph0: Graph0,
    call_sites: Dict[str, List[Any]],
    imports: Dict[str, List[Any]],
    *,
    detect_conditional: bool = False,
) -> Tuple[List[WorkflowEdge], List[Any]]:
    """Build static edges from call sites and resolved targets (F-001, F-024, F-033).

    Returns (static_edges, unresolved_dynamic_calls).
    """
    from codegraph.extractor import resolve_call_target

    all_node_ids: Set[str] = {n.id for n in graph0.nodes}
    edges: List[WorkflowEdge] = []
    unresolved: List[Any] = []

    for source_id, calls in call_sites.items():
        if source_id not in all_node_ids:
            continue
        file_imports = imports.get(source_id.split("::", 1)[0], [])

        # Derive file path and class for resolution
        parts = source_id.split("::")
        current_file = parts[0] if parts else ""
        current_class = parts[1] if len(parts) >= 3 else None

        for call in calls:
            if call.is_dynamic:
                unresolved.append(call)
                continue

            target = resolve_call_target(
                call,
                file_imports,
                current_file,
                all_node_ids,
                current_class=current_class,
            )

            if target is not None and target in all_node_ids:
                edge = WorkflowEdge(
                    source=source_id,
                    target=target,
                    edge_type="call",
                    confidence="static",
                )
                edges.append(edge)
            else:
                unresolved.append(call)

    return edges, unresolved


# ═══════════════════════════════════════════════════════════════════════
# F-012 — Dynamic edge builder
# ═══════════════════════════════════════════════════════════════════════


def build_dynamic_edges(
    dynamic_calls: List[Any],
    default_scope: str = "",
) -> List[WorkflowEdge]:
    """Build dynamic edges with wildcard targets (F-012)."""
    seen: Set[Tuple[str, str]] = set()
    edges: List[WorkflowEdge] = []

    for dc in dynamic_calls:
        scope = getattr(dc, "scope", "") or default_scope or "unknown"
        source = scope
        target = f"{scope}::*"
        key = (source, target)
        if key in seen:
            continue
        seen.add(key)
        edges.append(WorkflowEdge(
            source=source,
            target=target,
            edge_type="dynamic",
            confidence="static",
        ))

    return edges


# ═══════════════════════════════════════════════════════════════════════
# F-009 / F-025 / F-026 / F-027 — Runtime tracing via coverage.py
# ═══════════════════════════════════════════════════════════════════════


def run_trace(
    project_root: Path,
    test_dir: str = "tests",
    *,
    archi: bool = False,
    timeout: int = 300,
) -> List[Dict[str, Any]]:
    """Run pytest with coverage.py to capture function-level traces (F-009, F-025, F-027).

    Returns raw coverage data as a list of dicts with 'file' and 'executed_lines'.
    Falls back to empty list on failure (F-026).
    """
    if archi:
        test_path = project_root / CODEGRAPH_DIR / TEST_ARCHI_DIR
    else:
        test_path = project_root / test_dir

    if not test_path.exists():
        logger.warning("Test directory not found: %s — skipping trace", test_path)
        return []

    cov_data_file = project_root / CODEGRAPH_DIR / ".coverage_cg"
    cov_json_file = project_root / CODEGRAPH_DIR / "coverage_cg.json"

    try:
        # Run pytest with coverage
        cmd = [
            sys.executable, "-m", "pytest",
            str(test_path),
            f"--cov={project_root}",
            "--cov-branch",
            f"--cov-config={_coverage_config(project_root)}",
            "--no-header", "-q",
        ]
        logger.info("Running trace: %s", " ".join(cmd))
        proc = subprocess.run(
            cmd,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_trace_env(project_root, cov_data_file),
        )
        if proc.returncode != 0:
            logger.warning("Test run exited with code %d:\n%s", proc.returncode, proc.stderr[:500])
            # Still try to parse coverage data

        # Export coverage to JSON
        export_cmd = [
            sys.executable, "-m", "coverage", "json",
            f"--data-file={cov_data_file}",
            f"-o", str(cov_json_file),
        ]
        subprocess.run(
            export_cmd,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=60,
        )

        if cov_json_file.exists():
            data = json.loads(cov_json_file.read_text(encoding="utf-8"))
            files_data = data.get("files", {})
            result = []
            for fpath, finfo in files_data.items():
                result.append({
                    "file": fpath,
                    "executed_lines": finfo.get("executed_lines", []),
                })
            return result

        logger.warning("No coverage JSON produced — trace data unavailable")
        return []

    except FileNotFoundError:
        logger.warning("pytest or coverage not installed — skipping trace")
        return []
    except subprocess.TimeoutExpired:
        logger.warning("Trace timed out after %ds — skipping", timeout)
        return []
    except Exception as exc:
        logger.warning("Trace failed: %s — falling back to static only", exc)
        return []
    finally:
        # Cleanup temp files
        for p in (cov_data_file, cov_json_file):
            try:
                if p.exists():
                    p.unlink()
            except OSError:
                pass


def _coverage_config(project_root: Path) -> Path:
    """Return path to a temporary coveragerc for tracing."""
    cfg_path = project_root / CODEGRAPH_DIR / ".coveragerc_cg"
    if not cfg_path.exists():
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(
            "[run]\nbranch = True\nsource = .\n"
            "[report]\nshow_missing = False\n",
            encoding="utf-8",
        )
    return cfg_path


def _trace_env(project_root: Path, data_file: Path) -> Dict[str, str]:
    """Build environment for coverage run."""
    import os
    env = os.environ.copy()
    env["COVERAGE_FILE"] = str(data_file)
    return env


# ═══════════════════════════════════════════════════════════════════════
# F-010 — Trace data parser
# ═══════════════════════════════════════════════════════════════════════


def parse_trace_data(
    coverage_data: List[Dict[str, Any]],
    graph0: Graph0,
) -> List[WorkflowEdge]:
    """Parse coverage.py output to function-level call edges (F-010).

    Maps covered lines to Graph_0 nodes, then infers call relationships.
    """
    if not coverage_data:
        return []

    # Build a line→node lookup: file → sorted list of (start_line, node_id)
    file_nodes: Dict[str, List[Tuple[int, str]]] = defaultdict(list)
    for node in graph0.nodes:
        if node.type in ("function", "method"):
            file_nodes[node.file].append((node.line, node.id))

    for fpath in file_nodes:
        file_nodes[fpath].sort()

    edges: List[WorkflowEdge] = []
    seen: Set[Tuple[str, str]] = set()

    for entry in coverage_data:
        raw_file = entry.get("file", "")
        executed = set(entry.get("executed_lines", []))
        if not executed:
            continue

        # Normalize file path
        file_key = raw_file.replace("\\", "/")
        # Try to match against graph0 file paths
        matched_key = None
        for fk in file_nodes:
            if file_key.endswith(fk) or fk.endswith(file_key):
                matched_key = fk
                break
        if matched_key is None:
            continue

        nodes_in_file = file_nodes[matched_key]
        # Find which functions were executed
        executed_funcs: List[str] = []
        for start_line, node_id in nodes_in_file:
            if start_line in executed:
                executed_funcs.append(node_id)

        # Infer edges: consecutive executed functions in the same file
        for i in range(len(executed_funcs) - 1):
            src, tgt = executed_funcs[i], executed_funcs[i + 1]
            if src != tgt:
                key = (src, tgt)
                if key not in seen:
                    seen.add(key)
                    edges.append(WorkflowEdge(
                        source=src,
                        target=tgt,
                        edge_type="trace",
                        confidence="runtime",
                    ))

    return edges


# ═══════════════════════════════════════════════════════════════════════
# F-011 — Test-execution edge builder
# ═══════════════════════════════════════════════════════════════════════


def build_test_edges(
    coverage_data: List[Dict[str, Any]],
    graph0: Graph0,
) -> List[WorkflowEdge]:
    """Build test→production edges from coverage data (F-011).

    For each test function that was executed, create edges to production
    functions whose lines were also covered.
    """
    if not coverage_data:
        return []

    # Identify test nodes and production nodes
    test_nodes: Set[str] = set()
    prod_nodes: Set[str] = set()
    node_lines: Dict[str, Tuple[str, int]] = {}  # node_id → (file, line)
    for node in graph0.nodes:
        if node.type in ("function", "method"):
            node_lines[node.id] = (node.file, node.line)
            if node.file.startswith("test") or "/test" in node.file or "\\test" in node.file:
                test_nodes.add(node.id)
            else:
                prod_nodes.add(node.id)

    # Build file→covered lines mapping
    file_covered: Dict[str, Set[int]] = {}
    for entry in coverage_data:
        raw_file = entry.get("file", "").replace("\\", "/")
        file_covered[raw_file] = set(entry.get("executed_lines", []))

    edges: List[WorkflowEdge] = []
    seen: Set[Tuple[str, str]] = set()

    for test_id in test_nodes:
        test_file, test_line = node_lines[test_id]
        # Check which production files were covered during test
        for prod_id in prod_nodes:
            prod_file, prod_line = node_lines[prod_id]
            for raw_path, covered in file_covered.items():
                if raw_path.endswith(prod_file) and prod_line in covered:
                    key = (test_id, prod_id)
                    if key not in seen:
                        seen.add(key)
                        edges.append(WorkflowEdge(
                            source=test_id,
                            target=prod_id,
                            edge_type="test",
                            confidence="test",
                        ))
                    break

    return edges


# ═══════════════════════════════════════════════════════════════════════
# F-013 — Edge merging from multiple sources
# ═══════════════════════════════════════════════════════════════════════


def merge_edges(
    static: List[WorkflowEdge],
    trace: Optional[List[WorkflowEdge]] = None,
    test: Optional[List[WorkflowEdge]] = None,
    dynamic: Optional[List[WorkflowEdge]] = None,
) -> List[WorkflowEdge]:
    """Merge edges from all sources, deduplicating exact matches (F-013)."""
    all_edges: List[WorkflowEdge] = list(static)
    if trace:
        all_edges.extend(trace)
    if test:
        all_edges.extend(test)
    if dynamic:
        all_edges.extend(dynamic)

    # Deduplicate exact matches only
    deduped = deduplicate_edges(all_edges)

    # Sort by source node ID for deterministic output
    deduped.sort(key=lambda e: (e.source, e.target, e.edge_type))
    return deduped


# ═══════════════════════════════════════════════════════════════════════
# F-015 — Module-level compression
# ═══════════════════════════════════════════════════════════════════════


def _extract_module(node_id: str) -> str:
    """Extract module path from a node ID like 'path/file.py::Class::method'."""
    return node_id.split("::")[0] if "::" in node_id else node_id


def compress_to_module(edges: List[WorkflowEdge]) -> List[WorkflowEdge]:
    """Compress function-level edges to module-level (F-015)."""
    seen: Set[Tuple[str, str]] = set()
    result: List[WorkflowEdge] = []

    for e in edges:
        src_mod = _extract_module(e.source)
        tgt_mod = _extract_module(e.target)
        key = (src_mod, tgt_mod)
        if key not in seen:
            seen.add(key)
            result.append(WorkflowEdge(
                source=src_mod,
                target=tgt_mod,
                edge_type=e.edge_type,
                confidence=e.confidence,
            ))

    result.sort(key=lambda e: (e.source, e.target))
    return result


# ═══════════════════════════════════════════════════════════════════════
# F-016 — Class-level compression
# ═══════════════════════════════════════════════════════════════════════


def _extract_class(node_id: str) -> str:
    """Extract class-level ID from a node ID.

    'path/file.py::Class::method' → 'path/file.py::Class'
    'path/file.py::function' → 'path/file.py'  (module as class)
    """
    parts = node_id.split("::")
    if len(parts) >= 3:
        return f"{parts[0]}::{parts[1]}"
    elif len(parts) == 2:
        return parts[0]  # standalone function → module level
    return node_id


def compress_to_class(edges: List[WorkflowEdge]) -> List[WorkflowEdge]:
    """Compress method-level edges to class-level (F-016)."""
    seen: Set[Tuple[str, str]] = set()
    result: List[WorkflowEdge] = []

    for e in edges:
        src_cls = _extract_class(e.source)
        tgt_cls = _extract_class(e.target)
        key = (src_cls, tgt_cls)
        if key not in seen:
            seen.add(key)
            result.append(WorkflowEdge(
                source=src_cls,
                target=tgt_cls,
                edge_type=e.edge_type,
                confidence=e.confidence,
            ))

    result.sort(key=lambda e: (e.source, e.target))
    return result


# ═══════════════════════════════════════════════════════════════════════
# F-017 — Import edge builder
# ═══════════════════════════════════════════════════════════════════════


def build_import_edges(
    imports: Dict[str, List[Any]],
    graph0: Graph0,
) -> List[WorkflowEdge]:
    """Build import-level edges (F-017). NOT included by default."""
    all_files: Set[str] = {n.file for n in graph0.nodes}
    edges: List[WorkflowEdge] = []
    seen: Set[Tuple[str, str]] = set()

    for source_file, imp_list in imports.items():
        for imp in imp_list:
            module = getattr(imp, "module", str(imp)) if not isinstance(imp, str) else imp
            target_file = module.replace(".", "/") + ".py"
            # Also try without .py for package init
            candidates = [target_file, module.replace(".", "/") + "/__init__.py"]
            for candidate in candidates:
                if candidate in all_files:
                    key = (source_file, candidate)
                    if key not in seen:
                        seen.add(key)
                        edges.append(WorkflowEdge(
                            source=source_file,
                            target=candidate,
                            edge_type="call",
                            confidence="static",
                        ))
                    break

    return edges


# ═══════════════════════════════════════════════════════════════════════
# F-033 — Conditional edge detection
# ═══════════════════════════════════════════════════════════════════════


def detect_conditional_calls(
    func_node: ast.AST,
) -> Set[int]:
    """Return set of line numbers that are inside conditional blocks (F-033).

    A call is 'conditional' if it sits inside an if/elif/else, try/except,
    for/while loop body, or with statement.
    """
    conditional_lines: Set[int] = set()

    for node in ast.walk(func_node):
        bodies: List[list] = []
        if isinstance(node, (ast.If, ast.IfExp)):
            if hasattr(node, "body"):
                bodies.append(node.body)
            if hasattr(node, "orelse") and node.orelse:
                bodies.append(node.orelse)
        elif isinstance(node, ast.Try):
            bodies.append(node.handlers)
            if node.orelse:
                bodies.append(node.orelse)
            if node.finalbody:
                bodies.append(node.finalbody)
        elif isinstance(node, (ast.For, ast.While, ast.AsyncFor)):
            bodies.append(node.body)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            bodies.append(node.body)

        for body in bodies:
            if isinstance(body, list):
                for child in body:
                    for sub in ast.walk(child):
                        if hasattr(sub, "lineno"):
                            conditional_lines.add(sub.lineno)

    return conditional_lines


# ═══════════════════════════════════════════════════════════════════════
# F-014 — Workflow graph writer
# ═══════════════════════════════════════════════════════════════════════


def write_workflow(
    workflow: Workflow,
    project_root: Path,
    *,
    metadata: Optional[Dict[str, Any]] = None,
) -> Path:
    """Write workflow.json atomically (F-014, F-035)."""
    ensure_codegraph_dir(project_root)
    dest = resolve_path(project_root, WORKFLOW_DIR, WORKFLOW_FILE)

    data: Dict[str, Any] = {}

    # F-035 — metadata header
    if metadata:
        data["metadata"] = metadata
    else:
        data["metadata"] = {
            "built_at": workflow.built_at,
            "level": workflow.level,
            "edge_count": len(workflow.edges),
        }

    data["format_version"] = workflow.format_version
    data["built_at"] = workflow.built_at
    data["level"] = workflow.level
    data["edges"] = [e.to_dict() for e in workflow.edges]

    atomic_write(dest, data)
    logger.info("Saved workflow (%d edges) → %s", len(workflow.edges), dest)
    return dest


# ═══════════════════════════════════════════════════════════════════════
# F-019 — Workflow loading
# ═══════════════════════════════════════════════════════════════════════


def load_workflow(project_root: Path) -> Workflow:
    """Load workflow.json, returning empty Workflow if missing (F-019)."""
    path = resolve_path(project_root, WORKFLOW_DIR, WORKFLOW_FILE)
    if not path.exists():
        logger.debug("No workflow.json found — returning empty Workflow")
        return Workflow()

    try:
        text = path.read_text(encoding="utf-8")
        return Workflow.from_json(text)
    except (json.JSONDecodeError, KeyError) as exc:
        logger.error("Corrupted workflow.json: %s", exc)
        return Workflow()


# ═══════════════════════════════════════════════════════════════════════
# F-020 — Workflow validation
# ═══════════════════════════════════════════════════════════════════════

_VALID_EDGE_TYPES = {"call", "test", "trace", "dynamic"}
_VALID_CONFIDENCES = {"runtime", "test", "static", "ai_inferred"}


def validate_workflow(
    workflow: Workflow,
    graph0: Graph0,
) -> List[ValidationIssue]:
    """Check workflow graph integrity (F-020)."""
    issues: List[ValidationIssue] = []
    all_ids = {n.id for n in graph0.nodes}

    seen_keys: Set[Tuple[str, str, str, str]] = set()

    for edge in workflow.edges:
        # Source exists in Graph_0
        if edge.source not in all_ids:
            issues.append(ValidationIssue(
                severity="warning",
                message=f"Edge source not in Graph_0: {edge.source}",
            ))

        # Target exists or is dynamic wildcard
        if not edge.is_dynamic() and edge.target not in all_ids:
            issues.append(ValidationIssue(
                severity="warning",
                message=f"Edge target not in Graph_0: {edge.target}",
            ))

        # Valid edge type
        if edge.edge_type not in _VALID_EDGE_TYPES:
            issues.append(ValidationIssue(
                severity="error",
                message=f"Invalid edge_type: {edge.edge_type}",
            ))

        # Valid confidence
        if edge.confidence not in _VALID_CONFIDENCES:
            issues.append(ValidationIssue(
                severity="error",
                message=f"Invalid confidence: {edge.confidence}",
            ))

        # Duplicate check
        key = edge._key()
        if key in seen_keys:
            issues.append(ValidationIssue(
                severity="warning",
                message=f"Duplicate edge: {edge.source} → {edge.target} ({edge.edge_type})",
            ))
        seen_keys.add(key)

    return issues


# ═══════════════════════════════════════════════════════════════════════
# F-021 — Orphan node detection
# ═══════════════════════════════════════════════════════════════════════


def find_orphans(
    workflow: Workflow,
    graph0: Graph0,
    layer_map: Optional[Dict[str, int]] = None,
) -> List[str]:
    """Find nodes with no incoming or outgoing edges (F-021)."""
    connected: Set[str] = set()
    for edge in workflow.edges:
        connected.add(edge.source)
        connected.add(edge.target)

    orphans: List[str] = []
    for node in graph0.nodes:
        # Skip module-level nodes
        if node.type == "module":
            continue
        if node.id not in connected:
            # Only report layer 3/4 orphans
            if layer_map is not None:
                layer = layer_map.get(node.id, LAYER_PROJECT)
                if layer < LAYER_PROJECT:
                    continue
            orphans.append(node.id)

    return sorted(orphans)


# ═══════════════════════════════════════════════════════════════════════
# F-022 — Workflow edge counting
# ═══════════════════════════════════════════════════════════════════════


def edge_statistics(workflow: Workflow) -> EdgeStats:
    """Count edges by type and confidence (F-022)."""
    stats = EdgeStats(total=len(workflow.edges))

    for e in workflow.edges:
        stats.by_type[e.edge_type] = stats.by_type.get(e.edge_type, 0) + 1
        stats.by_confidence[e.confidence] = stats.by_confidence.get(e.confidence, 0) + 1
        if e.is_dynamic():
            stats.dynamic_count += 1
        if e.source == e.target:
            stats.self_referencing += 1

    return stats


# ═══════════════════════════════════════════════════════════════════════
# F-023 — Workflow incremental update
# ═══════════════════════════════════════════════════════════════════════


def update_workflow_incremental(
    workflow: Workflow,
    changed_files: List[str],
    graph0: Graph0,
    call_sites: Dict[str, List[Any]],
    imports: Dict[str, List[Any]],
) -> Workflow:
    """Update workflow edges incrementally for changed files (F-023)."""
    changed_set = set(changed_files)

    def _in_changed(node_id: str) -> bool:
        file_part = node_id.split("::")[0] if "::" in node_id else node_id
        return file_part in changed_set

    # Remove edges where source or target is in changed files
    kept = [e for e in workflow.edges if not (_in_changed(e.source) or _in_changed(e.target))]

    # Re-build edges for changed files only
    changed_call_sites = {k: v for k, v in call_sites.items() if _in_changed(k)}
    changed_imports = {k: v for k, v in imports.items() if _in_changed(k)}
    new_edges, _ = build_static_edges(graph0, changed_call_sites, changed_imports)

    kept.extend(new_edges)
    new_wf = Workflow(
        level=workflow.level,
        edges=deduplicate_edges(kept),
    )
    return new_wf


# ═══════════════════════════════════════════════════════════════════════
# F-029 — Workflow graph statistics summary
# ═══════════════════════════════════════════════════════════════════════


def workflow_summary(
    workflow: Workflow,
    graph0: Graph0,
    layer_map: Optional[Dict[str, int]] = None,
) -> str:
    """Generate a comprehensive text summary of the workflow (F-029)."""
    stats = edge_statistics(workflow)
    orphans = find_orphans(workflow, graph0, layer_map)
    node_count = len({e.source for e in workflow.edges} | {e.target for e in workflow.edges})

    lines = [
        f"Workflow Summary (level={workflow.level})",
        f"  Nodes in edges: {node_count}",
        f"  {stats.format()}",
        f"  Orphan nodes: {len(orphans)}",
    ]
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# F-030 — Workflow diff
# ═══════════════════════════════════════════════════════════════════════


def diff_workflows(old: Workflow, new: Workflow) -> WorkflowDiff:
    """Compare two workflow graphs (F-030)."""
    old_keys: Dict[Tuple[str, str], WorkflowEdge] = {}
    for e in old.edges:
        old_keys[(e.source, e.target)] = e

    new_keys: Dict[Tuple[str, str], WorkflowEdge] = {}
    for e in new.edges:
        new_keys[(e.source, e.target)] = e

    diff = WorkflowDiff()

    for key, edge in new_keys.items():
        if key not in old_keys:
            diff.added.append(WorkflowDiffEntry(
                kind="added",
                source=edge.source,
                target=edge.target,
                new_edge_type=edge.edge_type,
                new_confidence=edge.confidence,
            ))
        else:
            old_edge = old_keys[key]
            if old_edge.edge_type != edge.edge_type or old_edge.confidence != edge.confidence:
                diff.changed.append(WorkflowDiffEntry(
                    kind="changed",
                    source=edge.source,
                    target=edge.target,
                    old_edge_type=old_edge.edge_type,
                    new_edge_type=edge.edge_type,
                    old_confidence=old_edge.confidence,
                    new_confidence=edge.confidence,
                ))

    for key, edge in old_keys.items():
        if key not in new_keys:
            diff.removed.append(WorkflowDiffEntry(
                kind="removed",
                source=edge.source,
                target=edge.target,
                old_edge_type=edge.edge_type,
                old_confidence=edge.confidence,
            ))

    return diff


# ═══════════════════════════════════════════════════════════════════════
# F-031 — Import dependency tracker
# ═══════════════════════════════════════════════════════════════════════


def build_import_dependencies(
    graph0: Graph0,
    imports: Dict[str, List[Any]],
) -> ImportGraph:
    """Build module-to-module import relationships (F-031)."""
    edges: List[ImportEdge] = []
    seen: Set[Tuple[str, str]] = set()

    for source_file, imp_list in imports.items():
        for imp in imp_list:
            module = getattr(imp, "module", str(imp)) if not isinstance(imp, str) else imp
            if not module:
                continue
            target_module = module.replace(".", "/")
            key = (source_file, target_module)
            if key not in seen:
                seen.add(key)
                names = getattr(imp, "names", []) if not isinstance(imp, str) else []
                edges.append(ImportEdge(
                    source_module=source_file,
                    target_module=target_module,
                    names=names,
                ))

    return ImportGraph(edges=edges)


def save_import_graph(ig: ImportGraph, project_root: Path) -> Path:
    """Write imports.json to .codegraph/workflow/."""
    dest = resolve_path(project_root, WORKFLOW_DIR, "imports.json")
    atomic_write(dest, ig.to_dict())
    logger.info("Saved import graph (%d edges) → %s", len(ig.edges), dest)
    return dest


def load_import_graph(project_root: Path) -> ImportGraph:
    """Load imports.json."""
    path = resolve_path(project_root, WORKFLOW_DIR, "imports.json")
    if not path.exists():
        return ImportGraph()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return ImportGraph.from_dict(data)
    except (json.JSONDecodeError, KeyError):
        return ImportGraph()


# ═══════════════════════════════════════════════════════════════════════
# F-034 — Workflow level validation
# ═══════════════════════════════════════════════════════════════════════

_VALID_LEVELS = {"function", "class", "module"}


def validate_level(level: str) -> str:
    """Validate and return the workflow level (F-034)."""
    if level not in _VALID_LEVELS:
        raise ValueError(
            f"Invalid workflow level '{level}'. "
            f"Valid levels: {sorted(_VALID_LEVELS)}"
        )
    return level


# ═══════════════════════════════════════════════════════════════════════
# F-018 — Workflow build orchestrator
# ═══════════════════════════════════════════════════════════════════════


def _collect_call_sites_and_imports(
    graph0: Graph0,
    project_root: Path,
) -> Tuple[Dict[str, List[Any]], Dict[str, List[Any]]]:
    """Re-extract call sites and imports from source files for edge building."""
    from codegraph.extractor import (
        extract_file,
        CallSite,
    )
    from codegraph.utils.ids import normalize_path

    call_sites: Dict[str, List[Any]] = {}
    imports: Dict[str, List[Any]] = {}

    # Group nodes by file
    files: Set[str] = {n.file for n in graph0.nodes}
    for rel_file in files:
        abs_path = project_root / rel_file
        if not abs_path.exists():
            continue
        try:
            result = extract_file(abs_path, project_root)
        except Exception:
            continue

        imports[rel_file] = result.imports
        # Map call sites from function name → node_id based
        for node in result.nodes:
            fname = node.id.rsplit("::", 1)[-1] if "::" in node.id else ""
            if fname in result.call_sites:
                call_sites[node.id] = result.call_sites[fname]

    return call_sites, imports


def build_workflow(
    project_root: Path,
    config: Optional[CodegraphConfig] = None,
    *,
    trace: bool = False,
    archi: bool = False,
    trace_all: bool = False,
    include_imports: bool = False,
    level: str = "function",
) -> Workflow:
    """Top-level workflow build orchestrator (F-018, F-026, F-032, F-034, F-035).

    Coordinates static analysis, optional tracing, filtering, and output.
    """
    t0 = time.monotonic()

    # F-034 — validate level
    level = validate_level(level)

    if config is None:
        config = load_config(project_root)

    # a. Load Graph_0
    from codegraph.extractor import load_graph0
    graph0 = load_graph0(project_root)
    if not graph0.nodes:
        logger.warning("Empty Graph_0 — nothing to build")
        return Workflow(level=level)

    # b. Collect call sites and imports from source
    call_sites, imports_data = _collect_call_sites_and_imports(graph0, project_root)

    # b. Build static edges (F-001)
    static_edges, unresolved = build_static_edges(graph0, call_sites, imports_data)
    logger.info("Static edges: %d, unresolved calls: %d", len(static_edges), len(unresolved))

    # Build dynamic edges (F-012)
    dynamic_edges = build_dynamic_edges(unresolved)

    # c/d/e. Run traces if requested (F-009, F-026, F-027)
    trace_edges: List[WorkflowEdge] = []
    test_edges: List[WorkflowEdge] = []
    trace_mode = "static_only"

    if trace or trace_all:
        cov_data = run_trace(project_root, test_dir="tests")
        if cov_data:
            trace_edges = parse_trace_data(cov_data, graph0)
            test_edges = build_test_edges(cov_data, graph0)
            trace_mode = "traced"
        else:
            logger.warning("Trace produced no data — using static only")
            trace_mode = "trace_failed"

    if archi or trace_all:
        archi_data = run_trace(project_root, archi=True)
        if archi_data:
            trace_edges.extend(parse_trace_data(archi_data, graph0))
            if trace_mode == "static_only":
                trace_mode = "archi_only"
            elif trace_mode == "traced":
                trace_mode = "traced_all"

    # F-017 — optional import edges
    import_edges: Optional[List[WorkflowEdge]] = None
    if include_imports:
        import_edges = build_import_edges(imports_data, graph0)

    # g. Merge all edges (F-013)
    all_edges_list = merge_edges(
        static_edges,
        trace=trace_edges or None,
        test=test_edges or None,
        dynamic=dynamic_edges or None,
    )
    if import_edges:
        all_edges_list = merge_edges(all_edges_list, trace=import_edges)

    # h. Apply filters (F-007)
    from codegraph.filters import FilterPipeline
    pipeline = FilterPipeline.from_config(
        ["dunder", "logging", "stdlib", "test_harness"],
    )
    filtered_edges, filter_result = pipeline.apply(all_edges_list)
    logger.info(
        "Filters: %d → %d edges (removed %d)",
        filter_result.input_count,
        filter_result.output_count,
        filter_result.input_count - filter_result.output_count,
    )

    # i. Compress if needed (F-015, F-016)
    if level == "module":
        filtered_edges = compress_to_module(filtered_edges)
    elif level == "class":
        filtered_edges = compress_to_class(filtered_edges)

    # Create workflow object
    workflow = Workflow(level=level, edges=filtered_edges)

    # F-035 — metadata header
    elapsed = time.monotonic() - t0
    metadata = {
        "built_at": workflow.built_at,
        "level": level,
        "trace_mode": trace_mode,
        "filters_applied": pipeline.filter_names,
        "edge_count": len(filtered_edges),
        "node_count": len({e.source for e in filtered_edges} | {e.target for e in filtered_edges}),
        "build_time_s": round(elapsed, 2),
    }

    # j. Write workflow.json (F-014)
    write_workflow(workflow, project_root, metadata=metadata)

    # F-031 — always build import dependencies separately
    ig = build_import_dependencies(graph0, imports_data)
    save_import_graph(ig, project_root)

    logger.info("Workflow built in %.2fs: %d edges", elapsed, len(filtered_edges))
    return workflow
