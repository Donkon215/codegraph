"""Tests for codegraph.architecture_execution — issue #69 coverage map.

Covers: deterministic boundary coverage, explicit zero-coverage boundaries,
orphan tests, ambiguous (multi-boundary) tests, boundary-crossing flows
recorded in traversal order with one-sided vs untested distinguished,
missing-vs-zero evidence, and that the map is advisory (no pass/fail gates).
"""

from __future__ import annotations

from types import SimpleNamespace

from codegraph.architecture_execution import (
    ExecutionCoverageMap,
    load_execution_coverage,
    map_execution_coverage,
    save_execution_coverage,
)
from codegraph.architecture_graph import ArchitectureGraph
from codegraph.architecture_metrics import REACH_DEPTH
from codegraph.graph_partitioning import GraphPartitions, Partition
from codegraph.graph_partitioning import GraphPartitions, Partition


def _index(test_nodes):
    """Index store stub exposing only graph-derived test nodes (layer 4)."""

    def get_nodes_at_layer(layer):
        return list(test_nodes) if layer == 4 else []

    return SimpleNamespace(get_nodes_at_layer=get_nodes_at_layer)


def _graph() -> ArchitectureGraph:
    """Small repo: two production communities plus tests, one orphan test."""

    return ArchitectureGraph(
        nodes=[
            {"id": "payments.py::PaymentService", "file": "payments.py", "type": "function", "line": 1},
            {"id": "payments.py::PaymentRepo", "file": "payments.py", "type": "function", "line": 1},
            {"id": "orders.py::OrderService", "file": "orders.py", "type": "function", "line": 1},
            {"id": "orders.py::OrderRepo", "file": "orders.py", "type": "function", "line": 1},
            {"id": "tests/test_payments.py::test_pay", "file": "tests/test_payments.py", "type": "function", "line": 1},
            {"id": "tests/test_orders.py::test_order", "file": "tests/test_orders.py", "type": "function", "line": 1},
            {"id": "tests/test_orphan.py::test_orphan", "file": "tests/test_orphan.py", "type": "function", "line": 1},
        ],
        edges=[
            # test_pay exercises the payments boundary.
            {"source": "tests/test_payments.py::test_pay", "target": "payments.py::PaymentService", "edge_type": "call"},
            # test_order exercises the orders boundary.
            {"source": "tests/test_orders.py::test_order", "target": "orders.py::OrderService", "edge_type": "call"},
            # Boundary-crossing execution flows (both directions).
            {"source": "payments.py::PaymentService", "target": "orders.py::OrderService", "edge_type": "call"},
            {"source": "orders.py::OrderRepo", "target": "payments.py::PaymentRepo", "edge_type": "call"},
            # Internal edges keep the two production communities cohesive.
            {"source": "payments.py::PaymentService", "target": "payments.py::PaymentRepo", "edge_type": "call"},
            {"source": "payments.py::PaymentRepo", "target": "payments.py::PaymentService", "edge_type": "call"},
            {"source": "orders.py::OrderService", "target": "orders.py::OrderRepo", "edge_type": "call"},
            {"source": "orders.py::OrderRepo", "target": "orders.py::OrderService", "edge_type": "call"},
            # test_orphan reaches no production boundary -> orphan test.
        ],
    )


def _partitions() -> GraphPartitions:
    """Hand-built boundaries so the expected map is fully controlled."""
    payments = Partition(
        id="boundary_payments",
        nodes={"payments.py::PaymentService", "payments.py::PaymentRepo"},
    )
    orders = Partition(
        id="boundary_orders",
        nodes={"orders.py::OrderService", "orders.py::OrderRepo"},
    )
    test_part = Partition(
        id="boundary_tests",
        nodes={
            "tests/test_payments.py::test_pay",
            "tests/test_orders.py::test_order",
            "tests/test_orphan.py::test_orphan",
        },
    )
    partitions = GraphPartitions()
    for part in (payments, orders, test_part):
        partitions.partitions[part.id] = part
        for node_id in part.nodes:
            partitions.node_to_partition[node_id] = part.id
    partitions.metadata = {
        "method": "manual",
        "partition_count": 3,
        "node_count": 7,
        "edge_count": 8,
        "min_size": 4,
    }
    return partitions


