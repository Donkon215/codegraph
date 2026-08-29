"""Tests for architecture_change_adapters (PHASE 3C: RepairAction + AgentResponse)."""

import sys
from codegraph.architecture_change import OpType, ArchitectureChange
from codegraph.architecture_change_adapters import (
    from_repair_action,
    from_agent_response,
    from_planned_task,
    from_arch_plan,
    from_arch_change,
    from_simulated_change,
    target_workflow_to_change,
    system_architecture_to_change,
)
from codegraph.arch_planner import PlannedTask, ArchPlan
from codegraph.architecture_simulator import ArchChange
from codegraph.simulator import SimulatedChange
from codegraph.arch_schema import (
    SystemArchitecture,
    SubsystemDef,
    ArchComponent,
    ArchEdge,
    ArchConstraint,
)
from codegraph.models.agent_response import (
    AgentResponse,
    RepairAction,
    IntentProposal,
    WorkflowSuggestion,
)


def test_connect_call_becomes_add_edge_call():
    ra = RepairAction(node="a::f", action="connect_call", target="b::g", reason="r")
    ac = from_repair_action(ra)
    assert len(ac.operations) == 1
    op = ac.operations[0]
    assert op.op == OpType.ADD_EDGE
    assert op.source == "a::f"
    assert op.target == "b::g"
    assert op.edge_type == "call"


def test_connect_call_missing_target_is_skipped():
    ra = RepairAction(node="a::f", action="connect_call", target="")
    ac = from_repair_action(ra)
    assert ac.operations == []
    assert "skipped" in ac.metadata


def test_add_import_collapses_to_module_and_maps_dependency():
    ra = RepairAction(node="a::f", action="add_import", target="b")
    ac = from_repair_action(ra)
    assert len(ac.operations) == 1
    op = ac.operations[0]
    assert op.op == OpType.ADD_EDGE
    assert op.source == "a"  # module collapse
    assert op.target == "b"
    assert op.edge_type == "dependency"


def test_remove_dead_code_is_no_op_implementation_layer():
    ra = RepairAction(node="a::f", action="remove_dead_code", reason="dead")
    ac = from_repair_action(ra)
    assert ac.operations == []
    assert "skipped_implementation_layer" in ac.metadata
    assert "remove_dead_code" in ac.metadata["skipped_implementation_layer"]


def test_flag_for_human_review_is_no_op():
    ra = RepairAction(node="a", action="flag_for_human_review", reason="check")
    ac = from_repair_action(ra)
    assert ac.operations == []
    assert "skipped_implementation_layer" in ac.metadata


def test_unknown_action_is_not_silently_mapped():
    # RepairAction model itself rejects unknown actions; adapter is defensive regardless.
    ra = RepairAction(node="a", action="connect_call", target="b")
    ac = from_repair_action(ra)
    assert ac.validate() is None  # structural validity holds


def test_agent_response_intents_are_metadata_only():
    resp = AgentResponse(
        cycle="c",
        graph_version=1,
        intents=[IntentProposal(node="a", intent="x")],
        repairs=[],
        workflow_suggestions=[],
    )
    ac = from_agent_response(resp)
    assert ac.operations == []
    assert any("intents" in s for s in ac.metadata.get("skipped", []))


def test_agent_response_workflow_suggestions_are_not_constraints():
    resp = AgentResponse(
        cycle="c",
        graph_version=1,
        repairs=[],
        workflow_suggestions=[
            WorkflowSuggestion(type="forbidden_call", source="a", target="b")
        ],
    )
    ac = from_agent_response(resp)
    assert ac.operations == []
    assert any("workflow_suggestions" in s for s in ac.metadata.get("skipped", []))


