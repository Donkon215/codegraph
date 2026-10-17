from __future__ import annotations

import pytest

from codegraph.architecture_graph import ArchitectureGraph
from codegraph.graph_partitioning import build_partitions, load_partitions, save_partitions
from codegraph.models.graph0 import Graph0, Graph0Node
from codegraph.models.graph1 import Graph1
from codegraph.models.workflow import Workflow, WorkflowEdge


def _graph() -> ArchitectureGraph:
    g0 = Graph0(
        nodes=[
            Graph0Node(id="payment.py::PaymentService", body_hash="1", file="payment.py", type="class", line=1),
            Graph0Node(id="payment.py::PaymentRepo", body_hash="2", file="payment.py", type="class", line=2),
            Graph0Node(id="order.py::OrderService", body_hash="3", file="order.py", type="class", line=1),
            Graph0Node(id="order.py::OrderRepo", body_hash="4", file="order.py", type="class", line=2),
        ]
    )
    wf = Workflow(
        edges=[
            WorkflowEdge(source="payment.py::PaymentService", target="payment.py::PaymentRepo", edge_type="call"),
            WorkflowEdge(source="order.py::OrderService", target="order.py::OrderRepo", edge_type="call"),
            WorkflowEdge(source="order.py::OrderService", target="payment.py::PaymentService", edge_type="call"),
        ]
    )
    return ArchitectureGraph.from_views(structure_graph=g0, intent_graph=Graph1(nodes=[]), workflow_graph=wf)


def test_build_partitions_assigns_nodes_and_boundaries(tmp_path):
    graph = _graph()
    partitions = build_partitions(graph, min_size=1)

    assert partitions.partitions
    payment_partition = partitions.partition_for_node("payment.py::PaymentService")
    assert payment_partition is not None
    assert "payment.py::PaymentService" in payment_partition.nodes
    assert payment_partition.id


def test_min_size_does_not_lose_or_atomise_modules():
    """Every node lands in exactly one partition, and small modules stay whole.

    Note this guards existing behaviour rather than a fixed defect: singleton
    partitions in a real self-run are module-level nodes (ids with no "::",
    one per file), not atomised symbols. See issue #77.
    """
    graph = _graph()
    partitions = build_partitions(graph, min_size=4)

    assert partitions.partitions, "all modules must still land in some partition"
    assert set(partitions.node_to_partition) == {
        "payment.py::PaymentService", "payment.py::PaymentRepo",
        "order.py::OrderService", "order.py::OrderRepo",
    }
    payment = partitions.partition_for_node("payment.py::PaymentService")
    assert "payment.py::PaymentRepo" in payment.nodes
    order = partitions.partition_for_node("order.py::OrderService")
    assert "order.py::OrderRepo" in order.nodes


def test_unsupported_partition_method_is_rejected():
    # metadata must never claim a method the code cannot run (#78).
    graph = _graph()
    with pytest.raises(ValueError, match="label_propagation"):
        build_partitions(graph, method="louvain")
    assert build_partitions(graph).metadata["method"] == "label_propagation"


def test_partition_persistence_roundtrip(tmp_path):
    graph = _graph()
    partitions = build_partitions(graph, min_size=1)
    save_partitions(tmp_path, partitions)

    loaded = load_partitions(tmp_path)
    assert loaded is not None
    assert loaded.partitions.keys() == partitions.partitions.keys()
    assert loaded.node_to_partition
