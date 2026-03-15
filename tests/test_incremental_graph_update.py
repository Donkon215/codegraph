from __future__ import annotations

from codegraph.architecture_graph import ArchitectureGraph
from codegraph.incremental_graph_update import incremental_update_graph
from codegraph.models.graph0 import Graph0, Graph0Node
from codegraph.models.graph1 import Graph1
from codegraph.models.workflow import Workflow, WorkflowEdge
from codegraph.subsystem_cache import SubsystemCache
from codegraph.subsystem_graph import SubsystemGraph


def _graph() -> ArchitectureGraph:
    g0 = Graph0(
        nodes=[
            Graph0Node(id="a.py::A", body_hash="1", file="a.py", type="class", line=1),
            Graph0Node(id="b.py::B", body_hash="2", file="b.py", type="class", line=1),
        ]
    )
    wf = Workflow(edges=[WorkflowEdge(source="a.py::A", target="b.py::B", edge_type="call")])
    return ArchitectureGraph.from_views(structure_graph=g0, intent_graph=Graph1(nodes=[]), workflow_graph=wf)


def test_incremental_update_recomputes_partitions_and_invalidates_cache(monkeypatch, tmp_path):
    graph = _graph()

    cache = SubsystemCache(tmp_path)
    cache.put(
        "a.py::A",
        SubsystemGraph(
            nodes=[{"id": "a.py::A", "file": "a.py", "type": "class"}],
            edges=[],
            boundary_nodes=[],
            metadata={},
        ),
    )

    import codegraph.incremental_graph_update as inc

    monkeypatch.setattr(inc, "detect_changed_files", lambda root: ["a.py"])

    result = incremental_update_graph(tmp_path, graph)

    assert result.status == "ok"
    assert "a.py::A" in result.changed_nodes
    assert result.invalidated_cache_entries >= 1
    assert result.recomputed_partitions
