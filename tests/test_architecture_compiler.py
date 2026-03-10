"""Tests for codegraph.architecture_compiler."""

from __future__ import annotations

from pathlib import Path

from codegraph.arch_schema import (
    ArchComponent,
    ArchConstraint,
    ArchEdge,
    SubsystemDef,
    SystemArchitecture,
)
from codegraph.architecture_compiler import (
    ArchitecturePlan,
    CompiledChange,
    apply_plan,
    compile_intent,
    plan_to_target_workflow,
)
from codegraph.target_architecture import TargetEdge, TargetNode, TargetWorkflow


# ── helpers ────────────────────────────────────────────────────────────


def _make_arch() -> SystemArchitecture:
    return SystemArchitecture(
        name="test",
        subsystems=[
            SubsystemDef(
                name="core_engine",
                components=[ArchComponent(name="extractor", module="codegraph/extractor.py")],
            ),
            SubsystemDef(
                name="models",
                components=[ArchComponent(name="graph0", module="codegraph/models/graph0.py")],
            ),
            SubsystemDef(
                name="infrastructure",
                components=[ArchComponent(name="cli", module="codegraph/cli.py")],
            ),
        ],
        edges=[
            ArchEdge(source="core_engine", target="models"),
            ArchEdge(source="infrastructure", target="core_engine"),
        ],
        constraints=[
            ArchConstraint(
                constraint_type="forbidden",
                source="models",
                target="core_engine",
                reason="Models must not import engine",
            ),
        ],
    )


# ── CompiledChange ─────────────────────────────────────────────────────


class TestCompiledChange:
    def test_to_dict_minimal(self):
        c = CompiledChange(change_type="add_subsystem", subsystem="api")
        d = c.to_dict()
        assert d["change_type"] == "add_subsystem"
        assert d["subsystem"] == "api"
        assert "target_subsystem" not in d  # empty fields omitted

    def test_roundtrip(self):
        c = CompiledChange(
            change_type="add_edge",
            subsystem="api",
            target_subsystem="models",
            reason="api needs models",
        )
        d = c.to_dict()
        c2 = CompiledChange.from_dict(d)
        assert c2.change_type == "add_edge"
        assert c2.subsystem == "api"
        assert c2.target_subsystem == "models"
        assert c2.reason == "api needs models"


# ── ArchitecturePlan ───────────────────────────────────────────────────


class TestArchitecturePlan:
    def test_has_changes_empty(self):
        plan = ArchitecturePlan(intent="test")
        assert not plan.has_changes

    def test_has_changes_with_change(self):
        plan = ArchitecturePlan(
            intent="add api",
            changes=[CompiledChange(change_type="add_subsystem", subsystem="api")],
        )
        assert plan.has_changes

    def test_roundtrip(self):
        plan = ArchitecturePlan(
            intent="add api",
            changes=[CompiledChange(change_type="add_subsystem", subsystem="api")],
            target_nodes=[TargetNode(node_id="api.server", module="api/server.py")],
            warnings=["something"],
        )
        d = plan.to_dict()
        plan2 = ArchitecturePlan.from_dict(d)
        assert plan2.intent == "add api"
        assert len(plan2.changes) == 1
        assert len(plan2.target_nodes) == 1
        assert plan2.warnings == ["something"]

    def test_save_load(self, tmp_path: Path):
        plan = ArchitecturePlan(
            intent="add cache",
            changes=[CompiledChange(change_type="add_subsystem", subsystem="cache")],
        )
        plan.save(tmp_path)
        loaded = ArchitecturePlan.load(tmp_path)
        assert loaded is not None
        assert loaded.intent == "add cache"

    def test_load_missing(self, tmp_path: Path):
        assert ArchitecturePlan.load(tmp_path) is None

    def test_format_output(self):
        plan = ArchitecturePlan(
            intent="add api",
            changes=[CompiledChange(change_type="add_subsystem", subsystem="api", reason="Need API")],
            warnings=["Check ports"],
        )
        text = plan.format()
        assert "add api" in text
        assert "add_subsystem" in text
        assert "Check ports" in text


# ── compile_intent ─────────────────────────────────────────────────────


