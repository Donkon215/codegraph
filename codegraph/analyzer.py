"""codegraph.analyzer — Orphan analysis, policy diff, task generation.

Group I: I-001 through I-006, I-018–I-020, I-023, I-025–I-026,
I-029–I-032.
"""

from __future__ import annotations

import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from codegraph.constants import (
    CONVERGENCE_THRESHOLD,
    LAYER_PROJECT,
    LAYER_TEST,
    MAX_ITERATIONS,
)
from codegraph.logging_config import get_logger
from codegraph.models.graph0 import Graph0
from codegraph.models.graph1 import Graph1
from codegraph.models.suggested_workflow import SuggestedWorkflow
from codegraph.models.workflow import Workflow
from codegraph.storage import resolve_path

logger = get_logger("analyzer")


# ═══════════════════════════════════════════════════════════════════════
# Dataclasses
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class ClassifiedOrphan:
    """An orphan node with a classification (I-002)."""

    node_id: str
    classification: str  # "entry_point" / "dead_code" / "new_code" / "disconnected"
    reason: str = ""


@dataclass
class StaleIntent:
    """A node whose intent may be outdated (I-003)."""

    node_id: str
    old_hash: str
    new_hash: str
    current_intent: str


@dataclass
class CoverageGap:
    """A production function without test coverage (I-004)."""

    node_id: str
    file: str
    node_type: str


@dataclass
class MissingEdge:
    """A heuristically detected missing edge (I-026)."""

    source: str
    target: str
    reason: str
    confidence: str = "heuristic"


@dataclass
class CycleMismatch:
    """Cycle in actual workflow involving suggested rules (I-023)."""

    cycle_nodes: List[str]
    involved_rules: List[str]


@dataclass
class Finding:
    """A single analysis finding. Used to generate tasks."""

    finding_type: str  # "policy_violation" / "orphan" / "stale_intent" / "coverage_gap" / "missing_intent" / "missing_edge" / "cycle_mismatch"
    severity: str = "warning"
    node_id: str = ""
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AnalysisResult:
    """Complete analysis output (I-001)."""

    findings: List[Finding] = field(default_factory=list)
    orphans: List[ClassifiedOrphan] = field(default_factory=list)
    stale_intents: List[StaleIntent] = field(default_factory=list)
    coverage_gaps: List[CoverageGap] = field(default_factory=list)
    missing_intents: List[str] = field(default_factory=list)
    missing_edges: List[MissingEdge] = field(default_factory=list)
    cycle_mismatches: List[CycleMismatch] = field(default_factory=list)
    violations: List[Any] = field(default_factory=list)  # PolicyViolation from suggest.py
    metadata: Dict[str, Any] = field(default_factory=dict)  # Extensible metadata (R-016)

    @property
    def total_findings(self) -> int:
        return len(self.findings)

    @property
    def error_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "warning")


# ═══════════════════════════════════════════════════════════════════════
# I-001 — Analyzer Core Engine
# ═══════════════════════════════════════════════════════════════════════


