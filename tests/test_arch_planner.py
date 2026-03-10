"""Tests for codegraph.arch_planner — architecture decomposition engine."""

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from codegraph.arch_planner import (
    ArchPlan,
    CoverageResult,
    PlannedTask,
    plan_architecture,
    plan_to_agent_response,
)
from codegraph.arch_schema import (
    ArchComponent,
    ArchConstraint,
    ArchEdge,
    SubsystemDef,
    SystemArchitecture,
)
from codegraph.models.graph0 import Graph0, Graph0Node


def _make_graph0(nodes_data):
    """Create a Graph0 with given nodes [(id, file, type)]."""
    nodes = [
        Graph0Node(id=n[0], body_hash="h", file=n[1], type=n[2], line=1)
        for n in nodes_data
    ]
    return Graph0(nodes=nodes)


def _make_index(callees=None):
    """Create a mock IndexStore with callees data."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE callees (node_id TEXT, callee_id TEXT)")
    conn.execute("CREATE TABLE nodes (node_id TEXT, id TEXT, file TEXT, type TEXT)")
    if callees:
        conn.executemany("INSERT INTO callees VALUES (?, ?)", callees)
    mock = MagicMock()
    mock._get_conn.return_value = conn
    return mock


class TestPlannedTask:
    def test_to_dict_minimal(self):
        t = PlannedTask(task_type="create_module", module="auth/service.py")
        d = t.to_dict()
        assert d["task_type"] == "create_module"
        assert d["module"] == "auth/service.py"

    def test_to_dict_full(self):
        t = PlannedTask(
            task_type="connect_call",
            subsystem="auth",
            source="auth::login",
            target="auth::validate",
            reason="Required by architecture",
            priority=2,
        )
        d = t.to_dict()
        assert d["task_type"] == "connect_call"
        assert d["subsystem"] == "auth"
        assert d["priority"] == 2

    def test_from_dict(self):
        d = {"task_type": "create_function", "module": "x.py", "function": "foo"}
        t = PlannedTask.from_dict(d)
        assert t.task_type == "create_function"
        assert t.function == "foo"


class TestCoverageResult:
    def test_empty_is_100_percent(self):
        c = CoverageResult()
        assert c.overall_coverage == 1.0

    def test_partial_coverage(self):
        c = CoverageResult(total_modules=4, existing_modules=2)
        assert c.module_coverage == 0.5

    def test_overall_average(self):
        c = CoverageResult(
            total_modules=2, existing_modules=1,
            total_functions=4, existing_functions=2,
        )
        # module: 50%, function: 50%, edge: 100% (0/0)
        assert c.overall_coverage == 0.5

    def test_to_dict(self):
        c = CoverageResult(total_modules=3, existing_modules=2)
        d = c.to_dict()
        assert d["modules"]["total"] == 3
        assert d["modules"]["existing"] == 2
        assert d["modules"]["coverage"] == pytest.approx(0.667, abs=0.01)


class TestArchPlan:
    def test_empty_plan(self):
        p = ArchPlan()
        d = p.to_dict()
        assert d["task_count"] == 0
        assert d["missing_modules"] == []

    def test_format(self):
        p = ArchPlan(
            architecture_name="test",
            missing_modules=["auth/service.py"],
            tasks=[PlannedTask(task_type="create_module", module="auth/service.py")],
        )
        text = p.format()
        assert "test" in text
        assert "Missing modules" in text
        assert "create_module" in text


class TestPlanArchitecture:
    def test_all_existing(self):
        """Architecture where everything already exists."""
        graph0 = _make_graph0([
            ("core/main.py::main", "core/main.py", "function"),
            ("core/main.py", "core/main.py", "module"),
        ])
        arch = SystemArchitecture(
            name="test",
            subsystems=[
                SubsystemDef(
                    name="core",
                    components=[ArchComponent(name="main", module="core/main.py")],
                ),
            ],
        )
        index = _make_index()
        plan = plan_architecture(arch, graph0, index)
        assert plan.coverage.existing_modules == 1
        assert len(plan.missing_modules) == 0

    def test_missing_module(self):
        """Architecture with a module that doesn't exist in code."""
        graph0 = _make_graph0([
            ("core/main.py::main", "core/main.py", "function"),
            ("core/main.py", "core/main.py", "module"),
        ])
        arch = SystemArchitecture(
            name="test",
            subsystems=[
                SubsystemDef(
                    name="core",
                    components=[
                        ArchComponent(name="main", module="core/main.py"),
                        ArchComponent(name="auth", module="core/auth.py"),
                    ],
                ),
            ],
        )
        index = _make_index()
        plan = plan_architecture(arch, graph0, index)
        assert len(plan.missing_modules) == 1
        assert "core/auth.py" in plan.missing_modules
        assert any(t.task_type == "create_module" for t in plan.tasks)

    def test_missing_function(self):
        """Architecture with a function that doesn't exist."""
        graph0 = _make_graph0([
            ("core/main.py", "core/main.py", "module"),
            ("core/main.py::main", "core/main.py", "function"),
        ])
        arch = SystemArchitecture(
            name="test",
            subsystems=[
                SubsystemDef(
                    name="core",
                    components=[
                        ArchComponent(
                            name="main",
                            module="core/main.py",
                            functions=["main", "init"],
                        ),
                    ],
                ),
            ],
        )
        index = _make_index()
        plan = plan_architecture(arch, graph0, index)
        assert plan.coverage.existing_functions == 1
        assert len(plan.missing_functions) == 1
        assert plan.missing_functions[0]["function"] == "init"

    def test_constraint_violation(self):
        """Architecture with a forbidden edge that exists in code."""
        graph0 = _make_graph0([
            ("ui/views.py::render", "ui/views.py", "function"),
            ("db/store.py::query", "db/store.py", "function"),
        ])
        arch = SystemArchitecture(
            name="test",
            subsystems=[
                SubsystemDef(
                    name="ui",
                    components=[ArchComponent(name="views", module="ui/views.py")],
                ),
                SubsystemDef(
                    name="db",
                    components=[ArchComponent(name="store", module="db/store.py")],
                ),
            ],
            constraints=[
                ArchConstraint("forbidden", "ui", "db", "No UI→DB"),
            ],
        )
        callees = [("ui/views.py::render", "db/store.py::query")]
        index = _make_index(callees=callees)
        plan = plan_architecture(arch, graph0, index)
        assert len(plan.constraint_violations) == 1
        assert any(t.task_type == "flag_violation" for t in plan.tasks)

    def test_missing_edge(self):
        """Architecture with an expected edge that doesn't exist."""
        graph0 = _make_graph0([
            ("core/main.py::main", "core/main.py", "function"),
            ("core/db.py::query", "core/db.py", "function"),
        ])
        arch = SystemArchitecture(
            name="test",
            subsystems=[
                SubsystemDef(
                    name="core",
                    components=[
                        ArchComponent(name="main_mod", module="core/main.py"),
                        ArchComponent(name="db_mod", module="core/db.py"),
                    ],
                    edges=[ArchEdge(source="main_mod", target="db_mod")],
                ),
            ],
        )
        index = _make_index()
        plan = plan_architecture(arch, graph0, index)
        assert len(plan.missing_connections) == 1
        assert any(t.task_type == "connect_call" for t in plan.tasks)

    def test_tasks_sorted_by_priority(self):
        """Tasks should be sorted by priority (lowest number first)."""
        graph0 = _make_graph0([
            ("ui/views.py::render", "ui/views.py", "function"),
            ("db/store.py::query", "db/store.py", "function"),
        ])
        arch = SystemArchitecture(
            name="test",
            subsystems=[
                SubsystemDef(
                    name="ui",
                    components=[ArchComponent(name="views", module="ui/views.py")],
                ),
                SubsystemDef(
                    name="db",
                    components=[ArchComponent(name="store", module="db/store.py")],
                ),
            ],
            constraints=[
                ArchConstraint("forbidden", "ui", "db"),
            ],
        )
        callees = [("ui/views.py::render", "db/store.py::query")]
        index = _make_index(callees=callees)
        plan = plan_architecture(arch, graph0, index)
        if len(plan.tasks) > 1:
            for i in range(len(plan.tasks) - 1):
                assert plan.tasks[i].priority <= plan.tasks[i + 1].priority


class TestPlanToAgentResponse:
    def test_basic_conversion(self):
        plan = ArchPlan(
            architecture_name="test",
            tasks=[
                PlannedTask(
                    task_type="connect_call",
                    source="a.py::foo",
                    target="b.py::bar",
                    reason="Required",
                ),
                PlannedTask(
                    task_type="flag_violation",
                    source="ui.py::view",
                    target="db.py::query",
                    reason="Forbidden",
                ),
                PlannedTask(
                    task_type="create_module",
                    module="new.py",
                    reason="Missing module",
                ),
            ],
        )
        response = plan_to_agent_response(plan, graph_version=5)
        assert response["graph_version"] == 5
        assert len(response["repairs"]) == 3
        assert response["repairs"][0]["action"] == "connect_call"
        assert response["repairs"][1]["action"] == "flag_for_human_review"
        assert response["repairs"][2]["action"] == "flag_for_human_review"
