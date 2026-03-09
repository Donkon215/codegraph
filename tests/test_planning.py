"""Tests for codegraph.planning — agent planning layer."""

import pytest

from codegraph.planning import (
    PlanStep,
    RepairPlan,
    generate_plan,
    validate_plan,
    save_plan,
    load_plan,
)


class TestPlanStep:
    def test_to_dict(self):
        step = PlanStep(step_id=1, action="add_intent", node_id="a::f")
        d = step.to_dict()
        assert d["step_id"] == 1
        assert d["action"] == "add_intent"

    def test_to_dict_with_target(self):
        step = PlanStep(step_id=1, action="connect_call", node_id="a::f", target="b::g")
        d = step.to_dict()
        assert d["target"] == "b::g"


class TestRepairPlan:
    def test_empty_plan(self):
        plan = RepairPlan(plan_id="test", graph_version=1)
        d = plan.to_dict()
        assert d["summary"]["total_steps"] == 0

    def test_format(self):
        plan = RepairPlan(plan_id="test", graph_version=1, cycle=1)
        plan.steps.append(PlanStep(step_id=1, action="add_intent", node_id="x::y"))
        text = plan.format()
        assert "test" in text
        assert "add_intent" in text

    def test_to_json(self):
        plan = RepairPlan(plan_id="test", graph_version=5)
        j = plan.to_json()
        assert '"plan_id": "test"' in j
        assert '"graph_version": 5' in j


class TestGeneratePlan:
    def test_empty_tasks(self):
        plan = generate_plan({"tasks": []}, graph_version=1)
        assert len(plan.steps) == 0

    def test_intent_missing_tasks(self):
        tasks_data = {
            "tasks": [{
                "task_id": "intent_missing",
                "priority": 10,
                "nodes": ["a::f1", "a::f2"],
            }],
        }
        plan = generate_plan(tasks_data, graph_version=3, cycle=2)
        assert plan.total_intents == 2
        assert len(plan.steps) == 2
        assert plan.steps[0].action == "add_intent"
        assert plan.graph_version == 3
        assert plan.cycle == 2

    def test_orphan_tasks(self):
        tasks_data = {
            "tasks": [{
                "task_id": "orphan_nodes",
                "priority": 3,
                "nodes": ["dead::func"],
            }],
        }
        plan = generate_plan(tasks_data, graph_version=1)
        assert plan.total_flags == 1
        assert plan.steps[0].action == "flag_orphan"

    def test_policy_violation_tasks(self):
        tasks_data = {
            "tasks": [{
                "task_id": "policy_violation",
                "priority": 1,
                "nodes": ["a::source"],
                "details": {"target": "b::target"},
            }],
        }
        plan = generate_plan(tasks_data, graph_version=1)
        assert plan.total_repairs == 1
        assert plan.steps[0].action == "connect_call"

    def test_mixed_tasks_sorted_by_priority(self):
        tasks_data = {
            "tasks": [
                {"task_id": "intent_missing", "priority": 10, "nodes": ["x"]},
                {"task_id": "policy_violation", "priority": 1, "nodes": ["y"], "details": {"target": "z"}},
                {"task_id": "orphan_nodes", "priority": 3, "nodes": ["w"]},
            ],
        }
        plan = generate_plan(tasks_data, graph_version=1)
        # Policy violation (P1) should come first
        assert plan.steps[0].action == "connect_call"
        assert plan.steps[1].action == "flag_orphan"
        assert plan.steps[2].action == "add_intent"


class TestValidatePlan:
    def test_valid_plan(self):
        plan = RepairPlan(plan_id="test", graph_version=1)
        plan.steps.append(PlanStep(step_id=1, action="add_intent", node_id="x"))
        issues = validate_plan(plan)
        assert len(issues) == 0

    def test_duplicate_step_ids(self):
        plan = RepairPlan(plan_id="test", graph_version=1)
        plan.steps.append(PlanStep(step_id=1, action="add_intent", node_id="x"))
        plan.steps.append(PlanStep(step_id=1, action="add_intent", node_id="y"))
        issues = validate_plan(plan)
        assert any("Duplicate" in i for i in issues)

    def test_missing_graph_version(self):
        plan = RepairPlan(plan_id="test", graph_version=0)
        issues = validate_plan(plan)
        assert any("graph_version" in i for i in issues)

    def test_invalid_dependency(self):
        plan = RepairPlan(plan_id="test", graph_version=1)
        plan.steps.append(PlanStep(step_id=1, action="x", node_id="a", depends_on=[99]))
        issues = validate_plan(plan)
        assert any("non-existent" in i for i in issues)


class TestSaveLoadPlan:
    def test_round_trip(self, tmp_path):
        plan = RepairPlan(plan_id="test_plan", graph_version=5, cycle=2)
        plan.steps.append(PlanStep(step_id=1, action="add_intent", node_id="a::f"))
        plan.total_intents = 1

        save_plan(plan, tmp_path)
        loaded = load_plan(tmp_path, "test_plan")

        assert loaded is not None
        assert loaded.plan_id == "test_plan"
        assert loaded.graph_version == 5
        assert len(loaded.steps) == 1
        assert loaded.steps[0].action == "add_intent"

    def test_load_nonexistent(self, tmp_path):
        result = load_plan(tmp_path, "nonexistent")
        assert result is None
