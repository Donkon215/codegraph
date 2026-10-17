"""codegraph.architecture_execution — Map execution flows and test coverage to architecture boundaries.

Implements GitHub issue #69: a coverage map over the architecture boundary model
(partitions / detected communities). It joins execution-flow evidence (workflow
graph edges) with test-coverage evidence (graph layer-4 test nodes) so each
boundary records which tests exercise it, each execution flow records the
boundaries it traverses (in order), and untested / one-sided boundary-crossing
flows are reported explicitly.

The map is advisory: coverage gaps never block a build, an apply, or a
simulation verdict. This module registers no CLI commands and changes no shared
CLI files.

Design constraints honoured from issue #69:
* Attribution is derived from the graph only. Test-ness comes from the graph's
  layer-4 assignment -- never inferred from a ``test_`` file name.
* Line/branch coverage and coverage reports are out of scope; no coverage data
  is ever parsed.
* Human-authored intent is never used as coverage evidence.
* A test attributable to more than one boundary has that ambiguity recorded,
  not resolved silently.
* Missing evidence (no test nodes) is distinguished from zero coverage
  (tests exist but reach no boundary).

Written definition: ``docs/architecture-metrics.md``.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from codegraph.architecture_graph import ArchitectureGraph
from codegraph.graph_partitioning import GraphPartitions, build_partitions
from codegraph.index import IndexStore

# Graph layer reserved for test code (codegraph.layers.LAYER_TEST == 4).
_TEST_LAYER = 4


@dataclass
class BoundaryCoverage:
    """Coverage of a single architecture boundary (partition/community)."""

    boundary_id: str
    node_ids: List[str] = field(default_factory=list)
    covering_tests: List[str] = field(default_factory=list)
    coverage_status: str = "zero_coverage"  # covered | zero_coverage | missing_evidence

    def to_dict(self) -> Dict[str, Any]:
        return {
            "boundary_id": self.boundary_id,
            "node_count": len(self.node_ids),
            "node_ids": list(self.node_ids),
            "covering_tests": list(self.covering_tests),
            "test_count": len(self.covering_tests),
            "coverage_status": self.coverage_status,
        }


@dataclass
class FlowCoverage:
    """A boundary-crossing execution flow (one workflow edge between boundaries)."""

    flow_id: str
    source_node: str
    target_node: str
    boundary_path: List[str] = field(default_factory=list)  # [source, target] in order
    tests_covering_source: List[str] = field(default_factory=list)
    tests_covering_target: List[str] = field(default_factory=list)
    tests_covering_flow: List[str] = field(default_factory=list)
    coverage_status: str = "untested"  # covered | one_sided | untested | missing_evidence

    def to_dict(self) -> Dict[str, Any]:
        return {
            "flow_id": self.flow_id,
            "source_node": self.source_node,
            "target_node": self.target_node,
            "boundary_path": list(self.boundary_path),
            "tests_covering_source": list(self.tests_covering_source),
            "tests_covering_target": list(self.tests_covering_target),
            "tests_covering_flow": list(self.tests_covering_flow),
            "coverage_status": self.coverage_status,
        }


@dataclass
class ExecutionCoverageMap:
    """Deterministic coverage map over architecture boundaries (issue #69)."""

    evidence: str = "missing"  # present | missing
    boundaries: List[BoundaryCoverage] = field(default_factory=list)
    flows: List[FlowCoverage] = field(default_factory=list)
    orphan_tests: List[str] = field(default_factory=list)
    ambiguous_tests: List[str] = field(default_factory=list)
    totals: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evidence": self.evidence,
            "boundaries": [b.to_dict() for b in self.boundaries],
            "flows": [f.to_dict() for f in self.flows],
            "orphan_tests": list(self.orphan_tests),
            "ambiguous_tests": list(self.ambiguous_tests),
            "totals": dict(self.totals),
        }


def _reachable_boundaries(
    test: str,
    graph: ArchitectureGraph,
    node_to_boundary: Dict[str, str],
) -> Set[str]:
    """Return the architecture boundaries reachable from *test* through graph edges.

    Traversal follows forward (callee) edges from *test*'s direct callees onward,
    with cycle protection (a ``visited`` set) so circular call graphs terminate.
    Neighbours are visited in sorted order so the result is deterministic for the
    same graph. The test's own boundary is not counted unless re-reached through
    a cycle; coverage is about calling *into* a boundary, not residing in one.

    Attribution is derived from graph edges and layer-4 test-ness only: file
    names and human-authored intent are never consulted.
    """
    reachable = _reachable_nodes(test, graph)
    return {node_to_boundary[node] for node in reachable if node in node_to_boundary}


def _reachable_nodes(test: str, graph: ArchitectureGraph) -> Set[str]:
    """Return nodes reachable from a test through directed graph edges."""
    visited: Set[str] = {test}
    queue: deque[str] = deque(sorted(graph.adj_out.get(test, set())))
    while queue:
        node = queue.popleft()
        if node in visited:
            continue
        visited.add(node)
        for nxt in sorted(graph.adj_out.get(node, set())):
            if nxt not in visited:
                queue.append(nxt)
    return visited - {test}