class TestCompileIntent:
    def test_known_pattern_api(self):
        arch = _make_arch()
        plan = compile_intent("add REST API", arch)
        assert plan.has_changes
        types = [c.change_type for c in plan.changes]
        assert "add_subsystem" in types
        # Should have api subsystem
        subs = [c.subsystem for c in plan.changes if c.change_type == "add_subsystem"]
        assert "api" in subs

    def test_known_pattern_cache(self):
        arch = _make_arch()
        plan = compile_intent("add cache layer", arch)
        assert plan.has_changes
        # cache pattern maps to infrastructure, which already exists
        # so it should add components, not a new subsystem
        comp_changes = [c for c in plan.changes if c.change_type == "add_component"]
        assert len(comp_changes) >= 1

    def test_generic_intent(self):
        arch = _make_arch()
        plan = compile_intent("add reporting service", arch)
        assert plan.has_changes
        subs = [c.subsystem for c in plan.changes if c.change_type == "add_subsystem"]
        assert "reporting" in subs

    def test_unrecognized_intent(self):
        arch = _make_arch()
        plan = compile_intent("do something", arch)
        # should have a warning
        assert plan.warnings

    def test_auto_constraints_default(self):
        arch = _make_arch()
        plan = compile_intent("add REST API", arch)
        constraint_changes = [c for c in plan.changes if c.change_type == "add_constraint"]
        # Should have forbidden constraints from models and infrastructure
        assert len(constraint_changes) >= 1

    def test_auto_constraints_disabled(self):
        arch = _make_arch()
        plan = compile_intent("add REST API", arch, auto_constraints=False)
        constraint_changes = [c for c in plan.changes if c.change_type == "add_constraint"]
        assert len(constraint_changes) == 0

    def test_existing_subsystem_no_duplicate(self):
        arch = _make_arch()
        plan = compile_intent("add database support", arch)
        # database pattern maps to infrastructure, which exists
        sub_changes = [c for c in plan.changes if c.change_type == "add_subsystem"]
        infra_subs = [c for c in sub_changes if c.subsystem == "infrastructure"]
        assert len(infra_subs) == 0  # don't add existing subsystem


# ── apply_plan ─────────────────────────────────────────────────────────


class TestApplyPlan:
    def test_add_subsystem(self):
        arch = _make_arch()
        plan = ArchitecturePlan(
            intent="add api",
            changes=[
                CompiledChange(change_type="add_subsystem", subsystem="api", description="API layer"),
            ],
        )
        result = apply_plan(plan, arch)
        assert result.get_subsystem("api") is not None

    def test_add_component(self):
        arch = _make_arch()
        plan = ArchitecturePlan(
            intent="add component",
            changes=[
                CompiledChange(
                    change_type="add_component",
                    subsystem="core_engine",
                    component_name="parser",
                    module_path="codegraph/parser.py",
                ),
            ],
        )
        apply_plan(plan, arch)
        sub = arch.get_subsystem("core_engine")
        assert "parser" in [c.name for c in sub.components]

    def test_add_edge(self):
        arch = _make_arch()
        plan = ArchitecturePlan(
            intent="connect",
            changes=[
                CompiledChange(change_type="add_edge", subsystem="models", target_subsystem="infrastructure"),
            ],
        )
        apply_plan(plan, arch)
        edge_pairs = [(e.source, e.target) for e in arch.edges]
        assert ("models", "infrastructure") in edge_pairs

    def test_add_constraint(self):
        arch = _make_arch()
        plan = ArchitecturePlan(
            intent="add constraint",
            changes=[
                CompiledChange(
                    change_type="add_constraint",
                    subsystem="infrastructure",
                    target_subsystem="models",
                    constraint_type="forbidden",
                    reason="No infra→models",
                ),
            ],
        )
        apply_plan(plan, arch)
        assert len(arch.constraints) == 2

    def test_no_duplicate_subsystem(self):
        arch = _make_arch()
        plan = ArchitecturePlan(
            intent="add core_engine",
            changes=[CompiledChange(change_type="add_subsystem", subsystem="core_engine")],
        )
        apply_plan(plan, arch)
        names = [s.name for s in arch.subsystems]
        assert names.count("core_engine") == 1

    def test_no_duplicate_edge(self):
        arch = _make_arch()
        plan = ArchitecturePlan(
            intent="add edge",
            changes=[CompiledChange(change_type="add_edge", subsystem="core_engine", target_subsystem="models")],
        )
        apply_plan(plan, arch)
        pairs = [(e.source, e.target) for e in arch.edges]
        assert pairs.count(("core_engine", "models")) == 1


# ── plan_to_target_workflow ────────────────────────────────────────────


class TestPlanToTargetWorkflow:
    def test_new_target(self):
        plan = ArchitecturePlan(
            intent="add api",
            target_edges=[TargetEdge(source="a", target="b")],
            target_nodes=[TargetNode(node_id="api.server", module="api/server.py")],
        )
        tw = plan_to_target_workflow(plan)
        assert len(tw.edges) == 1
        assert len(tw.nodes) == 1
        assert tw.description == "Target from intent: add api"

    def test_append_to_existing(self):
        existing = TargetWorkflow(description="existing")
        existing.edges.append(TargetEdge(source="x", target="y"))
        plan = ArchitecturePlan(
            intent="add api",
            target_edges=[TargetEdge(source="a", target="b")],
        )
        tw = plan_to_target_workflow(plan, existing_target=existing)
        assert len(tw.edges) == 2
        assert tw.description == "existing"
