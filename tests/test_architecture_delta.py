"""#28 acceptance tests: canonical ArchitectureDelta + ArchitectureChange input.

Covers: single canonical class, change -> delta projection, modify = remove+add,
constraint policy-change vs violation, and structural equivalence between the
TargetWorkflow path and the ArchitectureChange path.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from codegraph.architecture_change import (
    ArchitectureChange,
    ArchitectureOperation,
    OpType,
)
from codegraph.architecture_delta import (
    ArchitectureDelta,
    EdgeChange,
    NodeChange,
    generate_architecture_delta,
)
from codegraph.target_architecture import (
    TargetWorkflow,
    compute_architecture_delta,
)
from codegraph.architecture_change_adapters import target_workflow_to_change


class TestSingleCanonicalClass:
    def test_target_architecture_no_longer_defines_class(self):
        import codegraph.target_architecture as ta
        from codegraph.architecture_delta import ArchitectureDelta as Canonical

        # The duplicate definition is gone; target_architecture only re-exports
        # the single canonical class (same object, not a second definition).
        assert ta.ArchitectureDelta is Canonical

    def test_compute_returns_canonical(self):
        delta = compute_architecture_delta(TargetWorkflow(), {"edges": []}, set())
        assert isinstance(delta, ArchitectureDelta)


class TestChangeToDelta:
    def test_add_component(self):
        ac = ArchitectureChange(operations=[
            ArchitectureOperation(OpType.ADD_COMPONENT, component="x.py",
                                  component_subsystem="core", reason="r"),
        ])
        with tempfile.TemporaryDirectory() as d:
            delta = generate_architecture_delta(Path(d), change=ac)
        assert len(delta.added_nodes) == 1
        assert delta.added_nodes[0].node_id == "x.py"

    def test_remove_component(self):
        ac = ArchitectureChange(operations=[
            ArchitectureOperation(OpType.REMOVE_COMPONENT, component="x.py",
                                  component_subsystem="core"),
        ])
        with tempfile.TemporaryDirectory() as d:
            delta = generate_architecture_delta(Path(d), change=ac)
        assert len(delta.removed_nodes) == 1

    def test_add_subsystem(self):
        ac = ArchitectureChange(operations=[
            ArchitectureOperation(OpType.ADD_SUBSYSTEM, subsystem="core"),
        ])
        with tempfile.TemporaryDirectory() as d:
            delta = generate_architecture_delta(Path(d), change=ac)
        assert any(n.node_type == "subsystem" and n.node_id == "core"
                   for n in delta.added_nodes)

    def test_add_edge_preserves_type(self):
        ac = ArchitectureChange(operations=[
            ArchitectureOperation(OpType.ADD_EDGE, source="a", target="b",
                                  edge_type="dependency"),
        ])
        with tempfile.TemporaryDirectory() as d:
            delta = generate_architecture_delta(Path(d), change=ac)
        assert len(delta.added_edges) == 1
        assert delta.added_edges[0].edge_type == "dependency"

    def test_remove_edge(self):
        ac = ArchitectureChange(operations=[
            ArchitectureOperation(OpType.REMOVE_EDGE, source="a", target="b"),
        ])
        with tempfile.TemporaryDirectory() as d:
            delta = generate_architecture_delta(Path(d), change=ac)
        assert len(delta.removed_edges) == 1


class TestModifyIsRemovePlusAdd:
    def test_modify_edge(self):
        ac = ArchitectureChange(operations=[
            ArchitectureOperation(OpType.REMOVE_EDGE, source="a", target="b"),
            ArchitectureOperation(OpType.ADD_EDGE, source="a", target="c"),
        ])
        with tempfile.TemporaryDirectory() as d:
            delta = generate_architecture_delta(Path(d), change=ac)
        assert len(delta.removed_edges) == 1
        assert len(delta.added_edges) == 1


class TestConstraints:
    def _write_system(self, root: Path) -> None:
        system = {
            "subsystems": [
                {"name": "core", "components": [{"name": "c", "module": "codegraph/core.py"}]},
                {"name": "models", "components": [{"name": "m", "module": "codegraph/models.py"}]},
            ],
            "constraints": [
                {"type": "forbidden_dependency", "source": "core", "target": "models"},
            ],
        }
        arch_dir = root / ".codegraph" / "architecture"
        arch_dir.mkdir(parents=True, exist_ok=True)
        (arch_dir / "system.json").write_text(json.dumps(system), encoding="utf-8")

    def test_constraint_addition_is_not_a_violation(self):
        ac = ArchitectureChange(operations=[
            ArchitectureOperation(OpType.ADD_CONSTRAINT, constraint_type="forbidden_dependency",
                                  source="core", target="models"),
        ])
        with tempfile.TemporaryDirectory() as d:
            self._write_system(Path(d))
            delta = generate_architecture_delta(Path(d), change=ac)
        assert delta.constraint_violations == []
        assert "constraint_changes" in delta.metadata
        assert delta.metadata["constraint_changes"][0]["op"] == "ADD_CONSTRAINT"

    def test_violation_detected_in_proposed_state(self):
        ac = ArchitectureChange(operations=[
            ArchitectureOperation(OpType.ADD_EDGE, source="codegraph/core.py",
                                  target="codegraph/models.py"),
        ])
        with tempfile.TemporaryDirectory() as d:
            self._write_system(Path(d))
            delta = generate_architecture_delta(Path(d), change=ac)
        assert len(delta.constraint_violations) == 1
        assert delta.risk_estimate == "BLOCKED"


class TestSemanticEquivalence:
    def test_target_and_change_paths_match_structurally(self):
        target = TargetWorkflow()
        target.add_edge("a::f", "b::g", reason="needed")
        target.add_node("new.py", module="new.py", subsystem="api")

        # Target path
        target_delta = compute_architecture_delta(target, {"edges": []}, set())

        # Equivalent change path
        ac = target_workflow_to_change(target, {"edges": []}, set())
        with tempfile.TemporaryDirectory() as d:
            change_delta = generate_architecture_delta(Path(d), change=ac)

        assert len(target_delta.added_edges) == len(change_delta.added_edges)
        assert len(target_delta.added_nodes) == len(change_delta.added_nodes)
        assert {e.source for e in target_delta.added_edges} == \
               {e.source for e in change_delta.added_edges}
        assert {n.node_id for n in target_delta.added_nodes} == \
               {n.node_id for n in change_delta.added_nodes}
