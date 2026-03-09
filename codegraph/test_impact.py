"""codegraph.test_impact — Test impact analysis.

Group M: M-007 through M-013, M-016, M-018, M-020, M-021.
"""

from __future__ import annotations

import json
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from codegraph.index import IndexStore
from codegraph.logging_config import get_logger
from codegraph.models.graph0 import Graph0
from codegraph.models.graph1 import Graph1
from codegraph.models.workflow import Workflow

logger = get_logger("test_impact")


# ═══════════════════════════════════════════════════════════════════════
# Data Structures
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class AffectedTest:
    """A test affected by code changes (M-009)."""

    test_id: str
    change_types: List[str] = field(default_factory=list)  # direct, transitive, etc.
    distance: int = 0  # shortest hop count from changed node
    impact_score: int = 0  # number of changed nodes that affect this test
    triggering_nodes: List[str] = field(default_factory=list)


@dataclass
class CoverageGap:
    """A production function with no test coverage (M-011)."""

    node_id: str
    file: str = ""
    gap_type: str = "no_test"  # no_test | no_trace | indirect_only


@dataclass
class TestImpactResult:
    """Aggregated test impact analysis result (M-009)."""

    affected_tests: List[AffectedTest] = field(default_factory=list)
    changed_nodes: List[str] = field(default_factory=list)
    coverage_gaps: List[CoverageGap] = field(default_factory=list)
    total_tests_affected: int = 0
    elapsed_ms: float = 0.0

    @property
    def direct_tests(self) -> List[AffectedTest]:
        return [t for t in self.affected_tests if "direct" in t.change_types]

    @property
    def transitive_tests(self) -> List[AffectedTest]:
        return [t for t in self.affected_tests if "transitive" in t.change_types
                and "direct" not in t.change_types]


@dataclass
class ImpactDiff:
    """Diff between two test impact results (M-020)."""

    new_affected: List[str] = field(default_factory=list)
    no_longer_affected: List[str] = field(default_factory=list)
    changed_type: List[Tuple[str, str, str]] = field(default_factory=list)  # (test, old_type, new_type)


# ═══════════════════════════════════════════════════════════════════════
# M-008 — Backward Call Graph Tracing
# M-018 — Performance Optimization
# ═══════════════════════════════════════════════════════════════════════

_DEFAULT_MAX_DEPTH = 50


def trace_backward(
    start_nodes: Set[str],
    index: IndexStore,
    *,
    stop_layer: int = 4,
    max_depth: int = _DEFAULT_MAX_DEPTH,
) -> Dict[str, List[Tuple[str, int]]]:
    """BFS backward through callers to find test nodes (M-008, M-018).

    Returns: {start_node: [(test_id, distance), ...]}
    """
    test_nodes = set(index.get_nodes_at_layer(stop_layer))
    result: Dict[str, List[Tuple[str, int]]] = {}

    for start in start_nodes:
        found_tests: List[Tuple[str, int]] = []
        visited: Set[str] = set()
        queue: deque[Tuple[str, int]] = deque([(start, 0)])

        while queue:
            current, depth = queue.popleft()
            if current in visited:
                continue
            visited.add(current)

            if depth > 0 and current in test_nodes:
                found_tests.append((current, depth))
                continue  # Don't trace beyond test nodes

            if depth >= max_depth:
                continue

            # M-018 — Batch callers lookup
            for caller in index.get_callers(current):
                if caller not in visited:
                    queue.append((caller, depth + 1))

        result[start] = found_tests

    return result


# ═══════════════════════════════════════════════════════════════════════
# M-007 — Test Impact Analysis Core
# ═══════════════════════════════════════════════════════════════════════


def analyze_test_impact(
    changed_nodes: Set[str],
    index: IndexStore,
    *,
    max_depth: int = _DEFAULT_MAX_DEPTH,
) -> TestImpactResult:
    """Determine which tests are affected by code changes (M-007)."""
    t0 = time.perf_counter()

    result = TestImpactResult(changed_nodes=sorted(changed_nodes))

    # Trace backward from all changed nodes
    traces = trace_backward(changed_nodes, index, max_depth=max_depth)

    # M-009 — Aggregate results
    test_map: Dict[str, AffectedTest] = {}

    for start_node, tests_found in traces.items():
        for test_id, distance in tests_found:
            if test_id not in test_map:
                test_map[test_id] = AffectedTest(test_id=test_id, distance=distance)
            at = test_map[test_id]
            at.impact_score += 1
            at.triggering_nodes.append(start_node)
            at.distance = min(at.distance, distance)

            # M-010 — Classify change type
            if distance == 1:
                if "direct" not in at.change_types:
                    at.change_types.append("direct")
            else:
                if "transitive" not in at.change_types:
                    at.change_types.append("transitive")

    # M-016 — Prioritize: direct > transitive, higher score first
    result.affected_tests = sorted(
        test_map.values(),
        key=lambda t: (
            0 if "direct" in t.change_types else 1,
            -t.impact_score,
            t.distance,
        ),
    )
    result.total_tests_affected = len(result.affected_tests)
    result.elapsed_ms = (time.perf_counter() - t0) * 1000

    return result


