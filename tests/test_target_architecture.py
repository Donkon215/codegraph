"""Tests for codegraph.target_architecture — target state & delta engine."""

import json
import tempfile
from pathlib import Path

import pytest

from codegraph.architecture_delta import ArchitectureDelta, EdgeChange, NodeChange
from codegraph.target_architecture import (
    TargetEdge,
    TargetNode,
    TargetWorkflow,
    compute_architecture_delta,
    delta_to_tasks,
    generate_target_from_architecture,
    save_target_delta,
)


class TestTargetEdge:
    def test_to_dict_minimal(self):
        e = TargetEdge("a::f", "b::g")
        d = e.to_dict()
        assert d["source"] == "a::f"
        assert d["target"] == "b::g"
        assert "reason" not in d
        assert "priority" not in d

    def test_to_dict_full(self):
        e = TargetEdge("a::f", "b::g", reason="needed", priority=3, subsystem="core")
        d = e.to_dict()
        assert d["reason"] == "needed"
        assert d["priority"] == 3
        assert d["subsystem"] == "core"

    def test_roundtrip(self):
        e = TargetEdge("a::f", "b::g", reason="test", priority=2)
        restored = TargetEdge.from_dict(e.to_dict())
        assert restored.source == "a::f"
        assert restored.target == "b::g"
        assert restored.reason == "test"
        assert restored.priority == 2

    def test_from_dict_defaults(self):
        e = TargetEdge.from_dict({"source": "x", "target": "y"})
        assert e.reason == ""
        assert e.priority == 5
        assert e.subsystem == ""


class TestTargetNode:
    def test_to_dict_minimal(self):
        n = TargetNode("a::f")
        d = n.to_dict()
        assert d["node_id"] == "a::f"
        assert "module" not in d

    def test_to_dict_full(self):
        n = TargetNode("a::f", module="a.py", subsystem="core",
                        intent="Does stuff", reason="Required")
        d = n.to_dict()
        assert d["module"] == "a.py"
        assert d["intent"] == "Does stuff"

    def test_roundtrip(self):
        n = TargetNode("a::f", module="a.py", intent="test")
        restored = TargetNode.from_dict(n.to_dict())
        assert restored.node_id == "a::f"
        assert restored.module == "a.py"
        assert restored.intent == "test"


class TestTargetWorkflow:
    def test_empty_workflow(self):
        tw = TargetWorkflow()
        d = tw.to_dict()
        assert d["version"] == 1
        assert d["edges"] == []
        assert d["nodes"] == []

    def test_add_edge(self):
        tw = TargetWorkflow()
        tw.add_edge("a::f", "b::g", reason="test")
        assert len(tw.edges) == 1
        assert tw.edges[0].source == "a::f"
        assert tw.edges[0].reason == "test"

    def test_add_node(self):
        tw = TargetWorkflow()
        tw.add_node("a::f", module="a.py", intent="helper")
        assert len(tw.nodes) == 1
        assert tw.nodes[0].node_id == "a::f"

    def test_roundtrip(self):
        tw = TargetWorkflow(description="test target")
        tw.add_edge("a::f", "b::g")
        tw.add_node("c::h")
        restored = TargetWorkflow.from_dict(tw.to_dict())
        assert restored.description == "test target"
        assert len(restored.edges) == 1
        assert len(restored.nodes) == 1

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tw = TargetWorkflow(description="save test")
            tw.add_edge("x::f", "y::g")
            tw.save(root)

            loaded = TargetWorkflow.load(root)
            assert loaded is not None
            assert loaded.description == "save test"
            assert len(loaded.edges) == 1
            assert loaded.edges[0].source == "x::f"

    def test_load_nonexistent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            assert TargetWorkflow.load(Path(tmpdir)) is None