def analyze(
    project_root: Path,
    graph0: Graph0,
    graph1: Graph1,
    workflow: Workflow,
    suggested_workflow: Optional[SuggestedWorkflow] = None,
    index: Any = None,
    *,
    affected_nodes: Optional[Set[str]] = None,
) -> AnalysisResult:
    """Run all analyses and return combined results (I-001).

    When *affected_nodes* is provided (CAS integration), analysis is
    scoped to only those nodes for faster incremental evaluation.
    """
    result = AnalysisResult()

    # Build layer map from graph1
    layer_map: Dict[str, int] = {}
    for g1n in graph1.nodes:
        layer_map[g1n.id] = g1n.layer

    # I-002 — Orphan analysis
    from codegraph.workflow import find_orphans
    orphan_ids = find_orphans(workflow, graph0, layer_map)
    if affected_nodes is not None:
        orphan_ids = [o for o in orphan_ids if o in affected_nodes]
    result.orphans = classify_orphans(orphan_ids, graph0, graph1)
    for orph in result.orphans:
        result.findings.append(Finding(
            finding_type="orphan",
            severity="warning",
            node_id=orph.node_id,
            message=f"Orphan ({orph.classification}): {orph.node_id}",
            details={"classification": orph.classification, "reason": orph.reason},
        ))

    # I-003 — Stale intent detection
    result.stale_intents = find_stale_intents(graph0, graph1, affected_nodes)
    for si in result.stale_intents:
        result.findings.append(Finding(
            finding_type="stale_intent",
            severity="warning",
            node_id=si.node_id,
            message=f"Stale intent: {si.node_id} (hash changed {si.old_hash} → {si.new_hash})",
        ))

    # I-004 — Coverage gaps
    result.coverage_gaps = find_coverage_gaps(graph0, graph1, workflow, index, affected_nodes)
    for cg in result.coverage_gaps:
        result.findings.append(Finding(
            finding_type="coverage_gap",
            severity="warning",
            node_id=cg.node_id,
            message=f"No test coverage: {cg.node_id}",
        ))

    # I-005 — Missing intents
    result.missing_intents = find_missing_intents(graph0, graph1, layer_map, affected_nodes)
    for nid in result.missing_intents:
        result.findings.append(Finding(
            finding_type="missing_intent",
            severity="info",
            node_id=nid,
            message=f"Missing intent: {nid}",
        ))

    # I-006 — Policy violations
    if suggested_workflow and suggested_workflow.rules:
        from codegraph.suggest import detect_violations, policy_diff
        violations = detect_violations(suggested_workflow, workflow, graph0, graph1)
        result.violations = violations
        for v in violations:
            result.findings.append(Finding(
                finding_type="policy_violation",
                severity=v.severity,
                node_id=v.source,
                message=f"Policy violation [{v.rule_id}]: {v.source} → {v.target} ({v.rule_type})",
                details={"rule_id": v.rule_id, "rule_type": v.rule_type, "reason": v.reason},
            ))

    # I-026 — Heuristic missing edges
    result.missing_edges = detect_missing_edges(workflow, graph0, affected_nodes)
    for me in result.missing_edges:
        result.findings.append(Finding(
            finding_type="missing_edge",
            severity="info",
            node_id=me.source,
            message=f"Possible missing edge: {me.source} → {me.target}",
            details={"reason": me.reason},
        ))

    # I-023 — Cycle mismatch detection
    if suggested_workflow and suggested_workflow.rules:
        result.cycle_mismatches = detect_cycle_mismatches(
            workflow, suggested_workflow, graph0, graph1,
        )
        for cm in result.cycle_mismatches:
            result.findings.append(Finding(
                finding_type="cycle_mismatch",
                severity="warning",
                message=f"Cycle involving rule nodes: {' → '.join(cm.cycle_nodes)}",
                details={"rules": cm.involved_rules},
            ))

    # Sort findings by severity (error > warning > info)
    sev_order = {"error": 0, "warning": 1, "info": 2}
    result.findings.sort(key=lambda f: (sev_order.get(f.severity, 9), f.finding_type))

    return result


# ═══════════════════════════════════════════════════════════════════════
# I-002 — Orphan Node Analysis
# ═══════════════════════════════════════════════════════════════════════

_ENTRY_PREFIXES = ("test_", "conftest", "__main__")
_ENTRY_SUFFIXES = ("::main", "::cli", "::app")


def classify_orphans(
    orphan_ids: List[str],
    graph0: Graph0,
    graph1: Graph1,
) -> List[ClassifiedOrphan]:
    """Classify orphan nodes by likely cause (I-002)."""
    results: List[ClassifiedOrphan] = []
    for nid in orphan_ids:
        g0_node = graph0.get_node(nid)
        g1_node = graph1.get_node(nid)
        classification = "dead_code"
        reason = "No callers, no callees"

        if g0_node is None:
            continue

        # Entry point: __main__, cli, test_, etc.
        lower_id = nid.lower()
        if any(lower_id.startswith(pfx) or f"::{pfx}" in lower_id for pfx in _ENTRY_PREFIXES):
            classification = "entry_point"
            reason = "Likely entry point or test function"
        elif any(lower_id.endswith(sfx) for sfx in _ENTRY_SUFFIXES):
            classification = "entry_point"
            reason = "Likely entry point (main/cli/app)"
        elif g0_node.type == "class":
            classification = "disconnected"
            reason = "Class with no method calls observed"
        elif g1_node and g1_node.intent:
            classification = "disconnected"
            reason = "Has intent but no workflow edges"
        elif g1_node and g1_node.intent_body_hash != g0_node.body_hash:
            classification = "new_code"
            reason = "Body hash differs from intent baseline"

        results.append(ClassifiedOrphan(
            node_id=nid,
            classification=classification,
            reason=reason,
        ))
    return results


