from __future__ import annotations

from codegraph.architecture_graph import ArchitectureGraph
from codegraph.architecture_intent import ArchitectureIntent
from codegraph.intent_validator import validate_architecture_intent
from codegraph.models.graph0 import Graph0, Graph0Node
from codegraph.models.graph1 import Graph1
from codegraph.models.workflow import Workflow, WorkflowEdge


def test_intent_validator_detects_layer_violation():
    g0 = Graph0(
        nodes=[
            Graph0Node(id="controllers/user.py::UserController", body_hash="a", file="controllers/user.py", type="class", line=1),
            Graph0Node(id="repositories/user.py::UserRepository", body_hash="b", file="repositories/user.py", type="class", line=1),
        ]
    )
    graph = ArchitectureGraph.from_views(
        structure_graph=g0,
        intent_graph=Graph1(nodes=[]),
        workflow_graph=Workflow(
            edges=[
                WorkflowEdge(
                    source="controllers/user.py::UserController",
                    target="repositories/user.py::UserRepository",
                    edge_type="call",
                )
            ]
        ),
    )

    intent = ArchitectureIntent(
        layers={"API": ["controllers"], "Repository": ["repositories"]},
        rules=[{"from": "API", "to": "Repository", "allowed": False}],
    )

    report = validate_architecture_intent(graph, intent)
    assert report.rule_violations == 1
    assert report.layer_integrity_score < 1.0
    assert report.violations[0]["from_layer"] == "API"
