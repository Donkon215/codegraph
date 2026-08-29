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

    def test_target_nodes_not_scoped_for_removal(self):
        # Target nodes are intentionally non-scoped, mirroring the edge rule
        # (edges are only removed when their source is in the target scope).
        # A current node absent from the target is NOT reported as a removal.
        target = TargetWorkflow()
        target.add_node("new.py", module="new.py", subsystem="api")
        delta = compute_architecture_delta(target, {"edges": []}, {"old.py"})
        # new.py: target but not current -> added
        assert len(delta.added_nodes) == 1 and delta.added_nodes[0].node_id == "new.py"
        # old.py: current but not target -> NOT removed (nodes non-scoped)
        assert delta.removed_nodes == []


class TestChangeToDelta:
    def test_add_component(self):
        ac = ArchitectureChange(operations=[
            ArchitectureOperation(OpType.ADD_COMPONENT, component="x.py",
                                  component_subsystem="core", reason="r"),
        ])
        with tempfile.TemporaryDirectory() as d:
            delta = generate_architecture_delta(Path(d), change=ac)
        assert len(delta.added_nodes) == 1
        n = delta.added_nodes[0]
        assert n.node_id == "x.py"
        # Locked contract: ADD_COMPONENT -> node_type "module" (not "component")
        assert n.node_type == "module"
        # subsystem metadata is preserved, not silently dropped
        assert n.subsystem == "core"

    def test_remove_component(self):
        # Removing a component that does not exist is a no-op (no state difference).
        ac = ArchitectureChange(operations=[
            ArchitectureOperation(OpType.REMOVE_COMPONENT, component="x.py",
                                  component_subsystem="core"),
        ])
        with tempfile.TemporaryDirectory() as d:
            delta = generate_architecture_delta(Path(d), change=ac)
        assert len(delta.removed_nodes) == 0

    def test_add_subsystem(self):
        ac = ArchitectureChange(operations=[
            ArchitectureOperation(OpType.ADD_SUBSYSTEM, subsystem="core"),
        ])
        with tempfile.TemporaryDirectory() as d:
            delta = generate_architecture_delta(Path(d), change=ac)
        assert any(n.node_type == "subsystem" and n.node_id == "core"
                   for n in delta.added_nodes)

    def test_remove_subsystem(self):
        # Removing a subsystem that does not exist is a no-op.
        ac = ArchitectureChange(operations=[
            ArchitectureOperation(OpType.REMOVE_SUBSYSTEM, subsystem="core"),
        ])
        with tempfile.TemporaryDirectory() as d:
            delta = generate_architecture_delta(Path(d), change=ac)
        assert delta.removed_nodes == []

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
        # Removing an edge that does not exist is a no-op (no state difference).
        ac = ArchitectureChange(operations=[
            ArchitectureOperation(OpType.REMOVE_EDGE, source="a", target="b"),
        ])
        with tempfile.TemporaryDirectory() as d:
            delta = generate_architecture_delta(Path(d), change=ac)
        assert len(delta.removed_edges) == 0


class TestModifyIsRemovePlusAdd:
    def test_add_then_remove_same_edge_net_zero(self):
        # ADD then REMOVE the same edge against an empty current state -> no diff.
        ac = ArchitectureChange(operations=[
            ArchitectureOperation(OpType.ADD_EDGE, source="a", target="b"),
            ArchitectureOperation(OpType.REMOVE_EDGE, source="a", target="b"),
        ])
        with tempfile.TemporaryDirectory() as d:
            delta = generate_architecture_delta(Path(d), change=ac)
        assert delta.added_edges == []
        assert delta.removed_edges == []


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
        # Locked contract: constraint_type survives verbatim, never normalized.
        assert delta.constraint_violations[0].constraint_type == "forbidden_dependency"
        assert delta.risk_estimate == "BLOCKED"

    def test_policy_removal_removes_violation(self):
        ac = ArchitectureChange(operations=[
            ArchitectureOperation(OpType.ADD_EDGE, source="codegraph/core.py",
                                  target="codegraph/models.py"),
            ArchitectureOperation(OpType.REMOVE_CONSTRAINT, constraint_type="forbidden_dependency",
                                  source="core", target="models"),
        ])
        with tempfile.TemporaryDirectory() as d:
            self._write_system(Path(d))
            delta = generate_architecture_delta(Path(d), change=ac)
        # The forbidden policy is gone, so the proposed edge is no longer a violation.
        assert delta.constraint_violations == []
        assert delta.metadata["constraint_changes"][-1]["op"] == "REMOVE_CONSTRAINT"