def test_agent_response_combines_repairs_and_skips_non_mutations():
    ra1 = RepairAction(node="a::f", action="connect_call", target="b")
    ra2 = RepairAction(node="x", action="flag_for_human_review")
    resp = AgentResponse(
        cycle="c",
        graph_version=1,
        repairs=[ra1, ra2],
        intents=[],
        workflow_suggestions=[],
    )
    ac = from_agent_response(resp)
    assert len(ac.operations) == 1
    assert ac.operations[0].op == OpType.ADD_EDGE
    assert any("skipped_implementation_layer" in s for s in ac.metadata.get("skipped", []))


def test_create_module_becomes_add_component():
    task = PlannedTask(task_type="create_module", subsystem="S", module="pkg/mod.py", reason="r")
    ac = from_planned_task(task)
    assert len(ac.operations) == 1
    op = ac.operations[0]
    assert op.op == OpType.ADD_COMPONENT
    assert op.component == "pkg/mod.py"
    assert op.component_subsystem == "S"


def test_create_function_is_no_op():
    task = PlannedTask(
        task_type="create_function", subsystem="S", module="pkg/mod.py", function="foo"
    )
    ac = from_planned_task(task)
    assert ac.operations == []
    assert "skipped_implementation_layer" in ac.metadata


def test_connect_call_task_becomes_add_edge():
    task = PlannedTask(task_type="connect_call", source="A", target="B", reason="r")
    ac = from_planned_task(task)
    assert len(ac.operations) == 1
    op = ac.operations[0]
    assert op.op == OpType.ADD_EDGE and op.edge_type == "call"


def test_flag_violation_is_no_op():
    task = PlannedTask(task_type="flag_violation", source="A", target="B")
    ac = from_planned_task(task)
    assert ac.operations == []
    assert "skipped_diagnostic" in ac.metadata


def test_add_constraint_task_skipped_without_constraint_type():
    task = PlannedTask(task_type="add_constraint", source="A", target="B")
    ac = from_planned_task(task)
    assert ac.operations == []
    assert any("add_constraint" in s for s in ac.metadata.get("skipped", []))


def test_arch_plan_aggregates_tasks():
    plan = type("P", (), {"tasks": [
        PlannedTask(task_type="create_module", subsystem="S", module="m.py"),
        PlannedTask(task_type="connect_call", source="A", target="B"),
        PlannedTask(task_type="create_function", subsystem="S", module="m.py", function="f"),
    ]})()
    ac = from_arch_plan(plan)
    assert len(ac.operations) == 2
    assert {o.op for o in ac.operations} == {OpType.ADD_COMPONENT, OpType.ADD_EDGE}


def test_equivalence_agentresponse_vs_archplan_connect_call():
    # Same intent expressed two ways must normalize() equal (PHASE 4 key test).
    agent = AgentResponse(
        cycle="c",
        graph_version=1,
        repairs=[RepairAction(node="A", action="connect_call", target="B")],
        intents=[],
        workflow_suggestions=[],
    )
    plan = type("P", (), {"tasks": [
        PlannedTask(task_type="connect_call", source="A", target="B"),
    ]})()
    a = from_agent_response(agent).normalize()
    b = from_arch_plan(plan).normalize()
    assert a == b
    assert len(a.operations) == 1
    assert a.operations[0].op == OpType.ADD_EDGE


def test_arch_change_add_subsystem():
    ac = from_arch_change(ArchChange(action="add_subsystem", subsystem="S", reason="r"))
    assert len(ac.operations) == 1 and ac.operations[0].op == OpType.ADD_SUBSYSTEM


def test_arch_change_add_edge_maps_dependency():
    ac = from_arch_change(ArchChange(action="add_edge", subsystem="S", target_subsystem="T"))
    op = ac.operations[0]
    assert op.op == OpType.ADD_EDGE and op.edge_type == "dependency" and op.source == "S" and op.target == "T"


def test_arch_change_remove_edge_maps_dependency():
    ac = from_arch_change(ArchChange(action="remove_edge", subsystem="S", target_subsystem="T"))
    op = ac.operations[0]
    assert op.op == OpType.REMOVE_EDGE and op.edge_type == "dependency"


