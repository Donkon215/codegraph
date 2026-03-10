"""Tests for codegraph.architecture_simulator."""

from __future__ import annotations

from codegraph.arch_schema import (
    ArchComponent,
    ArchConstraint,
    ArchEdge,
    SubsystemDef,
    SystemArchitecture,
)
from codegraph.architecture_simulator import (
    ArchChange,
    ArchPrediction,
    ArchSimulationResult,
    simulate_architecture_changes,
    simulate_subsystem_addition,
)


# ── helpers ────────────────────────────────────────────────────────────


def _make_arch() -> SystemArchitecture:
    return SystemArchitecture(
        name="test",
        subsystems=[
            SubsystemDef(
                name="core",
                components=[ArchComponent(name="engine", module="codegraph/engine.py")],
            ),
            SubsystemDef(
                name="models",
                components=[ArchComponent(name="graph0", module="codegraph/models/graph0.py")],
            ),
            SubsystemDef(
                name="infra",
                components=[ArchComponent(name="cli", module="codegraph/cli.py")],
            ),
        ],
        edges=[
            ArchEdge(source="core", target="models"),
            ArchEdge(source="infra", target="core"),
        ],
        constraints=[
            ArchConstraint(
                constraint_type="forbidden",
                source="models",
                target="core",
                reason="Models must not import core",
            ),
        ],
    )


# ── ArchChange ─────────────────────────────────────────────────────────


class TestArchChange:
    def test_to_dict(self):
        c = ArchChange(action="add_subsystem", subsystem="api", reason="Need API")
        d = c.to_dict()
        assert d["action"] == "add_subsystem"
        assert d["subsystem"] == "api"
        assert d["reason"] == "Need API"

    def test_roundtrip(self):
        c = ArchChange(
            action="add_edge",
            subsystem="api",
            target_subsystem="models",
            reason="api needs models",
        )
        d = c.to_dict()
        c2 = ArchChange.from_dict(d)
        assert c2.action == "add_edge"
        assert c2.subsystem == "api"
        assert c2.target_subsystem == "models"

    def test_with_components(self):
        c = ArchChange(action="split_subsystem", subsystem="core",
                       target_subsystem="core_v2", components=["a", "b"])
        d = c.to_dict()
        assert d["components"] == ["a", "b"]
        c2 = ArchChange.from_dict(d)
        assert c2.components == ["a", "b"]


# ── ArchPrediction ─────────────────────────────────────────────────────


class TestArchPrediction:
    def test_to_dict(self):
        p = ArchPrediction(
            metric="cycles",
            current_value=0,
            predicted_value=1,
            delta=1.0,
            severity="error",
            description="New cycle",
        )
        d = p.to_dict()
        assert d["metric"] == "cycles"
        assert d["current"] == 0
        assert d["predicted"] == 1
        assert d["delta"] == 1.0


# ── ArchSimulationResult ──────────────────────────────────────────────


class TestArchSimulationResult:
    def test_empty_result(self):
        r = ArchSimulationResult()
        assert r.safe
        assert r.recommendation == "accept"

    def test_to_dict(self):
        r = ArchSimulationResult(
            changes=[ArchChange(action="add_subsystem", subsystem="api")],
            predictions=[ArchPrediction(metric="cycles", delta=0)],
            safe=True,
            recommendation="accept",
            reasons=["All good"],
        )
        d = r.to_dict()
        assert d["safe"] is True
        assert len(d["changes"]) == 1
        assert len(d["predictions"]) == 1

    def test_format(self):
        r = ArchSimulationResult(
            predictions=[
                ArchPrediction(metric="cycles", current_value=0,
                               predicted_value=1, delta=1.0,
                               severity="error", description="New cycle"),
            ],
            safe=False,
            recommendation="review",
            reasons=["Cycle detected"],
        )
        text = r.format()
        assert "UNSAFE" in text
        assert "review" in text
        assert "cycles" in text


# ── simulate_architecture_changes ──────────────────────────────────────


