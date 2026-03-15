"""codegraph.runtime_graph — Runtime behaviour extraction (Graph3).

Extracts dynamic/runtime information that static AST analysis cannot fully capture:
  - Service call patterns (HTTP, gRPC)
  - Database access patterns (queries, table references)
  - Message queue patterns (publish/subscribe)
    - Event dispatch/pub-sub flows
    - Runtime worker/queue interactions
    - Frontend ↔ backend API interactions (cross-language)
  - File I/O patterns
  - Environment variable usage

This enriches the static call graph with runtime edges, giving
a more complete picture of system architecture.

Usage::

    from codegraph.runtime_graph import extract_runtime_edges
    edges = extract_runtime_edges(project_root)
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Set

from codegraph.logging_config import get_logger

logger = get_logger("runtime_graph")

RUNTIME_FILE = "runtime_edges.json"  # backwards-compatible alias
GRAPH3_FILE = "graph3_runtime.json"


@dataclass
class RuntimeEdge:
    """A runtime-discovered dependency edge."""

    source_file: str
    source_node: str
    edge_type: str  # http_call, db_query, mq_publish, file_io, env_var
    target: str  # URL pattern, table name, queue name, file path, var name
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "source_file": self.source_file,
            "source_node": self.source_node,
            "edge_type": self.edge_type,
            "target": self.target,
        }
        if self.details:
            d["details"] = self.details
        return d


@dataclass
class RuntimeGraph:
    """Collection of runtime edges discovered in a project."""

    edges: List[RuntimeEdge] = field(default_factory=list)
    files_scanned: int = 0
    edge_types: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "graph": "graph3",
            "edges": [e.to_dict() for e in self.edges],
            "files_scanned": self.files_scanned,
            "edge_types": self.edge_types,
            "total_edges": len(self.edges),
        }

    def format(self) -> str:
        lines = [f"Runtime Graph: {len(self.edges)} edges "
                 f"from {self.files_scanned} files"]
        if self.edge_types:
            lines.append("  Edge types:")
            for etype, count in sorted(self.edge_types.items(),
                                       key=lambda x: -x[1]):
                lines.append(f"    {etype}: {count}")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# Detection Patterns
# ═══════════════════════════════════════════════════════════════════════

# HTTP client calls
_HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}

# DB access patterns
_DB_PATTERNS = {
    "execute", "executemany", "fetchone", "fetchall", "fetchmany",
    "cursor", "query",
}

# Message queue patterns
_MQ_PATTERNS = {
    "publish", "subscribe", "send_message", "receive_message",
    "basic_publish", "basic_consume",
}

_EVENT_PATTERNS = {
    "emit", "dispatch", "dispatch_event", "socket_emit",
}


# ═══════════════════════════════════════════════════════════════════════
# AST Visitor
# ═══════════════════════════════════════════════════════════════════════


class RuntimeEdgeVisitor(ast.NodeVisitor):
    """AST visitor that extracts runtime interaction patterns."""

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self.edges: List[RuntimeEdge] = []
        self._current_func: str = "<module>"
        self._current_class: str = ""

    @property
    def _source_node(self) -> str:
        parts = [self.file_path]
        if self._current_class:
            parts.append(self._current_class)
        parts.append(self._current_func)
        return "::".join(parts)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        old_func = self._current_func
        self._current_func = node.name
        self.generic_visit(node)
        self._current_func = old_func

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        old_class = self._current_class
        self._current_class = node.name
        self.generic_visit(node)
        self._current_class = old_class

    def visit_Call(self, node: ast.Call) -> None:
        self._check_http_call(node)
        self._check_db_call(node)
        self._check_mq_call(node)
        self._check_event_call(node)
        self._check_queue_worker_call(node)
        self._check_rpc_call(node)
        self._check_env_var(node)
        self.generic_visit(node)

    def _check_http_call(self, node: ast.Call) -> None:
        """Detect requests.get(...), httpx.post(...), etc."""
        if not isinstance(node.func, ast.Attribute):
            return
        method = node.func.attr.lower()
        if method not in _HTTP_METHODS:
            return
        # Exclude known non-HTTP receivers (e.g. os.environ.get, dict.get)
        value = node.func.value
        if isinstance(value, ast.Attribute) and value.attr == "environ":
            return
        if isinstance(value, ast.Name) and value.id in ("os", "dict", "self"):
            return
        # Extract URL argument if it's a string literal
        url = "<dynamic>"
        if node.args and isinstance(node.args[0], ast.Constant):
            url = str(node.args[0].value)
        self.edges.append(RuntimeEdge(
            source_file=self.file_path,
            source_node=self._source_node,
            edge_type="http_call",
            target=url,
            details={"method": method.upper()},
        ))

    def _check_db_call(self, node: ast.Call) -> None:
        """Detect cursor.execute(...), session.query(...), etc."""
        if not isinstance(node.func, ast.Attribute):
            return
        if node.func.attr not in _DB_PATTERNS:
            return
        # Try to extract SQL or table name
        target = "<dynamic>"
        if node.args and isinstance(node.args[0], ast.Constant):
            raw = str(node.args[0].value)
            # Extract table name from simple SQL
            match = re.search(
                r"(?:FROM|INTO|UPDATE|JOIN)\s+(\w+)",
                raw,
                re.IGNORECASE,
            )
            if match:
                target = match.group(1)
            else:
                target = raw[:80]
        self.edges.append(RuntimeEdge(
            source_file=self.file_path,
            source_node=self._source_node,
            edge_type="db_query",
            target=target,
            details={"operation": node.func.attr},
        ))

    def _check_mq_call(self, node: ast.Call) -> None:
        """Detect message queue publish/subscribe calls."""
        if not isinstance(node.func, ast.Attribute):
            return
        if node.func.attr not in _MQ_PATTERNS:
            return
        target = "<dynamic>"
        # Try to find queue/topic name in kwargs
        for kw in node.keywords:
            if kw.arg in ("queue", "topic", "routing_key", "exchange"):
                if isinstance(kw.value, ast.Constant):
                    target = str(kw.value.value)
                    break
        self.edges.append(RuntimeEdge(
            source_file=self.file_path,
            source_node=self._source_node,
            edge_type="mq_publish" if "publish" in node.func.attr
            else "mq_subscribe",
            target=target,
            details={"operation": node.func.attr},
        ))

    def _check_event_call(self, node: ast.Call) -> None:
        if not isinstance(node.func, ast.Attribute):
            return
        op = node.func.attr
        if op not in _EVENT_PATTERNS and op not in {"emit", "dispatch"}:
            return
        target = "<dynamic>"
        if node.args and isinstance(node.args[0], ast.Constant):
            target = str(node.args[0].value)
        self.edges.append(RuntimeEdge(
            source_file=self.file_path,
            source_node=self._source_node,
            edge_type="event",
            target=target,
            details={"operation": op},
        ))

    def _check_queue_worker_call(self, node: ast.Call) -> None:
        if not isinstance(node.func, ast.Attribute):
            return
        op = node.func.attr.lower()
        if op not in {"delay", "apply_async", "enqueue", "dequeue", "put", "get"}:
            return
        receiver = ""
        try:
            receiver = ast.unparse(node.func.value).lower()
        except Exception:
            receiver = ""
        queue_like = any(tok in receiver for tok in ("queue", "celery", "broker", "channel", "worker"))
        if op in {"put", "get", "enqueue", "dequeue"} and not queue_like:
            return
        kind = "queue" if op in {"enqueue", "dequeue", "put", "get"} else "worker"
        self.edges.append(RuntimeEdge(
            source_file=self.file_path,
            source_node=self._source_node,
            edge_type=kind,
            target="<runtime>",
            details={"operation": op},
        ))

    def _check_rpc_call(self, node: ast.Call) -> None:
        if not isinstance(node.func, ast.Attribute):
            return
        op = node.func.attr.lower()
        if op not in {"rpc_call", "call", "invoke"}:
            return
        value = node.func.value
        if isinstance(value, ast.Name) and value.id.lower() in {"grpc", "rpc", "client"}:
            self.edges.append(RuntimeEdge(
                source_file=self.file_path,
                source_node=self._source_node,
                edge_type="rpc_call",
                target="<rpc>",
                details={"operation": op},
            ))

    def _check_env_var(self, node: ast.Call) -> None:
        """Detect os.environ.get(...), os.getenv(...)."""
        if not isinstance(node.func, ast.Attribute):
            return
        attr = node.func.attr
        # os.getenv("VAR")
        if attr == "getenv" and isinstance(node.func.value, ast.Name):
            if node.func.value.id == "os":
                if node.args and isinstance(node.args[0], ast.Constant):
                    self.edges.append(RuntimeEdge(
                        source_file=self.file_path,
                        source_node=self._source_node,
                        edge_type="env_var",
                        target=str(node.args[0].value),
                    ))
            return
        # os.environ.get("VAR") or os.environ["VAR"]
        if attr == "get" and isinstance(node.func.value, ast.Attribute):
            if (node.func.value.attr == "environ"
                    and isinstance(node.func.value.value, ast.Name)
                    and node.func.value.value.id == "os"):
                if node.args and isinstance(node.args[0], ast.Constant):
                    self.edges.append(RuntimeEdge(
                        source_file=self.file_path,
                        source_node=self._source_node,
                        edge_type="env_var",
                        target=str(node.args[0].value),
                    ))


# ═══════════════════════════════════════════════════════════════════════
# Main Extraction
# ═══════════════════════════════════════════════════════════════════════


def extract_runtime_edges(
    project_root: Path,
    *,
    include_patterns: List[str] | None = None,
    exclude_patterns: List[str] | None = None,
) -> RuntimeGraph:
    """Extract runtime edges from all Python files in the project.

    Scans source files for HTTP calls, database queries, message queue
    interactions, and environment variable access.
    """
    graph = RuntimeGraph()

    py_files = sorted(project_root.rglob("*.py"))
    js_files = sorted(project_root.rglob("*.js")) + sorted(project_root.rglob("*.jsx"))
    ts_files = sorted(project_root.rglob("*.ts")) + sorted(project_root.rglob("*.tsx"))
    if exclude_patterns is None:
        exclude_patterns = ["__pycache__", ".codegraph", "node_modules",
                           ".git", ".venv", "venv"]

    for py_file in py_files:
        rel = py_file.relative_to(project_root).as_posix()
        if any(pat in rel for pat in exclude_patterns):
            continue
        if include_patterns and not any(pat in rel for pat in include_patterns):
            continue

        try:
            source = py_file.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=rel)
        except (SyntaxError, OSError):
            continue

        visitor = RuntimeEdgeVisitor(rel)
        visitor.visit(tree)

        graph.edges.extend(visitor.edges)
        graph.files_scanned += 1

    _extract_js_runtime_edges(project_root, js_files + ts_files, graph, include_patterns, exclude_patterns)

    _add_cross_language_edges(project_root, graph)

    # Compute edge type counts
    for edge in graph.edges:
        graph.edge_types[edge.edge_type] = (
            graph.edge_types.get(edge.edge_type, 0) + 1
        )

    return graph


def save_runtime_graph(
    project_root: Path, graph: RuntimeGraph,
) -> Path:
    """Save runtime graph (Graph3) to .codegraph/graphs/graph3_runtime.json.

    Also writes runtime_edges.json for backwards compatibility.
    """
    out_dir = project_root / ".codegraph" / "graphs"
    out_dir.mkdir(parents=True, exist_ok=True)
    data = json.dumps(graph.to_dict(), indent=2, ensure_ascii=False)
    path = out_dir / GRAPH3_FILE
    path.write_text(
        data,
        encoding="utf-8",
    )
    legacy = out_dir / RUNTIME_FILE
    legacy.write_text(
        json.dumps(graph.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Saved runtime graph: %d edges", len(graph.edges))
    return path


def load_runtime_graph(project_root: Path) -> RuntimeGraph | None:
    """Load runtime graph from disk."""
    path = project_root / ".codegraph" / "graphs" / GRAPH3_FILE
    if not path.exists():
        path = project_root / ".codegraph" / "graphs" / RUNTIME_FILE
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    graph = RuntimeGraph(
        files_scanned=data.get("files_scanned", 0),
        edge_types=data.get("edge_types", {}),
    )
    for e in data.get("edges", []):
        graph.edges.append(RuntimeEdge(
            source_file=e["source_file"],
            source_node=e["source_node"],
            edge_type=e["edge_type"],
            target=e["target"],
            details=e.get("details", {}),
        ))
    return graph


def _extract_js_runtime_edges(
    project_root: Path,
    files: List[Path],
    graph: RuntimeGraph,
    include_patterns: List[str] | None,
    exclude_patterns: List[str] | None,
) -> None:
    for file_path in files:
        rel = file_path.relative_to(project_root).as_posix()
        if exclude_patterns and any(pat in rel for pat in exclude_patterns):
            continue
        if include_patterns and not any(pat in rel for pat in include_patterns):
            continue
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        # fetch("/api/..."), axios.get("/api/..."), socket.emit("event"), dispatch(...)
        for m in re.finditer(r"fetch\((['\"])([^'\"]+)\1", content):
            graph.edges.append(RuntimeEdge(
                source_file=rel,
                source_node=f"{rel}::<module>",
                edge_type="fetch",
                target=m.group(2),
            ))
        for m in re.finditer(r"axios\.(get|post|put|patch|delete)\((['\"])([^'\"]+)\2", content):
            graph.edges.append(RuntimeEdge(
                source_file=rel,
                source_node=f"{rel}::<module>",
                edge_type="axios",
                target=m.group(3),
                details={"method": m.group(1).upper()},
            ))
        for m in re.finditer(r"socket\.emit\((['\"])([^'\"]+)\1", content):
            graph.edges.append(RuntimeEdge(
                source_file=rel,
                source_node=f"{rel}::<module>",
                edge_type="socket",
                target=m.group(2),
            ))
        for _ in re.finditer(r"\bdispatch\(", content):
            graph.edges.append(RuntimeEdge(
                source_file=rel,
                source_node=f"{rel}::<module>",
                edge_type="dispatch",
                target="<action>",
            ))
        graph.files_scanned += 1


def _add_cross_language_edges(project_root: Path, graph: RuntimeGraph) -> None:
    # Build route map from python decorators
    route_targets: Dict[str, str] = {}
    for py_file in project_root.rglob("*.py"):
        rel = py_file.relative_to(project_root).as_posix()
        if any(skip in rel for skip in (".codegraph", "__pycache__", ".venv", "venv")):
            continue
        try:
            src = py_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in re.finditer(r"@\w+\.(?:get|post|put|patch|delete)\((['\"])(/[^'\"]*)\1\)", src):
            route_targets[match.group(2)] = rel

    if not route_targets:
        return

    additions: List[RuntimeEdge] = []
    for edge in graph.edges:
        if edge.edge_type not in {"fetch", "axios", "http_call"}:
            continue
        target = edge.target
        for route, backend_file in route_targets.items():
            if target == route or target.endswith(route):
                additions.append(RuntimeEdge(
                    source_file=edge.source_file,
                    source_node=edge.source_node,
                    edge_type="frontend_to_backend",
                    target=f"{backend_file}::{route}",
                    details={"from": target, "to": route},
                ))
                break

    graph.edges.extend(additions)