class TestSemanticEquivalence:
    def test_target_and_change_paths_match_structurally(self):
        target = TargetWorkflow()
        target.add_edge("a::f", "b::g", reason="needed", priority=2)
        target.add_node("new.py", module="new.py", subsystem="api")

        # Target path
        target_delta = compute_architecture_delta(target, {"edges": []}, set())

        # Equivalent change path
        ac = target_workflow_to_change(target, {"edges": []}, set())
        with tempfile.TemporaryDirectory() as d:
            change_delta = generate_architecture_delta(Path(d), change=ac)

        # Both historical producers must yield the SAME canonical object,
        # not merely objects sharing IDs.
        def node_key(n):
            return (n.node_id, n.module, n.node_type, n.subsystem, n.intent)

        def edge_key(e):
            return (e.source, e.target, e.edge_type, e.priority, e.reason)

        assert [node_key(n) for n in target_delta.added_nodes] == \
               [node_key(n) for n in change_delta.added_nodes]
        assert [edge_key(e) for e in target_delta.added_edges] == \
               [edge_key(e) for e in change_delta.added_edges]
        assert target_delta.affected_subsystems == change_delta.affected_subsystems

        # Phase 1 contract: ADD_COMPONENT -> node_type "module" on BOTH paths.
        assert all(n.node_type == "module" for n in target_delta.added_nodes)
        assert all(n.node_type == "module" for n in change_delta.added_nodes)

    def test_target_edge_priority_preserved_through_funnel(self):
        # TargetEdge.priority (non-default) must survive the funnel even though
        # the frozen ArchitectureChange IR has no priority field.
        target = TargetWorkflow()
        target.add_edge("a::f", "b::g", reason="needed", priority=2)
        direct = compute_architecture_delta(target, {"edges": []}, set())
        assert direct.added_edges[0].priority == 2

        ac = target_workflow_to_change(target, {"edges": []}, set())
        with tempfile.TemporaryDirectory() as d:
            funnel = generate_architecture_delta(Path(d), change=ac)
        assert funnel.added_edges[0].priority == 2


class TestNoOpSemantics:
    """The locked contract: delta == diff(current, current + change).

    A no-op operation (adding something already present, removing something
    absent, or cancelling operations) must NOT appear in the delta.
    """

    def _state(self, d, *, edges=None, system=None):
        root = Path(d)
        if edges is not None:
            wf_dir = root / ".codegraph" / "workflow"
            wf_dir.mkdir(parents=True, exist_ok=True)
            (wf_dir / "workflow.json").write_text(
                json.dumps({"edges": edges, "nodes": []}), encoding="utf-8")
        if system is not None:
            arch_dir = root / ".codegraph" / "architecture"
            arch_dir.mkdir(parents=True, exist_ok=True)
            (arch_dir / "system.json").write_text(
                json.dumps(system), encoding="utf-8")

    def test_add_existing_edge(self):
        with tempfile.TemporaryDirectory() as d:
            self._state(d, edges=[{"source": "A", "target": "B", "edge_type": "call"}])
            ac = ArchitectureChange(operations=[
                ArchitectureOperation(OpType.ADD_EDGE, source="A", target="B")])
            delta = generate_architecture_delta(Path(d), change=ac)
        assert delta.added_edges == []
        assert delta.removed_edges == []

    def test_remove_missing_edge(self):
        with tempfile.TemporaryDirectory() as d:
            ac = ArchitectureChange(operations=[
                ArchitectureOperation(OpType.REMOVE_EDGE, source="A", target="B")])
            delta = generate_architecture_delta(Path(d), change=ac)
        assert delta.removed_edges == []

    def test_add_existing_component(self):
        system = {"subsystems": [{"name": "core",
                                  "components": [{"name": "x", "module": "x.py"}]}]}
        with tempfile.TemporaryDirectory() as d:
            self._state(d, system=system)
            ac = ArchitectureChange(operations=[
                ArchitectureOperation(OpType.ADD_COMPONENT, component="x.py",
                                      component_subsystem="core")])
            delta = generate_architecture_delta(Path(d), change=ac)
        assert delta.added_nodes == []

    def test_remove_missing_component(self):
        with tempfile.TemporaryDirectory() as d:
            ac = ArchitectureChange(operations=[
                ArchitectureOperation(OpType.REMOVE_COMPONENT, component="x.py",
                                      component_subsystem="core")])
            delta = generate_architecture_delta(Path(d), change=ac)
        assert delta.removed_nodes == []

    def test_add_then_remove_same_edge(self):
        ac = ArchitectureChange(operations=[
            ArchitectureOperation(OpType.ADD_EDGE, source="A", target="B"),
            ArchitectureOperation(OpType.REMOVE_EDGE, source="A", target="B"),
        ])
        with tempfile.TemporaryDirectory() as d:
            delta = generate_architecture_delta(Path(d), change=ac)
        assert delta.added_edges == []
        assert delta.removed_edges == []

    def test_remove_then_add_replacement(self):
        # current A->B(call); remove it + add A->B(dependency) => type modification
        with tempfile.TemporaryDirectory() as d:
            self._state(d, edges=[{"source": "A", "target": "B", "edge_type": "call"}])
            ac = ArchitectureChange(operations=[
                ArchitectureOperation(OpType.REMOVE_EDGE, source="A", target="B"),
                ArchitectureOperation(OpType.ADD_EDGE, source="A", target="B",
                                      edge_type="dependency")])
            delta = generate_architecture_delta(Path(d), change=ac)
        assert len(delta.removed_edges) == 1 and delta.removed_edges[0].edge_type == "call"
        assert len(delta.added_edges) == 1 and delta.added_edges[0].edge_type == "dependency"

    def test_modify_edge_type(self):
        # Changing an edge's type is expressed as REMOVE(old) + ADD(new).
        with tempfile.TemporaryDirectory() as d:
            self._state(d, edges=[{"source": "A", "target": "B", "edge_type": "call"}])
            ac = ArchitectureChange(operations=[
                ArchitectureOperation(OpType.REMOVE_EDGE, source="A", target="B", edge_type="call"),
                ArchitectureOperation(OpType.ADD_EDGE, source="A", target="B",
                                      edge_type="dependency")])
            delta = generate_architecture_delta(Path(d), change=ac)
        assert len(delta.removed_edges) == 1 and delta.removed_edges[0].edge_type == "call"
        assert len(delta.added_edges) == 1 and delta.added_edges[0].edge_type == "dependency"

    def test_empty_change(self):
        ac = ArchitectureChange(operations=[])
        with tempfile.TemporaryDirectory() as d:
            delta = generate_architecture_delta(Path(d), change=ac)
        assert delta.added_edges == []
        assert delta.removed_edges == []
        assert delta.added_nodes == []
        assert delta.removed_nodes == []
        assert delta.constraint_violations == []