# ═══════════════════════════════════════════════════════════════════════
# M-010 — test_change_type Classification
# ═══════════════════════════════════════════════════════════════════════


def classify_test_change(
    test_id: str,
    changed_nodes: Set[str],
    index: IndexStore,
    workflow: Optional[Workflow] = None,
) -> List[str]:
    """Classify how a test relates to code changes (M-010)."""
    types: List[str] = []

    # Direct: test calls a changed function
    callees = set(index.get_callees(test_id))
    if callees & changed_nodes:
        types.append("direct")

    # Import: test's file imports a changed module
    test_node = index.get_node(test_id)
    if test_node:
        test_file = test_node.get("file", "")
        for changed in changed_nodes:
            changed_node = index.get_node(changed)
            if changed_node and changed_node.get("file", "").rstrip(".py") in test_file:
                if "import" not in types:
                    types.append("import")

    # Structural: test in same file as changed code
    if test_node:
        test_file = test_node.get("file", "")
        for changed in changed_nodes:
            cn = index.get_node(changed)
            if cn and cn.get("file", "") == test_file:
                if "structural" not in types:
                    types.append("structural")

    # Transitive: anything else (already calculated in analyze)
    if not types:
        types.append("transitive")

    return types


# ═══════════════════════════════════════════════════════════════════════
# M-011 — Coverage Gap Detection
# ═══════════════════════════════════════════════════════════════════════


def find_coverage_gaps(
    graph0: Graph0,
    index: IndexStore,
) -> List[CoverageGap]:
    """Find production functions with no test coverage (M-011)."""
    gaps: List[CoverageGap] = []

    # Get all test nodes (layer 4)
    test_nodes = set(index.get_nodes_at_layer(4))

    for node in graph0.nodes:
        if node.type not in ("function", "method"):
            continue
        # Skip test functions
        if node.id in test_nodes:
            continue
        if node.file.startswith("test") or "/test" in node.file:
            continue

        # Check for any test association
        tests = index.get_tests_for_node(node.id)
        if not tests:
            # Check if any test transitively calls this node
            callers = index.get_callers(node.id)
            has_test_caller = any(c in test_nodes for c in callers)
            if has_test_caller:
                gaps.append(CoverageGap(
                    node_id=node.id, file=node.file, gap_type="indirect_only",
                ))
            else:
                gaps.append(CoverageGap(
                    node_id=node.id, file=node.file, gap_type="no_test",
                ))

    return gaps


# ═══════════════════════════════════════════════════════════════════════
# M-012 — Test Impact Command Output
# ═══════════════════════════════════════════════════════════════════════


