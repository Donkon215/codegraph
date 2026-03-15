from __future__ import annotations

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


def test_partition_persistence_roundtrip(tmp_path):
    graph = _graph()
    partitions = build_partitions(graph, min_size=1)
    save_partitions(tmp_path, partitions)

    loaded = load_partitions(tmp_path)
    assert loaded is not None
    assert loaded.partitions.keys() == partitions.partitions.keys()
    assert loaded.node_to_partition
