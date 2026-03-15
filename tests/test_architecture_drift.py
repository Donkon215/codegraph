from __future__ import annotations

from codegraph.architecture_drift import compute_architecture_drift
from codegraph.architecture_graph import ArchitectureGraph
from codegraph.architecture_intent import ArchitectureIntent
from codegraph.models.graph0 import Graph0, Graph0Node
from codegraph.models.graph1 import Graph1
from codegraph.models.workflow import Workflow, WorkflowEdge


def test_architecture_drift_score_from_violations():
    graph = ArchitectureGraph.from_views(
        structure_graph=Graph0(
            nodes=[
                Graph0Node(id="api.py::A", body_hash="a", file="api.py", type="function", line=1),
                Graph0Node(id="repo.py::B", body_hash="b", file="repo.py", type="function", line=1),
            ]
        ),
        intent_graph=Graph1(nodes=[]),
        workflow_graph=Workflow(
            edges=[WorkflowEdge(source="api.py::A", target="repo.py::B", edge_type="call")]
        ),
    )

    intent = ArchitectureIntent(
        layers={"API": ["api.py"], "Repository": ["repo.py"]},
        rules=[{"from": "API", "to": "Repository", "allowed": False}],
    )

    report = compute_architecture_drift(graph, intent)
    assert report.rule_drift > 0.0
    assert report.edge_drift > 0.0
    assert report.drift_score > 0.0
