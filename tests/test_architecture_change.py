"""Tests for the canonical ArchitectureChange model (v1.2 issue #27/A)."""

import pytest

from codegraph.architecture_change import (
    ArchitectureChange,
    ArchRelationship,
    ConstraintChange,
)
from codegraph.arch_schema import ArchConstraint
from codegraph.models.agent_response import AgentResponse, RepairAction
from codegraph.arch_planner import PlannedTask


def test_roundtrip_dict_and_json():
    ch = ArchitectureChange(
        add=["service.payment"],
        remove=["service.legacy"],
        modify=["service.order"],
        relationships=[
            ArchRelationship(action="add", from_="order", to="payment", type="calls")
        ],
        constraints=[
            ConstraintChange(
                action="add",
                constraint=ArchConstraint("forbidden", "ui", "db", "no direct dep"),
            )
        ],
    )
    back = ArchitectureChange.from_dict(ch.to_dict())
    assert back == ch
    # round-trips through JSON too
    assert ArchitectureChange.from_json(ch.to_json()) == ch


def test_from_agent_response():
    ar = AgentResponse(
        repairs=[
            RepairAction(node="a", action="connect_call", target="b"),
            RepairAction(node="c", action="remove_dead_code"),
            RepairAction(node="d", action="flag_for_human_review", reason="check"),
        ]
    )
    ch = ArchitectureChange.from_agent_response(ar)
    assert ArchRelationship(action="add", from_="a", to="b", type="calls") in ch.relationships
    assert "c" in ch.remove
    # flag_for_human_review is a review note, not a topology change
    assert len(ch.relationships) == 1


def test_from_planned_tasks():
    tasks = [
        PlannedTask(task_type="create_module", module="service.payment"),
        PlannedTask(task_type="connect_call", source="order", target="payment"),
        PlannedTask(task_type="add_constraint", source="ui", target="db", reason="boundary"),
    ]
    ch = ArchitectureChange.from_planned_tasks(tasks)
    assert "service.payment" in ch.add
    assert (
        ArchRelationship(action="add", from_="order", to="payment", type="calls")
        in ch.relationships
    )
    assert ch.constraints and ch.constraints[0].constraint.source == "ui"


def test_to_simulated_changes_bridge():
    ch = ArchitectureChange(
        add=["x"],
        remove=["y"],
        relationships=[
            ArchRelationship(action="add", from_="a", to="b"),
            ArchRelationship(action="remove", from_="c", to="d"),
        ],
    )
    sims = ch.to_simulated_changes()
    actions = {(s.action, s.node_id, s.source, s.target) for s in sims}
    assert ("add_node", "x", "", "") in actions
    assert ("remove_node", "y", "", "") in actions
    assert ("add_edge", "", "a", "b") in actions
    assert ("remove_edge", "", "c", "d") in actions


def test_user_vision_json_shape():
    text = """
    {
      "add": ["service.payment"],
      "remove": [],
      "modify": ["service.order"],
      "relationships": [{"action": "add", "from": "order", "to": "payment", "type": "calls"}],
      "constraints": [{"action": "add", "type": "forbidden", "source": "ui", "target": "db", "reason": ""}]
    }
    """
    ch = ArchitectureChange.from_json(text)
    assert ch.add == ["service.payment"]
    assert ch.modify == ["service.order"]
    assert ch.relationships[0].to == "payment"
    assert ch.constraints[0].constraint.target == "db"