# ═══════════════════════════════════════════════════════════════════════
# I-003 — Stale Intent Detection
# ═══════════════════════════════════════════════════════════════════════


def find_stale_intents(
    graph0: Graph0,
    graph1: Graph1,
    affected_nodes: Optional[Set[str]] = None,
) -> List[StaleIntent]:
    """Find nodes where body_hash changed since intent was set (I-003)."""
    stale: List[StaleIntent] = []
    for g1_node in graph1.nodes:
        if not g1_node.intent or not g1_node.intent.strip():
            continue
        if not g1_node.intent_body_hash:
            continue
        if affected_nodes is not None and g1_node.id not in affected_nodes:
            continue
        g0_node = graph0.get_node(g1_node.id)
        if g0_node is None:
            continue
        if g0_node.body_hash != g1_node.intent_body_hash:
            stale.append(StaleIntent(
                node_id=g1_node.id,
                old_hash=g1_node.intent_body_hash,
                new_hash=g0_node.body_hash,
                current_intent=g1_node.intent,
            ))
    return stale


# ═══════════════════════════════════════════════════════════════════════
# I-004 — Coverage Gap Detection
# ═══════════════════════════════════════════════════════════════════════


def find_coverage_gaps(
    graph0: Graph0,
    graph1: Graph1,
    workflow: Workflow,
    index: Any = None,
    affected_nodes: Optional[Set[str]] = None,
) -> List[CoverageGap]:
    """Find Layer 3 functions without test coverage (I-004)."""
    # Build set of production nodes with test edges
    tested: Set[str] = set()

    # Check workflow for test edges
    for edge in workflow.edges:
        if edge.confidence == "test" or edge.edge_type == "test":
            tested.add(edge.target)

    # Also check index if available
    if index is not None:
        try:
            for g1_node in graph1.nodes:
                if g1_node.layer == LAYER_PROJECT:
                    tests = index.get_tests_for_node(g1_node.id)
                    if tests:
                        tested.add(g1_node.id)
        except Exception:
            pass  # Index may not have tests table

    gaps: List[CoverageGap] = []
    for g1_node in graph1.nodes:
        if g1_node.layer != LAYER_PROJECT:
            continue
        if affected_nodes is not None and g1_node.id not in affected_nodes:
            continue
        if g1_node.id in tested:
            continue
        g0_node = graph0.get_node(g1_node.id)
        if g0_node is None:
            continue
        # Only report functions and methods (not modules/classes)
        if g0_node.type not in ("function", "method"):
            continue
        gaps.append(CoverageGap(
            node_id=g1_node.id,
            file=g0_node.file,
            node_type=g0_node.type,
        ))
    return gaps


# ═══════════════════════════════════════════════════════════════════════
# I-005 — Missing Intent Detection
# ═══════════════════════════════════════════════════════════════════════


def find_missing_intents(
    graph0: Graph0,
    graph1: Graph1,
    layer_map: Optional[Dict[str, int]] = None,
    affected_nodes: Optional[Set[str]] = None,
) -> List[str]:
    """Find nodes without intent annotations (I-005).  Only Layer 3/4."""
    g1_intents = {n.id for n in graph1.nodes if n.intent and n.intent.strip()}
    missing: List[str] = []
    for node in graph0.nodes:
        if affected_nodes is not None and node.id not in affected_nodes:
            continue
        layer = (layer_map or {}).get(node.id, LAYER_PROJECT)
        if layer < LAYER_PROJECT:
            continue
        if node.id not in g1_intents:
            missing.append(node.id)
    return sorted(missing)


# ═══════════════════════════════════════════════════════════════════════
# I-018 — Convergence Tracker
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class IterationMetrics:
    """Metrics for a single repair loop iteration."""

    iteration: int
    orphan_count: int = 0
    edge_count: int = 0
    task_count: int = 0
    finding_count: int = 0
    human_review_count: int = 0