class TestAffectedSubsystems:
    def test_subsystem_add_populates_affected(self):
        ac = ArchitectureChange(operations=[
            ArchitectureOperation(OpType.ADD_SUBSYSTEM, subsystem="newsub")])
        with tempfile.TemporaryDirectory() as d:
            delta = generate_architecture_delta(Path(d), change=ac)
        assert "newsub" in delta.affected_subsystems
        assert any(n.node_type == "subsystem" and n.node_id == "newsub"
                   for n in delta.added_nodes)

    def test_subsystem_remove_populates_affected(self):
        system = {"subsystems": [{"name": "core", "components": []}]}
        with tempfile.TemporaryDirectory() as d:
            arch_dir = Path(d) / ".codegraph" / "architecture"
            arch_dir.mkdir(parents=True, exist_ok=True)
            (arch_dir / "system.json").write_text(json.dumps(system), encoding="utf-8")
            ac = ArchitectureChange(operations=[
                ArchitectureOperation(OpType.REMOVE_SUBSYSTEM, subsystem="core")])
            delta = generate_architecture_delta(Path(d), change=ac)
        assert "core" in delta.affected_subsystems
        assert any(n.node_type == "subsystem" and n.node_id == "core"
                   for n in delta.removed_nodes)


class TestComponentAffectsSubsystem:
    def test_added_component_affects_its_subsystem(self):
        # component_subsystem is not yet in system.json -> must still appear
        # in affected_subsystems (derived from the node's subsystem field).
        ac = ArchitectureChange(operations=[
            ArchitectureOperation(OpType.ADD_COMPONENT, component="new.py",
                                  component_subsystem="api")])
        with tempfile.TemporaryDirectory() as d:
            delta = generate_architecture_delta(Path(d), change=ac)
        assert "api" in delta.affected_subsystems
        assert delta.added_nodes[0].subsystem == "api"

    def test_removed_component_affects_its_subsystem(self):
        system = {"subsystems": [{"name": "api",
                                  "components": [{"name": "n", "module": "new.py"}]}]}
        with tempfile.TemporaryDirectory() as d:
            arch_dir = Path(d) / ".codegraph" / "architecture"
            arch_dir.mkdir(parents=True, exist_ok=True)
            (arch_dir / "system.json").write_text(json.dumps(system), encoding="utf-8")
            ac = ArchitectureChange(operations=[
                ArchitectureOperation(OpType.REMOVE_COMPONENT, component="new.py",
                                      component_subsystem="api")])
            delta = generate_architecture_delta(Path(d), change=ac)
        assert "api" in delta.affected_subsystems


class TestTargetPathPreservesMetadata:
    def test_target_node_subsystem_and_intent_survive(self):
        # The canonical delta must not silently drop TargetWorkflow metadata.
        target = TargetWorkflow()
        target.add_node("new.py", module="new.py", subsystem="api", intent="wire routes")
        target.add_edge("a::f", "b::g", reason="needed", priority=3)
        delta = compute_architecture_delta(target, {"edges": []}, set())
        n = delta.added_nodes[0]
        assert n.subsystem == "api"
        assert n.intent == "wire routes"
        e = delta.added_edges[0]
        assert e.priority == 3
        assert e.reason == "needed"