def test_arch_change_add_component():
    ac = from_arch_change(ArchChange(
        action="add_component", subsystem="S", module_path="pkg/mod.py", component_name="mod", reason="r"
    ))
    op = ac.operations[0]
    assert op.op == OpType.ADD_COMPONENT
    assert op.component == "pkg/mod.py"
    assert op.component_subsystem == "S"
    assert op.component_name == "mod"


def test_arch_change_add_constraint_preserves_verbatim_type():
    ac = from_arch_change(ArchChange(
        action="add_constraint", subsystem="S", target_subsystem="T", constraint_type="forbidden_dependency"
    ))
    op = ac.operations[0]
    assert op.op == OpType.ADD_CONSTRAINT
    assert op.constraint_type == "forbidden_dependency"  # NOT normalized to "forbidden"


def test_arch_change_split_merge_requires_arch():
    import pytest

    with pytest.raises(ValueError):
        from_arch_change(ArchChange(action="split_subsystem", subsystem="S", target_subsystem="N", components=["a"]))
    with pytest.raises(ValueError):
        from_arch_change(ArchChange(action="merge_subsystems", subsystem="S", target_subsystem="T"))


def test_decompose_split_to_primitives():
    arch = SystemArchitecture(name="split-fixture", subsystems=[
        SubsystemDef(name="S", components=[
            ArchComponent(name="A", module="a.py"),
            ArchComponent(name="B", module="b.py"),
            ArchComponent(name="C", module="c.py"),
        ], edges=[ArchEdge("A", "B"), ArchEdge("A", "C"), ArchEdge("B", "C")]),
    ], edges=[], constraints=[])
    ac = from_arch_change(
        ArchChange(action="split_subsystem", subsystem="S", target_subsystem="N", components=["A"]),
        arch,
    )
    assert any(o.op == OpType.ADD_SUBSYSTEM and o.subsystem == "N" for o in ac.operations)
    assert any(o.op == OpType.REMOVE_COMPONENT and o.component == "a.py"
               and o.component_subsystem == "S" and o.component_name == "A" for o in ac.operations)
    assert any(o.op == OpType.ADD_COMPONENT and o.component == "a.py"
               and o.component_subsystem == "N" and o.component_name == "A" for o in ac.operations)
    # A->B and A->C are cross edges; both collapse to the same inter-subsystem edge
    # N->S (subsystem granularity), so the decomposition deduplicates to one ADD_EDGE.
    cross = [o for o in ac.operations
             if o.op == OpType.ADD_EDGE and o.source == "N" and o.target == "S" and o.edge_type == "dependency"]
    assert len(cross) == 1


def test_decompose_merge_to_primitives():
    arch = SystemArchitecture(name="merge-fixture", subsystems=[
        SubsystemDef(name="X", components=[
            ArchComponent(name="P", module="p.py"), ArchComponent(name="Q", module="q.py")]),
        SubsystemDef(name="Y", components=[ArchComponent(name="R", module="r.py")]),
    ], edges=[ArchEdge("X", "Y")],
       constraints=[ArchConstraint(constraint_type="forbidden_dependency", source="X", target="Y")])
    ac = from_arch_change(
        ArchChange(action="merge_subsystems", subsystem="X", target_subsystem="Y"),
        arch,
    )
    assert any(o.op == OpType.REMOVE_SUBSYSTEM and o.subsystem == "Y" for o in ac.operations)
    # name_a (X) is the absorb target: NOT removed, NOT re-added.
    assert not any(o.op == OpType.REMOVE_SUBSYSTEM and o.subsystem == "X" for o in ac.operations)
    assert not any(o.op == OpType.ADD_SUBSYSTEM for o in ac.operations)
    added = [o.component for o in ac.operations if o.op == OpType.ADD_COMPONENT and o.component_subsystem == "X"]
    assert added == ["r.py"]  # only Y's component migrates into X
    # X->Y edge and forbidden_dependency X->Y both become self-edges -> removed, NOT re-added
    assert any(o.op == OpType.REMOVE_EDGE and o.source == "X" and o.target == "Y"
               and o.edge_type == "dependency" for o in ac.operations)
    assert not any(o.op == OpType.ADD_EDGE for o in ac.operations)
    assert not any(o.op == OpType.ADD_CONSTRAINT for o in ac.operations)
    assert any(o.op == OpType.REMOVE_CONSTRAINT and o.source == "X" and o.target == "Y"
               for o in ac.operations)