class ConvergenceTracker:
    """Track convergence across repair loop iterations (I-018)."""

    def __init__(self, max_iterations: int = MAX_ITERATIONS) -> None:
        self.max_iterations = max_iterations
        self.history: List[IterationMetrics] = []

    def record(self, metrics: IterationMetrics) -> None:
        self.history.append(metrics)

    def is_orphan_stagnant(self) -> bool:
        """Same orphan count for 3 consecutive iterations."""
        if len(self.history) < 3:
            return False
        last3 = [m.orphan_count for m in self.history[-3:]]
        return last3[0] == last3[1] == last3[2]

    def is_edge_stabilized(self) -> bool:
        """Edge count within ±5% of previous iteration."""
        if len(self.history) < 2:
            return False
        prev = self.history[-2].edge_count
        curr = self.history[-1].edge_count
        if prev == 0:
            return curr == 0
        return abs(curr - prev) / prev <= CONVERGENCE_THRESHOLD

    def is_max_iterations(self) -> bool:
        return len(self.history) >= self.max_iterations

    def is_all_human_review(self) -> bool:
        """All remaining tasks are flag_for_human_review."""
        if not self.history:
            return False
        last = self.history[-1]
        return last.task_count > 0 and last.human_review_count == last.task_count

    def should_stop(self) -> Tuple[bool, str]:
        """Check all convergence criteria.  Returns (stop, reason)."""
        if self.is_max_iterations():
            return True, f"Max iterations reached ({self.max_iterations})"
        if self.is_orphan_stagnant():
            return True, "Orphan count stagnant for 3 iterations"
        if self.is_edge_stabilized() and len(self.history) >= 3:
            return True, "Edge count stabilized (±5%)"
        if self.is_all_human_review():
            return True, "All remaining tasks require human review"
        return False, ""


# ═══════════════════════════════════════════════════════════════════════
# I-019 — Repair Loop Orchestrator
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class RepairResult:
    """Result of the full repair loop (I-019)."""

    iterations: int = 0
    stop_reason: str = ""
    history: List[IterationMetrics] = field(default_factory=list)
    final_findings: int = 0


def repair_loop(
    project_root: Path,
    *,
    max_iterations: int = MAX_ITERATIONS,
    dry_run: bool = True,
) -> RepairResult:
    """Run the analyze → tasks → response → apply loop (I-019).

    With *dry_run=True* (default), only runs analysis without applying
    changes.  Full automation requires Groups J/K.
    """
    tracker = ConvergenceTracker(max_iterations=max_iterations)
    result = RepairResult()

    from codegraph.extractor import load_graph0
    from codegraph.annotator import load_graph1
    from codegraph.workflow import load_workflow
    from codegraph.suggest import load_suggested_workflow

    for iteration in range(1, max_iterations + 1):
        graph0 = load_graph0(project_root)
        graph1 = load_graph1(project_root)
        workflow = load_workflow(project_root)
        suggested = load_suggested_workflow(project_root)

        index = None
        try:
            from codegraph.index import IndexStore
            index = IndexStore(project_root)
        except FileNotFoundError:
            pass

        analysis = analyze(
            project_root, graph0, graph1, workflow, suggested, index,
        )

        if index is not None:
            index.close()

        # Build layer map for orphan count
        layer_map = {n.id: n.layer for n in graph1.nodes}
        from codegraph.workflow import find_orphans
        orphans = find_orphans(workflow, graph0, layer_map)

        metrics = IterationMetrics(
            iteration=iteration,
            orphan_count=len(orphans),
            edge_count=len(workflow.edges),
            finding_count=len(analysis.findings),
            task_count=len(analysis.findings),
        )
        tracker.record(metrics)

        logger.info(
            "Iteration %d: %d findings, %d orphans, %d edges",
            iteration, len(analysis.findings), len(orphans), len(workflow.edges),
        )

        should_stop, reason = tracker.should_stop()
        if should_stop or dry_run:
            result.iterations = iteration
            result.stop_reason = reason or ("dry run" if dry_run else "converged")
            result.history = tracker.history
            result.final_findings = len(analysis.findings)
            break

    return result


# ═══════════════════════════════════════════════════════════════════════
# I-020 — Analysis Caching
# ═══════════════════════════════════════════════════════════════════════


