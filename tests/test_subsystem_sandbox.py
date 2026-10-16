from __future__ import annotations

from codegraph.subsystem_graph import SubsystemGraph
from codegraph.subsystem_sandbox import SubsystemSandbox, build_partition_sandbox


def _base_subsystem() -> SubsystemGraph:
    return SubsystemGraph(
        nodes=[
            {"id": "payment.py::PaymentController", "layer": 2, "type": "class"},
            {"id": "payment.py::PaymentService", "layer": 3, "type": "class"},
            {"id": "payment.py::PaymentRepository", "layer": 4, "type": "class"},
        ],
        edges=[
            {"source": "payment.py::PaymentController", "target": "payment.py::PaymentService", "edge_type": "call"},
            {"source": "payment.py::PaymentService", "target": "payment.py::PaymentRepository", "edge_type": "call"},
        ],
        boundary_nodes=["payment.py::PaymentService"],
        external_edges=[],
        metadata={"root_node": "payment.py::PaymentService"},
    )


def test_sandbox_split_and_simulate():
    sandbox = SubsystemSandbox(_base_subsystem())
    sandbox.apply_change(
        {
            "action": "split_node",
            "node": "payment.py::PaymentService",
            "new_nodes": [
                "payment.py::PaymentProcessor",
                "payment.py::PaymentValidator",
            ],
        }
    )
    metrics = sandbox.get_metrics()
    result = sandbox.simulate()

    assert metrics["nodes"] >= 3
    assert "score_before" in result
    assert "score_after" in result


def test_sandbox_insert_service_layer():
    sandbox = SubsystemSandbox(_base_subsystem())
    sandbox.apply_change(
        {
            "action": "insert_service_layer",
            "source": "payment.py::PaymentController",
            "target": "payment.py::PaymentRepository",
            "service_node": "payment.py::PaymentServiceFacade",
        }
    )
    metrics = sandbox.get_metrics()
    assert metrics["nodes"] == 4


class _FakeGraph:
    """Minimal stand-in for ArchitectureGraph: only the fields build_partitions reads."""

    def __init__(self, node_ids, edges):
        self.nodes = [{"id": nid} for nid in node_ids]
        self.edges = [dict(e) for e in edges]
        self.adj_out = {}
        for e in edges:
            self.adj_out.setdefault(e["source"], set()).add(e["target"])


_RING_NODES = ["ring.py::A", "ring.py::B", "ring.py::C", "ring.py::D"]
_RING_EDGES = [
    {"source": "ring.py::A", "target": "ring.py::B", "edge_type": "call"},
    {"source": "ring.py::B", "target": "ring.py::C", "edge_type": "call"},
    {"source": "ring.py::C", "target": "ring.py::D", "edge_type": "call"},
    {"source": "ring.py::D", "target": "ring.py::A", "edge_type": "call"},
]


def test_build_partition_sandbox_partitioned_path(tmp_path):
    # No saved partitions on disk, so partitions are built from the graph.
    graph = _FakeGraph(_RING_NODES, _RING_EDGES)
    sandbox = build_partition_sandbox(tmp_path, graph, "ring.py::A")

    sub = sandbox.subsystem_graph
    node_ids = {n["id"] for n in sub.nodes}
    assert "ring.py::A" in node_ids
    assert "simulation_partition_id" in sub.metadata
    assert sub.edges, "sandbox should carry the partition's internal edges"
    for edge in sub.edges:
        assert edge["source"] in node_ids
        assert edge["target"] in node_ids


def test_build_partition_sandbox_no_partition_path(tmp_path):
    # Root node is not in any partition, so the sandbox falls back to the whole graph.
    graph = _FakeGraph(_RING_NODES, _RING_EDGES)
    sandbox = build_partition_sandbox(tmp_path, graph, "missing.py::X")

    sub = sandbox.subsystem_graph
    assert {n["id"] for n in sub.nodes} == set(_RING_NODES)
    assert len(sub.edges) == len(_RING_EDGES)


def test_build_partition_sandbox_does_not_mutate_source_graph(tmp_path):
    graph = _FakeGraph(_RING_NODES, _RING_EDGES)
    graph.nodes[0]["layer"] = 1
    sandbox = build_partition_sandbox(tmp_path, graph, "missing.py::X")

    for node in sandbox.subsystem_graph.nodes:
        node["layer"] = 99

    assert all(node["layer"] == 1 for node in graph.nodes[:1])