class TestArchitectureDelta:
    def test_empty_delta(self):
        d = ArchitectureDelta()
        assert not d.has_changes
        assert d.total_changes == 0

    def test_has_changes(self):
        d = ArchitectureDelta(added_edges=[EdgeChange("a", "b")])
        assert d.has_changes
        assert d.total_changes == 1

    def test_total_changes(self):
        d = ArchitectureDelta(
            added_edges=[EdgeChange("a", "b")],
            removed_edges=[EdgeChange("c", "d")],
            added_nodes=[NodeChange("e")],
            removed_nodes=[NodeChange("f")],
        )
        assert d.total_changes == 4

    def test_to_dict_summary(self):
        d = ArchitectureDelta(added_edges=[EdgeChange("a", "b")])
        dd = d.to_dict()
        assert len(dd["added_edges"]) == 1
        assert dd["total_changes"] == 1

    def test_format(self):
        d = ArchitectureDelta(
            added_edges=[EdgeChange("a", "b", reason="required")],
            removed_edges=[EdgeChange("c", "d")],
        )
        text = d.format()
        assert "Added edges: 1" in text
        assert "a -> b" in text

    def test_save(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            d = ArchitectureDelta(added_edges=[EdgeChange("a", "b")])
            path = d.save(root)
            assert path.exists()
            data = json.loads(path.read_text(encoding="utf-8"))
            assert len(data["added_edges"]) == 1


class TestComputeArchitectureDelta:
    def test_no_changes(self):
        target = TargetWorkflow()
        target.add_edge("a::f", "b::g")
        workflow = {"edges": [{"source": "a::f", "target": "b::g"}]}
        nodes = {"a::f", "b::g"}
        delta = compute_architecture_delta(target, workflow, nodes)
        assert not delta.has_changes

    def test_missing_edge(self):
        target = TargetWorkflow()
        target.add_edge("a::f", "b::g", reason="needed")
        workflow = {"edges": []}
        delta = compute_architecture_delta(target, workflow, set())
        assert len(delta.added_edges) == 1
        assert delta.added_edges[0].source == "a::f"

    def test_extra_edge(self):
        target = TargetWorkflow()
        target.add_edge("a::f", "b::g")
        workflow = {"edges": [
            {"source": "a::f", "target": "b::g"},
            {"source": "a::f", "target": "c::h"},
        ]}
        delta = compute_architecture_delta(target, workflow, set())
        # a::f is in target sources, so a::f → c::h is extra
        assert len(delta.removed_edges) == 1
        assert delta.removed_edges[0].target == "c::h"

    def test_missing_node(self):
        target = TargetWorkflow()
        target.add_node("new::func", module="new.py")
        workflow = {"edges": []}
        delta = compute_architecture_delta(target, workflow, set())
        assert len(delta.added_nodes) == 1
        assert delta.added_nodes[0].node_id == "new::func"

    def test_existing_node_not_missing(self):
        target = TargetWorkflow()
        target.add_node("a::f")
        workflow = {"edges": []}
        delta = compute_architecture_delta(target, workflow, {"a::f"})
        assert len(delta.added_nodes) == 0

    def test_priority_sorting(self):
        target = TargetWorkflow()
        target.add_edge("a::f", "b::g", priority=9)
        target.add_edge("c::h", "d::i", priority=1)
        workflow = {"edges": []}
        delta = compute_architecture_delta(target, workflow, set())
        assert delta.added_edges[0].priority == 1  # sorted ascending


class TestDeltaToTasks:
    def test_missing_edge_repair(self):
        delta = ArchitectureDelta(
            added_edges=[EdgeChange("a::f", "b::g", reason="needed")],
        )
        response = delta_to_tasks(delta, 42)
        assert response["graph_version"] == 42
        assert len(response["repairs"]) == 1
        assert response["repairs"][0]["action"] == "connect_call"
        assert response["repairs"][0]["node"] == "a::f"

    def test_missing_node_flagged(self):
        delta = ArchitectureDelta(
            added_nodes=[NodeChange("x::y", module="x.py",
                                    reason="needed", intent="helper")],
        )
        response = delta_to_tasks(delta, 1)
        assert len(response["repairs"]) == 1
        assert response["repairs"][0]["action"] == "flag_for_human_review"
        assert len(response["intents"]) == 1
        assert response["intents"][0]["intent"] == "helper"

    def test_extra_edge_flagged(self):
        delta = ArchitectureDelta(removed_edges=[EdgeChange("a", "b")])
        response = delta_to_tasks(delta, 1)
        assert len(response["repairs"]) == 1
        assert response["repairs"][0]["action"] == "flag_for_human_review"

    def test_empty_delta(self):
        delta = ArchitectureDelta()
        response = delta_to_tasks(delta, 1)
        assert response["repairs"] == []
        assert response["intents"] == []


class TestLegacySerialization:
    def test_round_trip_legacy_shape(self):
        delta = ArchitectureDelta(
            added_edges=[EdgeChange("a", "b", reason="r", priority=2)],
            removed_edges=[EdgeChange("c", "d")],
            added_nodes=[NodeChange("n", module="m.py", subsystem="s",
                                    intent="i", reason="nr")],
            removed_nodes=[NodeChange("o")],
        )
        legacy = delta.to_legacy_target_dict()
        assert legacy["summary"]["missing_edges"] == 1
        assert legacy["summary"]["extra_edges"] == 1
        assert legacy["summary"]["missing_nodes"] == 1
        assert legacy["summary"]["extra_nodes"] == 1

        restored = ArchitectureDelta.from_legacy_target_dict(legacy)
        assert len(restored.added_edges) == 1
        assert restored.added_edges[0].source == "a"
        assert restored.added_edges[0].priority == 2
        assert len(restored.removed_edges) == 1
        assert restored.removed_nodes[0].node_id == "o"

    def test_save_target_delta_legacy_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            delta = ArchitectureDelta(added_edges=[EdgeChange("a", "b")])
            path = save_target_delta(delta, root)
            assert path.name == "delta.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            assert data["summary"]["missing_edges"] == 1
            # reload through the legacy loader -> canonical
            restored = ArchitectureDelta.from_legacy_target_dict(data)
            assert len(restored.added_edges) == 1


class TestGenerateTargetFromArchitecture:
    def _make_arch(self):
        """Build a minimal SystemArchitecture-like object."""
        from codegraph.arch_schema import (
            ArchComponent, ArchEdge, SubsystemDef, SystemArchitecture,
        )
        ss_a = SubsystemDef(
            name="core",
            description="Core engine",
            components=[
                ArchComponent(name="extractor", module="codegraph/extractor.py",
                              functions=["extract"]),
            ],
        )
        ss_b = SubsystemDef(
            name="models",
            description="Data models",
            components=[
                ArchComponent(name="graph0", module="codegraph/models/graph0.py",
                              functions=["Graph0::load"]),
            ],
        )
        arch = SystemArchitecture(
            name="test",
            subsystems=[ss_a, ss_b],
            edges=[ArchEdge(source="core", target="models")],
        )
        return arch

    def test_generates_target_nodes(self):
        arch = self._make_arch()
        workflow = {"edges": []}
        target = generate_target_from_architecture(arch, workflow)
        assert len(target.nodes) >= 2

    def test_generates_edges_from_architecture(self):
        arch = self._make_arch()
        # Simulate a function-level edge matching the architecture edge
        workflow = {"edges": [
            {"source": "codegraph/extractor.py::extract",
             "target": "codegraph/models/graph0.py::Graph0::load"},
        ]}
        target = generate_target_from_architecture(arch, workflow)
        assert len(target.edges) >= 1

    def test_missing_architecture_edge_becomes_target(self):
        arch = self._make_arch()
        workflow = {"edges": []}  # no function-level edges at all
        target = generate_target_from_architecture(arch, workflow)
        # Should still have the architecture-level edge as target
        edge_pairs = [(e.source, e.target) for e in target.edges]
        assert ("core", "models") in edge_pairs