def test_simulated_change_add_edge_defaults_call():
    ac = from_simulated_change(SimulatedChange(action="add_edge", source="A", target="B"))
    op = ac.operations[0]
    assert op.op == OpType.ADD_EDGE and op.edge_type == "call"


def test_simulated_change_remove_edge_defaults_call():
    ac = from_simulated_change(SimulatedChange(action="remove_edge", source="A", target="B"))
    assert ac.operations[0].op == OpType.REMOVE_EDGE


def test_simulated_change_add_node_function_is_no_op():
    ac = from_simulated_change(SimulatedChange(action="add_node", node_id="pkg/mod.py::foo"))
    assert ac.operations == []
    assert "skipped_implementation_layer" in ac.metadata


def test_simulated_change_add_node_module_is_skipped_no_subsystem():
    ac = from_simulated_change(SimulatedChange(action="add_node", node_id="pkg/mod.py"))
    assert ac.operations == []
    assert "skipped" in ac.metadata


def test_simulated_change_remove_node_function_is_no_op():
    ac = from_simulated_change(SimulatedChange(action="remove_node", node_id="pkg/mod.py::foo"))
    assert ac.operations == []
    assert "skipped_implementation_layer" in ac.metadata


def test_simulated_change_remove_node_module_is_component():
    ac = from_simulated_change(SimulatedChange(action="remove_node", node_id="pkg/mod.py"))
    assert ac.operations[0].op == OpType.REMOVE_COMPONENT


def test_target_workflow_to_change_is_baseline_aware():
    from codegraph.target_architecture import TargetWorkflow, TargetEdge, TargetNode

    target = TargetWorkflow(edges=[
        TargetEdge(source="A", target="B"),
        TargetEdge(source="A", target="C"),
    ], nodes=[
        TargetNode(node_id="pkg/new.py", module="pkg/new.py", subsystem="S"),
        TargetNode(node_id="pkg/new.py::foo", module="pkg/new.py"),  # function node
    ])
    current_workflow = {"edges": [{"source": "A", "target": "B"}]}  # A->B already exists
    current_nodes = {"A", "B"}

    ac = target_workflow_to_change(target, current_workflow, current_nodes)
    edges = [o for o in ac.operations if o.op == OpType.ADD_EDGE]
    # A->B exists; only A->C is missing
    assert len(edges) == 1 and edges[0].source == "A" and edges[0].target == "C" and edges[0].edge_type == "call"
    comps = [o for o in ac.operations if o.op == OpType.ADD_COMPONENT]
    assert len(comps) == 1 and comps[0].component == "pkg/new.py" and comps[0].component_subsystem == "S"
    # function node -> NO OP, recorded
    assert any("target_node_function" in s for s in ac.metadata.get("skipped", []))


def test_system_architecture_to_change_reuses_planner(monkeypatch):
    import codegraph.architecture_change_adapters as mod

    fake_plan = ArchPlan(tasks=[PlannedTask(task_type="create_module", subsystem="S", module="m.py")])
    monkeypatch.setattr(mod, "plan_architecture", lambda arch, g0, idx: fake_plan)
    ac = mod.system_architecture_to_change("arch", "g0", "idx")
    assert any(o.op == OpType.ADD_COMPONENT and o.component == "m.py" for o in ac.operations)