def test_exact_coverage_map_matches_fixture() -> None:
    """Acceptance criterion: exact expected map for a small repository."""
    graph = _graph()
    index = _index(
        {
            "tests/test_payments.py::test_pay",
            "tests/test_orders.py::test_order",
            "tests/test_orphan.py::test_orphan",
        }
    )
    result = map_execution_coverage(graph, index, partitions=_partitions())

    assert result.evidence == "present"

    # Every boundary is listed explicitly, including zero-coverage ones.
    by_id = {b.boundary_id: b for b in result.boundaries}
    assert set(by_id) == {"boundary_orders", "boundary_payments", "boundary_tests"}

    assert by_id["boundary_payments"].covering_tests == [
        "tests/test_orders.py::test_order",
        "tests/test_payments.py::test_pay",
    ]
    assert by_id["boundary_payments"].coverage_status == "covered"
    assert by_id["boundary_orders"].covering_tests == [
        "tests/test_orders.py::test_order",
        "tests/test_payments.py::test_pay",
    ]
    assert by_id["boundary_orders"].coverage_status == "covered"
    # Zero coverage is listed explicitly, not omitted.
    assert by_id["boundary_tests"].covering_tests == []
    assert by_id["boundary_tests"].coverage_status == "zero_coverage"

    # Boundary-crossing flows, in traversal order, with per-side tests.
    flows = {f.flow_id: f for f in result.flows}
    assert flows["payments.py::PaymentService->orders.py::OrderService"].boundary_path == [
        "boundary_payments",
        "boundary_orders",
    ]
    # test_pay calls PaymentService directly (1 hop), so it covers the flow.
    # test_order only reaches PaymentService through a 4-hop cycle, which is
    # past the reach bound -- inference, not evidence.
    assert flows["payments.py::PaymentService->orders.py::OrderService"].coverage_status == "covered"
    assert flows["payments.py::PaymentService->orders.py::OrderService"].tests_covering_flow == [
        "tests/test_payments.py::test_pay",
    ]
    assert flows["orders.py::OrderRepo->payments.py::PaymentRepo"].coverage_status == "covered"
    # Tests on only one side of the boundary crossing -> one_sided (reported
    # separately from a flow with no tests at all).
    assert flows["tests/test_payments.py::test_pay->payments.py::PaymentService"].coverage_status == "one_sided"
    assert flows["tests/test_orders.py::test_order->orders.py::OrderService"].coverage_status == "one_sided"

    # Orphan test reported explicitly, not silently discarded.
    assert result.orphan_tests == ["tests/test_orphan.py::test_orphan"]
    # Both tests reach two boundaries, so both ambiguities are recorded.
    assert result.ambiguous_tests == [
        "tests/test_orders.py::test_order",
        "tests/test_payments.py::test_pay",
    ]

    # Totals are advisory only (no pass/fail fields).
    assert result.totals["boundary_count"] == 3
    assert result.totals["test_count"] == 3
    assert result.totals["covered_boundary_count"] == 2
    assert result.totals["zero_coverage_boundary_count"] == 1
    assert result.totals["flow_count"] == 4
    assert result.totals["covered_flow_count"] == 2
    assert result.totals["one_sided_flow_count"] == 2
    assert result.totals["untested_flow_count"] == 0
    assert result.totals["orphan_test_count"] == 1
    assert result.totals["ambiguous_test_count"] == 2

    # Full round-trip serializable map.
    data = result.to_dict()
    assert data["evidence"] == "present"
    assert set(data) == {
        "evidence", "reach_depth", "boundaries", "flows", "orphan_tests",
        "ambiguous_tests", "totals",
    }
    # The hop bound is recorded so a reader knows how far "covered" inferred.
    assert data["reach_depth"] == REACH_DEPTH
    # Direct coverage is distinguishable from inferred coverage.
    reaches = {b["boundary_id"]: b["nearest_reach"] for b in data["boundaries"]}
    assert reaches["boundary_payments"] == 1
    assert reaches["boundary_tests"] is None