def map_execution_coverage(
    graph: ArchitectureGraph,
    index: IndexStore,
    *,
    partitions: Optional[GraphPartitions] = None,
) -> ExecutionCoverageMap:
    """Map execution-flow and test-coverage evidence to architecture boundaries.

    Parameters
    ----------
    graph:
        Architecture graph whose workflow edges are the execution-flow evidence
        and whose nodes carry graph-assigned layers.
    index:
        Index store used only to identify test nodes (graph layer 4). Test-ness
        is never inferred from file names.
    partitions:
        Pre-computed architecture boundaries. When omitted they are built from
        *graph* with :func:`codegraph.graph_partitioning.build_partitions`.

    Returns an advisory :class:`ExecutionCoverageMap`. Coverage gaps never
    block a build, an apply, or a simulation verdict.
    """
    if partitions is None:
        partitions = build_partitions(graph)

    node_to_boundary: Dict[str, str] = dict(partitions.node_to_partition)

    graph_node_ids: Set[str] = {
        str(node.get("id", "")).strip()
        for node in graph.nodes
        if str(node.get("id", "")).strip()
    }

    # Test-coverage evidence: graph layer-4 test nodes, restricted to the graph.
    # Derived from the graph/index -- never from a ``test_`` file name.
    test_nodes: Set[str] = set()
    try:
        indexed_tests = index.get_nodes_at_layer(_TEST_LAYER)
    except (AttributeError, TypeError):
        indexed_tests = []
    for node_id in indexed_tests:
        if node_id in graph_node_ids:
            test_nodes.add(node_id)

    evidence = "present" if test_nodes else "missing"

    # Test -> boundaries: a test covers every boundary it can reach through the
    # graph (direct call or transitive via helpers), with edges determining
    # attribution -- never file names or intent. Deterministic BFS with cycle
    # protection (see _reachable_boundaries).
    boundary_tests: Dict[str, Set[str]] = {pid: set() for pid in partitions.partitions}
    reachable_by_test: Dict[str, Set[str]] = {}
    for test in sorted(test_nodes):
        reachable_by_test[test] = _reachable_nodes(test, graph)
        for boundary in _reachable_boundaries(test, graph, node_to_boundary):
            boundary_tests.setdefault(boundary, set()).add(test)

    # Per-boundary coverage: every boundary listed explicitly, zero coverage kept.
    boundaries: List[BoundaryCoverage] = []
    for pid in sorted(partitions.partitions):
        partition = partitions.partitions[pid]
        tests = sorted(boundary_tests.get(pid, set()))
        node_ids = sorted(partition.nodes)
        if evidence == "missing":
            status = "missing_evidence"
        elif tests:
            status = "covered"
        else:
            status = "zero_coverage"
        boundaries.append(
            BoundaryCoverage(
                boundary_id=pid,
                node_ids=node_ids,
                covering_tests=tests,
                coverage_status=status,
            )
        )

    # Ambiguity: a test attributable to more than one boundary is recorded, not
    # resolved silently.
    test_to_boundaries: Dict[str, Set[str]] = {}
    for pid, tests in boundary_tests.items():
        for test in tests:
            test_to_boundaries.setdefault(test, set()).add(pid)
    ambiguous_tests = sorted(
        test for test, bds in test_to_boundaries.items() if len(bds) > 1
    )

    # Orphan tests: graph test nodes that reach no boundary.
    if evidence == "missing":
        orphan_tests: List[str] = []
    else:
        covered_tests = set(test_to_boundaries.keys())
        orphan_tests = sorted(t for t in test_nodes if t not in covered_tests)

    # Boundary-crossing execution flows, in traversal order, with per-side tests.
    flows: List[FlowCoverage] = []
    seen_flows: Set[str] = set()
    for source in sorted(graph.adj_out):
        src_boundary = node_to_boundary.get(source)
        for target in sorted(graph.adj_out[source]):
            tgt_boundary = node_to_boundary.get(target)
            if not src_boundary or not tgt_boundary or src_boundary == tgt_boundary:
                continue
            flow_id = f"{source}->{target}"
            if flow_id in seen_flows:
                continue
            seen_flows.add(flow_id)
            # A test covers this flow only if it reaches this exact edge's
            # source node. The edge then takes it across the boundary. Merely
            # having unrelated tests somewhere on both boundary sides is not
            # evidence that the crossing is exercised.
            tests_source = sorted(
                test for test, reachable in reachable_by_test.items() if source in reachable
            )
            tests_target = sorted(
                test for test, reachable in reachable_by_test.items() if target in reachable
            )
            tests_flow = list(tests_source)
            if evidence == "missing":
                status = "missing_evidence"
            elif tests_flow:
                status = "covered"
            elif tests_source or tests_target:
                status = "one_sided"
            else:
                status = "untested"
            flows.append(
                FlowCoverage(
                    flow_id=flow_id,
                    source_node=source,
                    target_node=target,
                    boundary_path=[src_boundary, tgt_boundary],
                    tests_covering_source=tests_source,
                    tests_covering_target=tests_target,
                    tests_covering_flow=tests_flow,
                    coverage_status=status,
                )
            )

    # Totals are advisory metrics only; never a pass/fail gate.
    covered_boundaries = sum(1 for b in boundaries if b.coverage_status == "covered")
    zero_boundaries = sum(1 for b in boundaries if b.coverage_status == "zero_coverage")
    covered_flows = sum(1 for f in flows if f.coverage_status == "covered")
    one_sided_flows = sum(1 for f in flows if f.coverage_status == "one_sided")
    untested_flows = sum(1 for f in flows if f.coverage_status == "untested")

    totals = {
        "boundary_count": len(boundaries),
        "test_count": len(test_nodes),
        "covered_boundary_count": covered_boundaries,
        "zero_coverage_boundary_count": zero_boundaries,
        "flow_count": len(flows),
        "covered_flow_count": covered_flows,
        "one_sided_flow_count": one_sided_flows,
        "untested_flow_count": untested_flows,
        "orphan_test_count": len(orphan_tests),
        "ambiguous_test_count": len(ambiguous_tests),
    }

    return ExecutionCoverageMap(
        evidence=evidence,
        boundaries=boundaries,
        flows=flows,
        orphan_tests=orphan_tests,
        ambiguous_tests=ambiguous_tests,
        totals=totals,
    )