class AnalysisCache:
    """Cache analysis results keyed by graph_version (I-020)."""

    def __init__(self, project_root: Path) -> None:
        self._cache_dir = resolve_path(project_root, "cache")
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, version: int) -> Path:
        return self._cache_dir / f"analysis_v{version}.json"

    def get(self, graph_version: int) -> Optional[Dict[str, Any]]:
        path = self._cache_path(graph_version)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return None

    def put(self, graph_version: int, data: Dict[str, Any]) -> None:
        path = self._cache_path(graph_version)
        path.write_text(json.dumps(data), encoding="utf-8")

    def invalidate(self, graph_version: int) -> None:
        path = self._cache_path(graph_version)
        if path.exists():
            path.unlink()


# ═══════════════════════════════════════════════════════════════════════
# I-023 — Cycle Mismatch Detection
# ═══════════════════════════════════════════════════════════════════════


def detect_cycle_mismatches(
    workflow: Workflow,
    suggested: SuggestedWorkflow,
    graph0: Graph0,
    graph1: Graph1,
) -> List[CycleMismatch]:
    """Detect cycles in actual workflow that involve suggested rule nodes (I-023)."""
    # Collect nodes mentioned in rules
    rule_nodes: Set[str] = set()
    rule_by_node: Dict[str, List[str]] = defaultdict(list)
    for rule in suggested.rules:
        if rule.source:
            rule_nodes.add(rule.source)
            rule_by_node[rule.source].append(rule.id)
        if rule.target:
            rule_nodes.add(rule.target)
            rule_by_node[rule.target].append(rule.id)

    if not rule_nodes:
        return []

    # Build adjacency from workflow
    adj: Dict[str, Set[str]] = defaultdict(set)
    for edge in workflow.edges:
        adj[edge.source].add(edge.target)

    # DFS cycle detection limited to paths touching rule nodes
    mismatches: List[CycleMismatch] = []
    visited_cycles: Set[frozenset[str]] = set()

    for start in rule_nodes:
        if start not in adj:
            continue
        # BFS/DFS for short cycles (max depth 10)
        stack: List[Tuple[str, List[str]]] = [(start, [start])]
        seen_in_search: Set[str] = set()
        while stack:
            node, path = stack.pop()
            if len(path) > 10:
                continue
            for nxt in adj.get(node, set()):
                if nxt == start and len(path) > 1:
                    cycle_key = frozenset(path)
                    if cycle_key not in visited_cycles:
                        visited_cycles.add(cycle_key)
                        involved = []
                        for n in path:
                            involved.extend(rule_by_node.get(n, []))
                        if involved:
                            mismatches.append(CycleMismatch(
                                cycle_nodes=path,
                                involved_rules=list(set(involved)),
                            ))
                elif nxt not in seen_in_search and nxt not in set(path):
                    seen_in_search.add(nxt)
                    stack.append((nxt, path + [nxt]))

    return mismatches


# ═══════════════════════════════════════════════════════════════════════
# I-025 — Analysis Report Formatter
# ═══════════════════════════════════════════════════════════════════════