def test_coverage_map_is_deterministic() -> None:
    """Same graph and tests produce the same map on every run."""
    graph = _graph()
    index = _index(
        {
            "tests/test_payments.py::test_pay",
            "tests/test_orders.py::test_order",
            "tests/test_orphan.py::test_orphan",
        }
    )
    first = map_execution_coverage(graph, index, partitions=_partitions()).to_dict()
    second = map_execution_coverage(graph, index, partitions=_partitions()).to_dict()
    assert first == second


def test_coverage_map_roundtrips_through_disk(tmp_path) -> None:
    """Two builds must be comparable as files, not just as console output."""
    graph = _graph()
    index = _index(
        {
            "tests/test_payments.py::test_pay",
            "tests/test_orders.py::test_order",
            "tests/test_orphan.py::test_orphan",
        }
    )
    result = map_execution_coverage(graph, index, partitions=_partitions())
    path = save_execution_coverage(tmp_path, result)
    assert path.exists()

    loaded = load_execution_coverage(tmp_path)
    assert loaded is not None
    assert loaded.to_dict() == result.to_dict()
    assert loaded.reach_depth == REACH_DEPTH
    # Nearest-reach survives the round trip, so direct vs inferred stays visible.
    reaches = {b.boundary_id: b.nearest_reach for b in loaded.boundaries}
    assert reaches["boundary_payments"] == 1


def test_load_execution_coverage_returns_none_when_absent(tmp_path) -> None:
    assert load_execution_coverage(tmp_path) is None


def test_missing_evidence_distinguished_from_zero_coverage() -> None:
    """No test nodes = missing evidence; tests exist but reach none = zero coverage."""
    graph = _graph()

    # Missing evidence: no test nodes at all.
    no_tests = map_execution_coverage(graph, _index(set()), partitions=_partitions())
    assert no_tests.evidence == "missing"
    assert all(b.coverage_status == "missing_evidence" for b in no_tests.boundaries)
    assert all(f.coverage_status == "missing_evidence" for f in no_tests.flows)
    assert no_tests.orphan_tests == []
    assert no_tests.ambiguous_tests == []
    assert no_tests.totals["test_count"] == 0

    # Zero coverage: test nodes exist but none reach any production boundary.
    unconnected = _index({"tests/test_orphan.py::test_orphan"})
    zero = map_execution_coverage(graph, unconnected, partitions=_partitions())
    assert zero.evidence == "present"
    assert all(b.coverage_status == "zero_coverage" for b in zero.boundaries)
    assert zero.orphan_tests == ["tests/test_orphan.py::test_orphan"]
    assert zero.totals["zero_coverage_boundary_count"] == zero.totals["boundary_count"]


def test_ambiguous_multi_boundary_test_is_recorded() -> None:
    """A test attributable to more than one boundary is recorded, not resolved silently."""
    graph = _graph()
    index = _index({"tests/test_payments.py::test_pay"})
    # test_pay calls into both production communities.
    graph = ArchitectureGraph(
        nodes=graph.nodes,
        edges=[
            {"source": "tests/test_payments.py::test_pay", "target": "payments.py::PaymentService", "edge_type": "call"},
            {"source": "tests/test_payments.py::test_pay", "target": "orders.py::OrderService", "edge_type": "call"},
        ],
    )
    result = map_execution_coverage(graph, index, partitions=_partitions())
    assert result.ambiguous_tests == ["tests/test_payments.py::test_pay"]
    by_id = {b.boundary_id: b for b in result.boundaries}
    assert by_id["boundary_payments"].covering_tests == ["tests/test_payments.py::test_pay"]
    assert by_id["boundary_orders"].covering_tests == ["tests/test_payments.py::test_pay"]


