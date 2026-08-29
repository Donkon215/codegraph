"""PHASE 4 — adapter / IR proof matrix (issue #27).

Proves SEMANTICS, not just construction:
- conflict + duplicate rejection (IR-level)
- distinct typed edges survive
- forbidden_dependency preserved verbatim (never -> "forbidden")
- equivalence: different old representations of the SAME intent normalize() equal
- non-equivalence: differently-typed same-intent representations are correctly distinct
"""

import pytest
from codegraph.architecture_change import (
    ArchitectureChange,
    ArchitectureOperation,
    OpType,
    ArchitectureChangeValidationError,
)
from codegraph.architecture_change_adapters import (
    from_repair_action,
    from_agent_response,
    from_planned_task,
    from_arch_plan,
    from_simulated_change,
    from_arch_change,
)
from codegraph.models.agent_response import AgentResponse, RepairAction
from codegraph.arch_planner import PlannedTask, ArchPlan
from codegraph.simulator import SimulatedChange
from codegraph.architecture_simulator import ArchChange


# ── conflict / dedup behavior (IR-level) ──────────────────────────────────

def test_add_and_remove_same_edge_is_rejected():
    ac = ArchitectureChange(operations=[
        ArchitectureOperation(OpType.ADD_EDGE, source="A", target="B", edge_type="call"),
        ArchitectureOperation(OpType.REMOVE_EDGE, source="A", target="B", edge_type="call"),
    ])
    with pytest.raises(ArchitectureChangeValidationError):
        ac.validate()


def test_duplicate_add_edge_is_rejected():
    ac = ArchitectureChange(operations=[
        ArchitectureOperation(OpType.ADD_EDGE, source="A", target="B", edge_type="call"),
        ArchitectureOperation(OpType.ADD_EDGE, source="A", target="B", edge_type="call"),
    ])
    with pytest.raises(ArchitectureChangeValidationError):
        ac.validate()


def test_distinct_typed_edges_survive():
    ac = ArchitectureChange(operations=[
        ArchitectureOperation(OpType.ADD_EDGE, source="A", target="B", edge_type="call"),
        ArchitectureOperation(OpType.ADD_EDGE, source="A", target="B", edge_type="dependency"),
    ])
    ac.validate()  # distinct edge_type -> NOT a duplicate
    assert len(ac.operations) == 2


def test_forbidden_dependency_preserved_not_normalized():
    ac = ArchitectureChange(operations=[
        ArchitectureOperation(OpType.ADD_CONSTRAINT, constraint_type="forbidden_dependency",
                              source="A", target="B"),
    ])
    ac.validate()
    norm = ac.normalize()
    assert norm.operations[0].constraint_type == "forbidden_dependency"


# ── semantic equivalence (different old models, same intent) ──────────────

def test_equivalence_agentresponse_connect_call_vs_archplan():
    agent = AgentResponse(cycle="c", graph_version=1,
                          repairs=[RepairAction(node="A", action="connect_call", target="B")],
                          intents=[], workflow_suggestions=[])
    plan = ArchPlan(tasks=[PlannedTask(task_type="connect_call", source="A", target="B")])
    a = from_agent_response(agent).normalize()
    b = from_arch_plan(plan).normalize()
    assert a == b
    assert a.operations[0].op == OpType.ADD_EDGE and a.operations[0].edge_type == "call"


def test_equivalence_repairaction_connect_call_vs_simulatedchange():
    # Two different old models describing "call A->B" must normalize() equal.
    a = from_repair_action(RepairAction(node="A", action="connect_call", target="B")).normalize()
    b = from_simulated_change(SimulatedChange(action="add_edge", source="A", target="B")).normalize()
    assert a == b


def test_nonequivalence_archchange_add_edge_vs_plannedtask_connect_call():
    # These are NOT equivalent: ArchChange.add_edge -> dependency, PlannedTask -> call.
    x = from_arch_change(ArchChange(action="add_edge", subsystem="A", target_subsystem="B")).normalize()
    y = from_planned_task(PlannedTask(task_type="connect_call", source="A", target="B")).normalize()
    assert x != y
    assert x.operations[0].edge_type == "dependency"
    assert y.operations[0].edge_type == "call"
