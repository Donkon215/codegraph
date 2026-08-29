"""Tests for codegraph.code_planner."""

from __future__ import annotations

from pathlib import Path

from codegraph.arch_schema import (
    ArchComponent,
    ArchConstraint,
    ArchEdge,
    SubsystemDef,
    SystemArchitecture,
)
from codegraph.code_planner import (
    CodePlan,
    PlanTask,
    generate_plan,
    validate_plan,
)
from codegraph.architecture_delta import ArchitectureDelta, EdgeChange, NodeChange


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
        ],
        edges=[ArchEdge(source="core", target="models")],
        constraints=[
            ArchConstraint(
                constraint_type="forbidden",
                source="models",
                target="core",
                reason="Models must not import core",
            ),
        ],
    )


# ── PlanTask ───────────────────────────────────────────────────────────


class TestPlanTask:
    def test_to_dict_minimal(self):
        t = PlanTask(task_type="create_file", target="foo.py")
        d = t.to_dict()
        assert d["task_type"] == "create_file"
        assert d["target"] == "foo.py"
        assert "depends_on" not in d  # empty list omitted

    def test_roundtrip(self):
        t = PlanTask(
            task_type="add_import",
            target="foo.py::bar",
            description="add import",
            subsystem="core",
            depends_on=["t001"],
            priority=2,
            task_id="t002",
        )
        d = t.to_dict()
        t2 = PlanTask.from_dict(d)
        assert t2.task_type == "add_import"
        assert t2.depends_on == ["t001"]
        assert t2.priority == 2
        assert t2.task_id == "t002"


# ── CodePlan ───────────────────────────────────────────────────────────


class TestCodePlan:
    def test_task_count(self):
        plan = CodePlan(tasks=[
            PlanTask(task_type="create_file", target="a.py"),
            PlanTask(task_type="add_test", target="test_a.py"),
        ])
        assert plan.task_count == 2

    def test_tasks_by_type(self):
        plan = CodePlan(tasks=[
            PlanTask(task_type="create_file", target="a.py"),
            PlanTask(task_type="create_file", target="b.py"),
            PlanTask(task_type="add_test", target="test_a.py"),
        ])
        by_type = plan.tasks_by_type
        assert by_type["create_file"] == 2
        assert by_type["add_test"] == 1

    def test_save_load(self, tmp_path: Path):
        plan = CodePlan(
            description="test plan",
            tasks=[PlanTask(task_type="create_file", target="a.py", task_id="t001")],
        )
        plan.save(tmp_path)
        loaded = CodePlan.load(tmp_path)
        assert loaded is not None
        assert loaded.description == "test plan"
        assert len(loaded.tasks) == 1

    def test_load_missing(self, tmp_path: Path):
        assert CodePlan.load(tmp_path) is None

    def test_format_output(self):
        plan = CodePlan(
            description="my plan",
            tasks=[
                PlanTask(task_type="create_file", target="a.py", description="Create A", task_id="t001"),
                PlanTask(task_type="add_test", target="test_a.py", description="Test A",
                         task_id="t002", depends_on=["t001"]),
            ],
            warnings=["Check something"],
        )
        text = plan.format()
        assert "my plan" in text
        assert "create_file" in text
        assert "Check something" in text

    def test_ordered_tasks_by_priority(self):
        plan = CodePlan(tasks=[
            PlanTask(task_type="add_test", target="test.py", priority=4, task_id="t002"),
            PlanTask(task_type="create_file", target="a.py", priority=1, task_id="t001"),
        ])
        ordered = plan.ordered_tasks()
        assert ordered[0].task_id == "t001"
        assert ordered[1].task_id == "t002"

    def test_ordered_tasks_by_dependency(self):
        plan = CodePlan(tasks=[
            PlanTask(task_type="add_import", target="b.py", priority=3,
                     task_id="t002", depends_on=["t001"]),
            PlanTask(task_type="create_file", target="a.py", priority=3, task_id="t001"),
        ])
        ordered = plan.ordered_tasks()
        ids = [t.task_id for t in ordered]
        assert ids.index("t001") < ids.index("t002")


# ── generate_plan ──────────────────────────────────────────────────────


class TestGeneratePlan:
    def test_missing_nodes(self):
        delta = ArchitectureDelta(
            added_nodes=[
                NodeChange("api/server.py::serve", module="api/server.py", subsystem="api"),
            ],
        )
        arch = _make_arch()
        plan = generate_plan(delta, arch)
        types = [t.task_type for t in plan.tasks]
        assert "create_file" in types
        assert "create_function" in types
        assert "add_test" in types

    def test_missing_edges(self):
        delta = ArchitectureDelta(
            added_edges=[
                EdgeChange("codegraph/engine.py::run", "codegraph/models/graph0.py::build"),
            ],
        )
        arch = _make_arch()
        plan = generate_plan(delta, arch)
        types = [t.task_type for t in plan.tasks]
        assert "add_import" in types

    def test_extra_edges(self):
        delta = ArchitectureDelta(
            removed_edges=[
                EdgeChange("codegraph/engine.py::run", "codegraph/old.py::legacy"),
            ],
        )
        arch = _make_arch()
        plan = generate_plan(delta, arch)
        types = [t.task_type for t in plan.tasks]
        assert "modify_file" in types

    def test_architecture_update_task(self):
        delta = ArchitectureDelta(
            added_nodes=[
                NodeChange("api/server.py::serve", module="api/server.py", subsystem="api"),
            ],
        )
        arch = _make_arch()
        plan = generate_plan(delta, arch)
        types = [t.task_type for t in plan.tasks]
        assert "update_architecture" in types

    def test_empty_delta(self):
        delta = ArchitectureDelta()
        arch = _make_arch()
        plan = generate_plan(delta, arch)
        assert plan.task_count == 0

    def test_task_ids_generated(self):
        delta = ArchitectureDelta(
            added_nodes=[
                NodeChange("a.py::foo", module="a.py", subsystem="core"),
            ],
        )
        arch = _make_arch()
        plan = generate_plan(delta, arch)
        for t in plan.tasks:
            assert t.task_id.startswith("t")


# ── validate_plan ──────────────────────────────────────────────────────


class TestValidatePlan:
    def test_valid_plan(self):
        plan = CodePlan(tasks=[
            PlanTask(task_type="create_file", target="a.py", subsystem="core", task_id="t001"),
        ])
        arch = _make_arch()
        violations = validate_plan(plan, arch)
        assert len(violations) == 0

    def test_forbidden_import_detected(self):
        plan = CodePlan(tasks=[
            PlanTask(
                task_type="add_import",
                target="codegraph/models/graph0.py",
                description="Connect models → core engine",
                subsystem="models",
                task_id="t001",
            ),
        ])
        arch = _make_arch()
        violations = validate_plan(plan, arch)
        assert len(violations) >= 1
        assert "forbidden" in violations[0].lower()