def test_unrelated_tests_on_both_boundaries_do_not_cover_crossing() -> None:
    """Boundary coverage on both sides does not prove a test reaches the crossing."""
    source = "payments.py::Gateway"
    source_helper = "payments.py::Helper"
    target = "orders.py::Store"
    test_source = "tests/test_source.py::test_source"
    test_target = "tests/test_target.py::test_target"
    graph = ArchitectureGraph(
        nodes=[{"id": nid, "file": nid.split("::")[0], "type": "function", "line": 1}
               for nid in (source, source_helper, target, test_source, test_target)],
        edges=[
            {"source": test_source, "target": source_helper, "edge_type": "call"},
            {"source": test_target, "target": target, "edge_type": "call"},
            {"source": source, "target": target, "edge_type": "call"},
        ],
    )
    partitions = _parts(
        payments=[source, source_helper],
        orders=[target],
        tests=[test_source, test_target],
    )
    result = map_execution_coverage(
        graph, _index({test_source, test_target}), partitions=partitions
    )

    flow = next(f for f in result.flows if f.flow_id == f"{source}->{target}")
    by_boundary = {b.boundary_id: b for b in result.boundaries}
    assert by_boundary["payments"].covering_tests == [test_source]
    assert by_boundary["orders"].covering_tests == [test_target]
    assert flow.tests_covering_source == []
    assert flow.tests_covering_target == [test_target]
    assert flow.tests_covering_flow == []
    assert flow.coverage_status == "one_sided"


def test_empty_graph_produces_empty_map() -> None:
    graph = ArchitectureGraph(nodes=[], edges=[], metadata={})
    index = _index(set())
    result = map_execution_coverage(graph, index)
    assert result.evidence == "missing"
    assert result.boundaries == []
    assert result.flows == []
    assert result.orphan_tests == []
    assert result.ambiguous_tests == []
    assert isinstance(result, ExecutionCoverageMap)


def _parts(**boundaries: dict[str, list[str]]) -> GraphPartitions:
    """Build hand-controlled partitions from {boundary_id: [node_ids]}."""
    partitions = GraphPartitions()
    for boundary_id, node_ids in boundaries.items():
        partition = Partition(id=boundary_id, nodes=set(node_ids))
        partitions.partitions[boundary_id] = partition
        for node_id in node_ids:
            partitions.node_to_partition[node_id] = boundary_id
    partitions.metadata = {
        "method": "manual",
        "partition_count": len(boundaries),
        "node_count": sum(len(v) for v in boundaries.values()),
        "edge_count": 0,
        "min_size": 4,
    }
    return partitions


def test_transitive_reach_through_unmapped_helper() -> None:
    """A test that calls a helper which calls into a boundary covers that
    boundary transitively; edges, not direct adjacency, determine attribution."""
    graph = ArchitectureGraph(
        nodes=[
            {"id": "payments.py::PaymentService", "file": "payments.py", "type": "function", "line": 1},
            {"id": "helpers.py::Helper", "file": "helpers.py", "type": "function", "line": 1},
            {"id": "orders.py::OrderService", "file": "orders.py", "type": "function", "line": 1},
            {"id": "orders.py::OrderRepo", "file": "orders.py", "type": "function", "line": 1},
            {"id": "legacy.py::Legacy", "file": "legacy.py", "type": "function", "line": 1},
            {"id": "tests/t.py::test_helper", "file": "tests/t.py", "type": "function", "line": 1},
            {"id": "tests/t.py::test_orphan", "file": "tests/t.py", "type": "function", "line": 1},
        ],
        edges=[
            # test_helper -> Helper (no boundary) -> PaymentService (boundary_payments)
            {"source": "tests/t.py::test_helper", "target": "helpers.py::Helper", "edge_type": "call"},
            {"source": "helpers.py::Helper", "target": "payments.py::PaymentService", "edge_type": "call"},
            # untested boundary-crossing flow: orders -> legacy
            {"source": "orders.py::OrderService", "target": "legacy.py::Legacy", "edge_type": "call"},
            {"source": "orders.py::OrderService", "target": "orders.py::OrderRepo", "edge_type": "call"},
        ],
    )
    index = _index({"tests/t.py::test_helper", "tests/t.py::test_orphan"})
    partitions = _parts(
        boundary_payments=["payments.py::PaymentService"],
        boundary_orders=["orders.py::OrderService", "orders.py::OrderRepo"],
        boundary_legacy=["legacy.py::Legacy"],
        boundary_tests=[],
    )
    result = map_execution_coverage(graph, index, partitions=partitions)

    assert result.evidence == "present"
    by_id = {b.boundary_id: b for b in result.boundaries}
    # test_helper reaches payments.py::PaymentService *transitively* via Helper.
    assert by_id["boundary_payments"].covering_tests == ["tests/t.py::test_helper"]
    assert by_id["boundary_payments"].coverage_status == "covered"
    # No test reaches orders or legacy -> zero coverage listed explicitly.
    assert by_id["boundary_orders"].covering_tests == []
    assert by_id["boundary_orders"].coverage_status == "zero_coverage"
    assert by_id["boundary_legacy"].covering_tests == []
    assert by_id["boundary_legacy"].coverage_status == "zero_coverage"

    # Orphan test reported explicitly.
    assert result.orphan_tests == ["tests/t.py::test_orphan"]
    # No ambiguity here: test_helper reaches exactly one boundary.
    assert result.ambiguous_tests == []

    # The untested orders->legacy crossing flow is reported as untested.
    flows = {f.flow_id: f for f in result.flows}
    legacy_flow = flows["orders.py::OrderService->legacy.py::Legacy"]
    assert legacy_flow.boundary_path == ["boundary_orders", "boundary_legacy"]
    assert legacy_flow.coverage_status == "untested"
    assert legacy_flow.tests_covering_source == []
    assert legacy_flow.tests_covering_target == []


