from __future__ import annotations

from codegraph.architecture_graph import ArchitectureGraph
from codegraph.models.graph0 import Graph0, Graph0Node
from codegraph.models.graph1 import Graph1, Graph1Node
from codegraph.models.workflow import Workflow, WorkflowEdge
from codegraph.subsystem_extractor import extract_subsystem


def _make_arch_graph() -> ArchitectureGraph:
    g0 = Graph0(
        nodes=[
            Graph0Node(id="payment.py::PaymentController", body_hash="a", file="payment.py", type="class", line=1),
            Graph0Node(id="payment.py::PaymentService", body_hash="b", file="payment.py", type="class", line=2),
            Graph0Node(id="payment.py::PaymentRepository", body_hash="c", file="payment.py", type="class", line=3),
            Graph0Node(id="orders.py::OrderService", body_hash="d", file="orders.py", type="class", line=1),
        ]
    )
    g1 = Graph1(
        nodes=[
            Graph1Node(id="payment.py::PaymentController", layer=2),
            Graph1Node(id="payment.py::PaymentService", layer=3),
            Graph1Node(id="payment.py::PaymentRepository", layer=4),
            Graph1Node(id="orders.py::OrderService", layer=3),
        ]
    )
    wf = Workflow(
        edges=[
            WorkflowEdge(source="payment.py::PaymentController", target="payment.py::PaymentService", edge_type="call"),
            WorkflowEdge(source="payment.py::PaymentService", target="payment.py::PaymentRepository", edge_type="call"),
            WorkflowEdge(source="orders.py::OrderService", target="payment.py::PaymentService", edge_type="call"),
        ]
    )
    return ArchitectureGraph.from_views(structure_graph=g0, intent_graph=g1, workflow_graph=wf)


def test_extract_subsystem_slice_and_boundaries():
    arch = _make_arch_graph()
    subsystem = extract_subsystem(arch, "payment.py::PaymentService", depth=1, max_nodes=50)

    node_ids = {node["id"] for node in subsystem.nodes}
    assert "payment.py::PaymentService" in node_ids
    assert "payment.py::PaymentController" in node_ids
    assert "payment.py::PaymentRepository" in node_ids
    assert "orders.py::OrderService" in node_ids

    assert "payment.py::PaymentService" in subsystem.boundary_nodes
    assert isinstance(subsystem.metadata.get("external_dependencies", []), list)


def test_extract_subsystem_respects_max_nodes():
    arch = _make_arch_graph()
    subsystem = extract_subsystem(arch, "payment.py::PaymentService", depth=3, max_nodes=2)
    assert len(subsystem.nodes) <= 2
