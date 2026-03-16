from __future__ import annotations

from codegraph.architecture_graph import ArchitectureGraph
from codegraph.models.graph0 import Graph0, Graph0Node
from codegraph.models.graph1 import Graph1, Graph1Node
from codegraph.models.workflow import Workflow, WorkflowEdge
from codegraph.subsystem_graph import SubsystemGraph
from codegraph.subsystem_validator import validate_subsystem_patch


def _arch() -> ArchitectureGraph:
    g0 = Graph0(nodes=[
        Graph0Node(id="controller.py::OrdersController", body_hash="a", file="controller.py", type="class", line=1),
        Graph0Node(id="service.py::OrderService", body_hash="b", file="service.py", type="class", line=1),
        Graph0Node(id="repository.py::OrderRepo", body_hash="c", file="repository.py", type="class", line=1),
    ])
    g1 = Graph1(nodes=[
        Graph1Node(id="controller.py::OrdersController", layer=2),
        Graph1Node(id="service.py::OrderService", layer=3),
        Graph1Node(id="repository.py::OrderRepo", layer=4),
    ])
    wf = Workflow(edges=[
        WorkflowEdge(source="controller.py::OrdersController", target="service.py::OrderService", edge_type="call"),
        WorkflowEdge(source="service.py::OrderService", target="repository.py::OrderRepo", edge_type="call"),
    ])
    return ArchitectureGraph.from_views(structure_graph=g0, intent_graph=g1, workflow_graph=wf)


def test_validator_detects_external_breakage():
    subsystem = SubsystemGraph(
        nodes=[
            {"id": "service.py::OrderService", "layer": 3},
        ],
        edges=[],
        boundary_nodes=["service.py::OrderService"],
        external_edges=[
            {"source": "service.py::OrderService", "target": "repository.py::OrderRepo", "edge_type": "call"}
        ],
        metadata={},
    )

    patch = {"remove_edge": [["service.py::OrderService", "repository.py::OrderRepo", "call"]], "add_edge": []}
    result = validate_subsystem_patch(_arch(), subsystem, patch)

    assert result.valid is False
    assert any(v["violation"] == "external_dependency_breakage" for v in result.violations)


def test_validator_detects_layer_violation():
    subsystem = SubsystemGraph(
        nodes=[
            {"id": "controller.py::OrdersController", "layer": 2},
            {"id": "repository.py::OrderRepo", "layer": 4},
        ],
        edges=[],
        boundary_nodes=[],
        external_edges=[],
        metadata={},
    )

    patch = {"remove_edge": [], "add_edge": [["controller.py::OrdersController", "repository.py::OrderRepo", "call"]]}
    result = validate_subsystem_patch(_arch(), subsystem, patch)

    assert result.valid is False
    assert any(v["violation"] == "layer_boundary" for v in result.violations)