def format_analysis_report(analysis: AnalysisResult, *, as_json: bool = False) -> str:
    """Format the complete analysis report (I-025)."""
    if as_json:
        data = {
            "total_findings": analysis.total_findings,
            "errors": analysis.error_count,
            "warnings": analysis.warning_count,
            "orphans": len(analysis.orphans),
            "stale_intents": len(analysis.stale_intents),
            "coverage_gaps": len(analysis.coverage_gaps),
            "missing_intents": len(analysis.missing_intents),
            "violations": len(analysis.violations),
            "missing_edges": len(analysis.missing_edges),
            "findings": [
                {
                    "type": f.finding_type,
                    "severity": f.severity,
                    "node": f.node_id,
                    "message": f.message,
                }
                for f in analysis.findings
            ],
        }
        return json.dumps(data, indent=2)

    lines: List[str] = []
    lines.append("═══ Analysis Report ═══")
    lines.append(f"Total findings: {analysis.total_findings}")
    lines.append(f"  Errors:   {analysis.error_count}")
    lines.append(f"  Warnings: {analysis.warning_count}")
    lines.append("")

    if analysis.violations:
        lines.append(f"Policy Violations ({len(analysis.violations)}):")
        for v in analysis.violations:
            lines.append(f"  [{v.rule_id}] {v.source} → {v.target} ({v.rule_type})")
        lines.append("")

    if analysis.orphans:
        lines.append(f"Orphan Nodes ({len(analysis.orphans)}):")
        by_class = defaultdict(list)
        for o in analysis.orphans:
            by_class[o.classification].append(o.node_id)
        for cls, nodes in sorted(by_class.items()):
            lines.append(f"  {cls}: {len(nodes)}")
            for nid in nodes[:5]:
                lines.append(f"    {nid}")
            if len(nodes) > 5:
                lines.append(f"    ... and {len(nodes) - 5} more")
        lines.append("")

    if analysis.coverage_gaps:
        lines.append(f"Coverage Gaps ({len(analysis.coverage_gaps)}):")
        for cg in analysis.coverage_gaps[:10]:
            lines.append(f"  {cg.node_id} ({cg.file})")
        if len(analysis.coverage_gaps) > 10:
            lines.append(f"  ... and {len(analysis.coverage_gaps) - 10} more")
        lines.append("")

    if analysis.stale_intents:
        lines.append(f"Stale Intents ({len(analysis.stale_intents)}):")
        for si in analysis.stale_intents[:10]:
            lines.append(f"  {si.node_id}: {si.current_intent[:50]}...")
        lines.append("")

    if analysis.missing_intents:
        lines.append(f"Missing Intents ({len(analysis.missing_intents)}):")
        lines.append(f"  {len(analysis.missing_intents)} nodes without intent")
        lines.append("")

    if analysis.missing_edges:
        lines.append(f"Possible Missing Edges ({len(analysis.missing_edges)}):")
        for me in analysis.missing_edges[:5]:
            lines.append(f"  {me.source} → {me.target}: {me.reason}")
        lines.append("")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# I-026 — Missing Edge Detection (heuristic)
# ═══════════════════════════════════════════════════════════════════════


def detect_missing_edges(
    workflow: Workflow,
    graph0: Graph0,
    affected_nodes: Optional[Set[str]] = None,
) -> List[MissingEdge]:
    """Detect heuristically missing edges (I-026).

    Looks for patterns like:
    - __init__ without super().__init__ edge (for classes)
    - Module-level functions that import but never call sibling functions
    """
    missing: List[MissingEdge] = []
    # Heuristic: Find __init__ methods; if class has parent in same module,
    # check for super().__init__ edge
    init_nodes = [
        n for n in graph0.nodes
        if n.id.endswith("::__init__") and n.type == "method"
    ]

    for init_node in init_nodes:
        if affected_nodes is not None and init_node.id not in affected_nodes:
            continue
        # Extract class from init_node id pattern: file::Class::__init__
        parts = init_node.id.split("::")
        if len(parts) < 3:
            continue
        # Check if this __init__ has any callees
        edges_from = workflow.get_edges_from(init_node.id)
        if not edges_from:
            missing.append(MissingEdge(
                source=init_node.id,
                target="(super().__init__ or member setup)",
                reason="__init__ calls nothing — possibly missing setup logic",
            ))

    return missing


# ═══════════════════════════════════════════════════════════════════════
# I-029 — Parallel Analysis (for large codebases)
# ═══════════════════════════════════════════════════════════════════════