def test_layer_and_edges_not_file_names_determine_attribution() -> None:
    """File names are misleading: a layer-4 node in ``not_a_test.py`` is treated
    as a test, while a layer-3 node in ``tests/test_real.py`` is not. Attribution
    comes from graph layer and edges alone; naming and intent are unused."""
    graph = ArchitectureGraph(
        nodes=[
            {"id": "payments.py::PaymentService", "file": "payments.py", "type": "function", "line": 1},
            {"id": "orders.py::OrderService", "file": "orders.py", "type": "function", "line": 1},
            # Misleading name: looks like a non-test, but is layer 4 -> a test.
            {"id": "src/not_a_test.py::verify", "file": "src/not_a_test.py", "type": "function", "line": 1},
            # Misleading name: looks like a test, but is layer 3 -> not a test.
            {"id": "tests/test_real.py::setup", "file": "tests/test_real.py", "type": "function", "line": 1},
        ],
        edges=[
            {"source": "src/not_a_test.py::verify", "target": "payments.py::PaymentService", "edge_type": "call"},
            {"source": "tests/test_real.py::setup", "target": "orders.py::OrderService", "edge_type": "call"},
        ],
    )
    # Layer 4 determines test-ness: only ``verify`` is a test, despite the names.
    index = _index({"src/not_a_test.py::verify"})
    partitions = _parts(
        boundary_payments=["payments.py::PaymentService"],
        boundary_orders=["orders.py::OrderService"],
    )
    result = map_execution_coverage(graph, index, partitions=partitions)

    assert result.evidence == "present"
    by_id = {b.boundary_id: b for b in result.boundaries}
    # The misleadingly-named non-test file IS the test: it covers payments.
    assert by_id["boundary_payments"].covering_tests == ["src/not_a_test.py::verify"]
    assert by_id["boundary_payments"].coverage_status == "covered"
    # The misleadingly-named test file is layer 3, so NOT a test: orders zero.
    assert by_id["boundary_orders"].covering_tests == []
    assert by_id["boundary_orders"].coverage_status == "zero_coverage"

    # verify reaches a boundary -> not orphan. setup is not a test node at all.
    assert result.orphan_tests == []
    assert result.ambiguous_tests == []
    assert result.totals["test_count"] == 1
    assert result.totals["zero_coverage_boundary_count"] == 1

    # Deterministic under repeat runs.
    assert result.to_dict() == map_execution_coverage(graph, index, partitions=partitions).to_dict()