def format_test_impact(
    result: TestImpactResult,
    *,
    as_json: bool = False,
    test_runner: str = "pytest",
) -> str:
    """Format test impact results for CLI display (M-012)."""
    if as_json:
        return json.dumps({
            "total_affected": result.total_tests_affected,
            "changed_nodes": result.changed_nodes,
            "elapsed_ms": round(result.elapsed_ms, 2),
            "affected_tests": [{
                "test_id": t.test_id,
                "change_types": t.change_types,
                "distance": t.distance,
                "impact_score": t.impact_score,
                "triggering_nodes": t.triggering_nodes,
            } for t in result.affected_tests],
            "coverage_gaps": [{
                "node_id": g.node_id,
                "file": g.file,
                "gap_type": g.gap_type,
            } for g in result.coverage_gaps],
        }, indent=2)

    lines: List[str] = []

    lines.append(
        f"Test Impact: {result.total_tests_affected} tests affected "
        f"by {len(result.changed_nodes)} changed nodes"
    )

    # Direct callers
    direct = result.direct_tests
    if direct:
        lines.append(f"\nDirect ({len(direct)}):")
        for t in direct[:20]:
            lines.append(f"  ● {t.test_id} (score={t.impact_score})")

    # Transitive
    transitive = result.transitive_tests
    if transitive:
        lines.append(f"\nTransitive ({len(transitive)}):")
        for t in transitive[:20]:
            lines.append(f"  ○ {t.test_id} (depth={t.distance})")

    # Coverage gaps
    if result.coverage_gaps:
        lines.append(f"\nCoverage gaps ({len(result.coverage_gaps)}):")
        for g in result.coverage_gaps[:10]:
            lines.append(f"  ⚠ {g.node_id} [{g.gap_type}]")

    # Test runner command
    if result.affected_tests:
        test_files = set()
        for t in result.affected_tests:
            # Extract file from test_id
            parts = t.test_id.split("::")
            if parts:
                test_files.add(parts[0])

        if test_files:
            lines.append(f"\nRun affected tests:")
            lines.append(f"  {test_runner} {' '.join(sorted(test_files))}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# M-013 — Test Impact Integration with Delta
# ═══════════════════════════════════════════════════════════════════════


def impact_from_delta(
    delta_result: Any,
    index: IndexStore,
) -> TestImpactResult:
    """Run test impact analysis from delta result (M-013)."""
    changed = set(
        delta_result.nodes_modified
        + delta_result.nodes_added
        + delta_result.nodes_removed
    )
    return analyze_test_impact(changed, index)


# ═══════════════════════════════════════════════════════════════════════
# M-016 — Test Prioritization
# ═══════════════════════════════════════════════════════════════════════


def prioritize_tests(
    affected: List[AffectedTest],
) -> List[AffectedTest]:
    """Prioritize affected tests by likelihood of failure (M-016)."""
    return sorted(
        affected,
        key=lambda t: (
            # Direct callers first
            0 if "direct" in t.change_types else 1,
            # Higher impact score = more changed nodes affect it
            -t.impact_score,
            # Shorter distance = closer to change
            t.distance,
            # Alphabetical for stability
            t.test_id,
        ),
    )


# ═══════════════════════════════════════════════════════════════════════
# M-020 — Test Impact Diff View
# ═══════════════════════════════════════════════════════════════════════


def diff_test_impact(
    old_impact: TestImpactResult,
    new_impact: TestImpactResult,
) -> ImpactDiff:
    """Compare two test impact results (M-020)."""
    old_tests = {t.test_id: t for t in old_impact.affected_tests}
    new_tests = {t.test_id: t for t in new_impact.affected_tests}

    diff = ImpactDiff()

    for tid in new_tests:
        if tid not in old_tests:
            diff.new_affected.append(tid)
        else:
            old_type = ",".join(sorted(old_tests[tid].change_types))
            new_type = ",".join(sorted(new_tests[tid].change_types))
            if old_type != new_type:
                diff.changed_type.append((tid, old_type, new_type))

    for tid in old_tests:
        if tid not in new_tests:
            diff.no_longer_affected.append(tid)

    return diff


# ═══════════════════════════════════════════════════════════════════════
# M-021 — CAS-Aware Test Impact Analysis
# ═══════════════════════════════════════════════════════════════════════


def test_impact_cas(
    affected_nodes: Set[str],
    graph0: Graph0,
    graph1: Graph1,
    index: IndexStore,
) -> TestImpactResult:
    """CAS-powered test impact: filter affected set to Layer 4 tests (M-021).

    Falls back to backward-trace when CAS is unavailable.
    """
    # Check if CAS data is available
    dep_hashes = index.get_all_dependency_hashes()
    if not dep_hashes:
        # CAS not available — fall back to backward trace
        logger.info("CAS unavailable — falling back to backward trace")
        return analyze_test_impact(affected_nodes, index)

    t0 = time.perf_counter()

    # Filter affected_nodes to Layer 4 (test) nodes
    test_layer_nodes = set(index.get_nodes_at_layer(4))
    affected_tests = affected_nodes & test_layer_nodes

    result = TestImpactResult(
        changed_nodes=sorted(affected_nodes - test_layer_nodes),
    )

    # Classify each affected test
    # Body-changed nodes are "direct"; dependency_hash-changed are "transitive"
    body_changed = set()
    for node in graph0.nodes:
        if node.id in affected_nodes:
            g1_node = graph1.get_node(node.id)
            if g1_node and g1_node.intent_body_hash and g1_node.intent_body_hash != node.body_hash:
                body_changed.add(node.id)

    for test_id in sorted(affected_tests):
        at = AffectedTest(test_id=test_id)

        # Check if test directly calls a body-changed node
        callees = set(index.get_callees(test_id))
        if callees & body_changed:
            at.change_types.append("direct")
            at.distance = 1
        else:
            at.change_types.append("transitive")
            at.distance = 2  # CAS can't give exact distance

        at.impact_score = len(callees & affected_nodes)
        at.triggering_nodes = sorted(callees & affected_nodes)[:5]

        result.affected_tests.append(at)

    result.total_tests_affected = len(result.affected_tests)
    result.elapsed_ms = (time.perf_counter() - t0) * 1000

    return result