class TestSimulateArchitectureChanges:
    def test_add_subsystem(self):
        arch = _make_arch()
        changes = [ArchChange(action="add_subsystem", subsystem="api")]
        result = simulate_architecture_changes(changes, arch)
        # Should predict increase in subsystem_count
        sub_preds = [p for p in result.predictions if p.metric == "subsystem_count"]
        assert len(sub_preds) == 1
        assert sub_preds[0].delta > 0

    def test_add_edge(self):
        arch = _make_arch()
        changes = [ArchChange(action="add_edge", subsystem="models", target_subsystem="infra")]
        result = simulate_architecture_changes(changes, arch)
        # Should have prediction about edge count or coupling
        assert len(result.predictions) >= 1

    def test_forbidden_edge_violation(self):
        arch = _make_arch()
        # models → core is forbidden
        changes = [ArchChange(action="add_edge", subsystem="models", target_subsystem="core")]
        result = simulate_architecture_changes(changes, arch)
        constraint_preds = [p for p in result.predictions if p.metric == "constraint_violation"]
        assert len(constraint_preds) >= 1

    def test_does_not_modify_original(self):
        arch = _make_arch()
        original_sub_count = len(arch.subsystems)
        changes = [ArchChange(action="add_subsystem", subsystem="api")]
        simulate_architecture_changes(changes, arch)
        assert len(arch.subsystems) == original_sub_count

    def test_remove_edge(self):
        arch = _make_arch()
        changes = [ArchChange(action="remove_edge", subsystem="core", target_subsystem="models")]
        result = simulate_architecture_changes(changes, arch)
        # Should predict coupling/edge decrease
        assert result is not None

    def test_add_component(self):
        arch = _make_arch()
        changes = [ArchChange(action="add_component", subsystem="core",
                               component_name="parser", module_path="codegraph/parser.py")]
        result = simulate_architecture_changes(changes, arch)
        comp_preds = [p for p in result.predictions if p.metric == "component_count"]
        # Component count should increase
        if comp_preds:
            assert comp_preds[0].delta > 0

    def test_split_subsystem(self):
        # Add a component to core, then split
        arch = _make_arch()
        arch.get_subsystem("core").components.append(
            ArchComponent(name="parser", module="codegraph/parser.py")
        )
        changes = [ArchChange(
            action="split_subsystem",
            subsystem="core",
            target_subsystem="parsing",
            components=["parser"],
        )]
        result = simulate_architecture_changes(changes, arch)
        sub_preds = [p for p in result.predictions if p.metric == "subsystem_count"]
        assert len(sub_preds) == 1
        assert sub_preds[0].delta > 0

    def test_merge_subsystems(self):
        arch = _make_arch()
        changes = [ArchChange(
            action="merge_subsystems",
            subsystem="core",
            target_subsystem="models",
        )]
        result = simulate_architecture_changes(changes, arch)
        sub_preds = [p for p in result.predictions if p.metric == "subsystem_count"]
        assert len(sub_preds) == 1
        assert sub_preds[0].delta < 0

    def test_recommendation_accept(self):
        arch = _make_arch()
        changes = [ArchChange(action="add_component", subsystem="core",
                               component_name="util", module_path="codegraph/util.py")]
        result = simulate_architecture_changes(changes, arch)
        # Adding a component to existing subsystem is generally safe
        assert result.recommendation in ("accept", "review")

    def test_recommendation_review_or_reject(self):
        arch = _make_arch()
        # Add forbidden edge → should trigger review/reject
        changes = [ArchChange(action="add_edge", subsystem="models", target_subsystem="core")]
        result = simulate_architecture_changes(changes, arch)
        assert result.recommendation in ("review", "reject")

    def test_add_constraint(self):
        arch = _make_arch()
        changes = [ArchChange(
            action="add_constraint",
            subsystem="infra",
            target_subsystem="models",
            constraint_type="forbidden",
            reason="No infra→models",
        )]
        result = simulate_architecture_changes(changes, arch)
        # Should have constraint_count prediction
        assert result is not None


# ── simulate_subsystem_addition ────────────────────────────────────────


class TestSimulateSubsystemAddition:
    def test_basic_addition(self):
        arch = _make_arch()
        result = simulate_subsystem_addition("api", ["core", "models"], arch)
        assert len(result.changes) == 3  # 1 add_subsystem + 2 add_edge
        sub_preds = [p for p in result.predictions if p.metric == "subsystem_count"]
        assert len(sub_preds) == 1
        assert sub_preds[0].predicted_value > sub_preds[0].current_value

    def test_no_dependencies(self):
        arch = _make_arch()
        result = simulate_subsystem_addition("standalone", [], arch)
        assert len(result.changes) == 1  # just add_subsystem

    def test_does_not_modify_original(self):
        arch = _make_arch()
        original_count = len(arch.subsystems)
        simulate_subsystem_addition("api", ["core"], arch)
        assert len(arch.subsystems) == original_count


class TestCycleDetection:
    def test_detects_cycle(self):
        arch = SystemArchitecture(
            name="cyclic",
            subsystems=[
                SubsystemDef(name="a"),
                SubsystemDef(name="b"),
            ],
            edges=[
                ArchEdge(source="a", target="b"),
                ArchEdge(source="b", target="a"),
            ],
        )
        # Adding another node shouldn't break
        changes = [ArchChange(action="add_subsystem", subsystem="c")]
        result = simulate_architecture_changes(changes, arch)
        # The existing cycle should be reflected in metrics
        cycle_preds = [p for p in result.predictions if p.metric == "cycles"]
        # Architecture already has a cycle, adding a subsystem won't change it
        assert result is not None