def analyze_parallel(
    project_root: Path,
    graph0: Graph0,
    graph1: Graph1,
    workflow: Workflow,
    suggested_workflow: Optional[SuggestedWorkflow] = None,
    index: Any = None,
) -> AnalysisResult:
    """Run independent analyses in parallel (I-029)."""
    result = AnalysisResult()
    layer_map = {n.id: n.layer for n in graph1.nodes}

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {}

        # Orphans
        from codegraph.workflow import find_orphans
        futures["orphans"] = executor.submit(
            lambda: classify_orphans(find_orphans(workflow, graph0, layer_map), graph0, graph1)
        )

        # Stale intents
        futures["stale"] = executor.submit(find_stale_intents, graph0, graph1)

        # Coverage gaps
        futures["coverage"] = executor.submit(
            find_coverage_gaps, graph0, graph1, workflow, index
        )

        # Missing intents
        futures["missing_intent"] = executor.submit(
            find_missing_intents, graph0, graph1, layer_map
        )

        for key, future in futures.items():
            try:
                value = future.result(timeout=30)
                if key == "orphans":
                    result.orphans = value
                elif key == "stale":
                    result.stale_intents = value
                elif key == "coverage":
                    result.coverage_gaps = value
                elif key == "missing_intent":
                    result.missing_intents = value
            except Exception as exc:
                logger.warning("Parallel analysis '%s' failed: %s", key, exc)

    # Policy violations — must run after scope cache is clear (not thread-safe)
    if suggested_workflow and suggested_workflow.rules:
        from codegraph.suggest import detect_violations
        result.violations = detect_violations(suggested_workflow, workflow, graph0, graph1)

    # Build findings list from all results
    for o in result.orphans:
        result.findings.append(Finding(
            finding_type="orphan", severity="warning", node_id=o.node_id,
            message=f"Orphan ({o.classification}): {o.node_id}",
        ))
    for si in result.stale_intents:
        result.findings.append(Finding(
            finding_type="stale_intent", severity="warning", node_id=si.node_id,
            message=f"Stale intent: {si.node_id}",
        ))
    for cg in result.coverage_gaps:
        result.findings.append(Finding(
            finding_type="coverage_gap", severity="warning", node_id=cg.node_id,
            message=f"No test coverage: {cg.node_id}",
        ))
    for nid in result.missing_intents:
        result.findings.append(Finding(
            finding_type="missing_intent", severity="info", node_id=nid,
            message=f"Missing intent: {nid}",
        ))
    for v in result.violations:
        result.findings.append(Finding(
            finding_type="policy_violation", severity=v.severity, node_id=v.source,
            message=f"Policy violation [{v.rule_id}]: {v.source} → {v.target}",
        ))

    return result


# ═══════════════════════════════════════════════════════════════════════
# I-030 — Full Analyze Command Orchestrator
# ═══════════════════════════════════════════════════════════════════════


def run_analyze(project_root: Path, *, as_json: bool = False) -> AnalysisResult:
    """Top-level analyze orchestrator for CLI (I-030)."""
    from codegraph.extractor import load_graph0
    from codegraph.annotator import load_graph1
    from codegraph.workflow import load_workflow
    from codegraph.suggest import load_suggested_workflow

    graph0 = load_graph0(project_root)
    graph1 = load_graph1(project_root)
    workflow = load_workflow(project_root)
    suggested = load_suggested_workflow(project_root)

    index = None
    try:
        from codegraph.index import IndexStore
        index = IndexStore(project_root)
    except FileNotFoundError:
        pass

    result = analyze(
        project_root, graph0, graph1, workflow, suggested, index,
    )

    if index is not None:
        index.close()

    return result


# ═══════════════════════════════════════════════════════════════════════
# I-031 / I-032 — Graph_2 Semantic Integration (stubs for Group R)
# ═══════════════════════════════════════════════════════════════════════


def analyze_with_graph2(
    project_root: Path,
    graph0: Graph0,
    graph1: Graph1,
    workflow: Workflow,
    suggested_workflow: Optional[SuggestedWorkflow] = None,
    index: Any = None,
    graph2: Any = None,
) -> AnalysisResult:
    """Analyzer with optional Graph_2 semantic data (I-031).

    Falls back to structural analysis when Graph_2 is unavailable.
    Enriches results with semantic violations when Graph_2 is present.
    """
    # Base structural analysis
    result = analyze(project_root, graph0, graph1, workflow, suggested_workflow, index)

    if graph2 is None or not hasattr(graph2, "nodes") or not graph2.nodes:
        return result

    # Enrich with semantic rule violations
    try:
        from codegraph.semantics import evaluate_semantic_rules_impl
        violations = evaluate_semantic_rules_impl(graph2, graph0, workflow)
        if violations:
            logger.info("Semantic analysis found %d violations", len(violations))
            # Attach semantic findings to result metadata
            if not hasattr(result, "metadata"):
                result.metadata = {}
            result.metadata["semantic_violations"] = violations
            result.metadata["semantic_node_count"] = len(graph2.nodes)
            summary = graph2.get_behavior_summary()
            result.metadata["behavior_summary"] = summary
    except Exception as exc:
        logger.warning("Semantic analysis failed: %s", exc)

    return result
