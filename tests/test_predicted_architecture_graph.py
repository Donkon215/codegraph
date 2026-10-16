from __future__ import annotations

import json

from codegraph.architecture_change import ArchitectureChange, ArchitectureOperation, OpType
from codegraph.architecture_graph import ArchitectureGraph


def _op(kind: OpType, **kwargs) -> ArchitectureOperation:
    return ArchitectureOperation(kind, **kwargs)


def test_from_planned_applies_nodes_edges_and_constraints_without_mutating_input(tmp_path):
    current = ArchitectureGraph(
        nodes=[{"id": "a.py", "file": "a.py", "type": "module"},
               {"id": "b.py", "file": "b.py", "type": "module"}],
        edges=[{"source": "a.py", "target": "b.py", "edge_type": "dependency"}],
        metadata={"subsystems": ["core"], "constraints": []},
    )
    before = (json.dumps(current.nodes, sort_keys=True), json.dumps(current.edges, sort_keys=True),
              json.dumps(current.metadata, sort_keys=True))
    change = ArchitectureChange(operations=[
        _op(OpType.ADD_COMPONENT, component="c.py", component_subsystem="core"),
        _op(OpType.REMOVE_COMPONENT, component="b.py"),
        _op(OpType.REMOVE_EDGE, source="a.py", target="b.py", edge_type="dependency"),
        _op(OpType.ADD_EDGE, source="a.py", target="c.py", edge_type="dependency"),
        _op(OpType.ADD_CONSTRAINT, constraint_type="forbidden", source="core", target="external"),
    ])

    predicted = ArchitectureGraph.from_planned(current, change)

    assert {node["id"] for node in predicted.nodes} == {"a.py", "c.py"}
    assert predicted.edges == [{
        "source": "a.py", "target": "c.py", "edge_type": "dependency",
        "confidence": 1.0, "source_detail": "", "conditional": False,
    }]
    assert predicted.metadata["constraints"] == [{
        "constraint_type": "forbidden", "source": "core", "target": "external",
    }]
    assert (json.dumps(current.nodes, sort_keys=True), json.dumps(current.edges, sort_keys=True),
            json.dumps(current.metadata, sort_keys=True)) == before


def test_remove_constraint_and_subsystem_are_projected():
    current = ArchitectureGraph(
        nodes=[{"id": "pkg/a.py", "subsystem": "old"}],
        metadata={"subsystems": ["old", "keep"], "constraints": [
            {"constraint_type": "forbidden", "source": "keep", "target": "x"},
        ]},
    )
    change = ArchitectureChange(operations=[
        _op(OpType.REMOVE_SUBSYSTEM, subsystem="old"),
        _op(OpType.REMOVE_CONSTRAINT, constraint_type="forbidden", source="keep", target="x"),
        _op(OpType.ADD_SUBSYSTEM, subsystem="new"),
    ])

    predicted = ArchitectureGraph.from_planned(current, change)

    assert predicted.nodes == []
    assert predicted.metadata["subsystems"] == ["keep", "new"]
    assert predicted.metadata["constraints"] == []


def test_save_predicted_writes_only_prediction_artifact(tmp_path):
    graph = ArchitectureGraph(nodes=[{"id": "one.py"}])
    source_file = tmp_path / "one.py"
    source_file.write_bytes(b"# source file remains byte-for-byte unchanged\n\x00")
    source_before = source_file.read_bytes()
    real_graph = tmp_path / ".codegraph" / "graphs" / "graph0.json"
    real_graph.parent.mkdir(parents=True)
    real_graph.write_text('{"real": true}', encoding="utf-8")

    artifact = graph.save_predicted(tmp_path)

    assert artifact == tmp_path / ".codegraph" / "predicted_graph.json"
    assert json.loads(artifact.read_text(encoding="utf-8"))["predicted"] is True
    assert source_file.read_bytes() == source_before
    assert real_graph.read_text(encoding="utf-8") == '{"real": true}'
    assert sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*.json")) == [
        ".codegraph/graphs/graph0.json", ".codegraph/predicted_graph.json",
    ]


def test_predicted_graph_is_loadable_and_test_impact_uses_its_edges(tmp_path):
    from codegraph.test_impact import analyze_predicted_test_impact

    graph = ArchitectureGraph(
        nodes=[{"id": "src/service.py::run", "file": "src/service.py", "type": "function"},
               {"id": "tests/test_service.py::test_run", "file": "tests/test_service.py", "type": "test"}],
        edges=[{"source": "tests/test_service.py::test_run", "target": "src/service.py::run", "edge_type": "call"}],
    )
    artifact = graph.save_predicted(tmp_path)
    loaded = ArchitectureGraph.load_predicted(artifact)

    current = ArchitectureGraph(
        nodes=loaded.nodes,
        edges=[{"source": "tests/test_service.py::test_run", "target": "src/service.py::old", "edge_type": "call"}],
    )
    result = analyze_predicted_test_impact(
        {"src/service.py::run"}, loaded, current_graph=current,
    )

    assert [item.test_id for item in result.affected_tests] == ["tests/test_service.py::test_run"]
    assert result.affected_tests[0].change_types == ["direct"]
    assert "tests/test_service.py::test_run" in result.affected_nodes
    assert result.new_dependencies == [("tests/test_service.py::test_run", "src/service.py::run", "call")]
    assert result.removed_dependencies == [("tests/test_service.py::test_run", "src/service.py::old", "call")]


def test_loading_malformed_prediction_fails_with_value_error(tmp_path):
    artifact = tmp_path / "predicted_graph.json"
    artifact.write_text('{"predicted": true, "nodes": {}, "edges": []}', encoding="utf-8")

    try:
        ArchitectureGraph.load_predicted(artifact)
    except ValueError as exc:
        assert "malformed" in str(exc)
    else:
        raise AssertionError("malformed predicted graph should be rejected")


def test_layer_detector_accepts_predicted_architecture_edges():
    from codegraph.architecture_detection import detect_layered_architecture

    graph = ArchitectureGraph(
        nodes=[{"id": "storage/model.py", "file": "storage/model.py"},
               {"id": "service/api.py", "file": "service/api.py"}],
        edges=[{"source": "storage/model.py", "target": "service/api.py", "edge_type": "dependency"}],
    )

    report = detect_layered_architecture(graph.structure_graph, architecture_graph=graph)

    assert report["details"]["upward_violations"] == 1


def test_architecture_score_accepts_injected_predicted_graph(tmp_path):
    from codegraph.architecture_scoring import compute_architecture_index

    graph = ArchitectureGraph(nodes=[
        {"id": "a.py::one", "file": "a.py", "type": "function"},
        {"id": "b.py::two", "file": "b.py", "type": "function"},
    ], edges=[{"source": "a.py::one", "target": "b.py::two", "edge_type": "call"}])

    score = compute_architecture_index(tmp_path, architecture_graph=graph)

    assert 0.0 <= score.score <= 1.0


def test_architecture_advisor_runs_on_injected_graph_without_real_index(tmp_path):
    from codegraph.architecture_advisor import advise_architecture

    graph = ArchitectureGraph(nodes=[
        {"id": "src/service.py::run", "file": "src/service.py", "type": "function"},
        {"id": "src/store.py::load", "file": "src/store.py", "type": "function"},
    ], edges=[{"source": "src/service.py::run", "target": "src/store.py::load", "edge_type": "call"}])

    advice = advise_architecture(
        graph.structure_graph, architecture_graph=graph, project_root=tmp_path,
    )

    assert advice.total_nodes == 2
    assert not (tmp_path / ".codegraph" / "index" / "codegraph.db").exists()
