"""Unit tests for Graph_2 semantic behavior models.

Tests R-001 through R-007.
"""

from __future__ import annotations

import json

import pytest

from codegraph.models.graph2 import (
    ActionType,
    SideEffectType,
    SemanticAction,
    Guard,
    SideEffect,
    DataFlowItem,
    DataFlowSummary,
    Graph2Node,
    Graph2,
)


# ── R-001: ActionType Enum ─────────────────────────────────────────────


class TestActionType:

    def test_all_values(self) -> None:
        assert len(ActionType) == 21

    def test_string_enum(self) -> None:
        assert ActionType.READ == "read"
        assert ActionType.WRITE == "write"
        assert ActionType.UNKNOWN == "unknown"

    def test_from_value(self) -> None:
        assert ActionType("read") == ActionType.READ
        assert ActionType("delete") == ActionType.DELETE


# ── R-002: SideEffectType Enum ─────────────────────────────────────────


class TestSideEffectType:

    def test_all_values(self) -> None:
        assert len(SideEffectType) == 16

    def test_string_enum(self) -> None:
        assert SideEffectType.DATABASE_WRITE == "database_write"
        assert SideEffectType.NETWORK_CALL == "network_call"
        assert SideEffectType.NONE == "none"


# ── R-003: SemanticAction ──────────────────────────────────────────────


class TestSemanticAction:

    def test_defaults(self) -> None:
        a = SemanticAction()
        assert a.verb == ""
        assert a.action_type == ActionType.UNKNOWN

    def test_roundtrip_dict(self) -> None:
        a = SemanticAction(verb="fetch", object="data", action_type=ActionType.READ, confidence=0.9)
        d = a.to_dict()
        restored = SemanticAction.from_dict(d)
        assert restored.verb == "fetch"
        assert restored.action_type == ActionType.READ
        assert restored.confidence == 0.9


# ── R-003: Guard ───────────────────────────────────────────────────────


class TestGuard:

    def test_defaults(self) -> None:
        g = Guard()
        assert g.condition == ""
        assert g.early_return is False

    def test_roundtrip_dict(self) -> None:
        g = Guard(condition="x > 0", raises="ValueError", early_return=True)
        d = g.to_dict()
        restored = Guard.from_dict(d)
        assert restored.condition == "x > 0"
        assert restored.raises == "ValueError"
        assert restored.early_return is True


# ── R-004: SideEffect ─────────────────────────────────────────────────


class TestSideEffect:

    def test_defaults(self) -> None:
        s = SideEffect()
        assert s.effect_type == SideEffectType.NONE

    def test_roundtrip_dict(self) -> None:
        s = SideEffect(type="db", target="users", effect_type=SideEffectType.DATABASE_WRITE, reversible=True)
        d = s.to_dict()
        restored = SideEffect.from_dict(d)
        assert restored.type == "db"
        assert restored.effect_type == SideEffectType.DATABASE_WRITE
        assert restored.reversible is True


# ── R-004: DataFlowItem & DataFlowSummary ──────────────────────────────


class TestDataFlow:

    def test_item_roundtrip(self) -> None:
        item = DataFlowItem(name="user_id", type_annotation="int", source="parameter")
        d = item.to_dict()
        restored = DataFlowItem.from_dict(d)
        assert restored.name == "user_id"
        assert restored.type_annotation == "int"

    def test_summary_roundtrip(self) -> None:
        summary = DataFlowSummary(
            inputs=["x", "y"],
            outputs=["result"],
            transforms=["add"],
            input_items=[DataFlowItem(name="x")],
            output_items=[DataFlowItem(name="result")],
        )
        d = summary.to_dict()
        restored = DataFlowSummary.from_dict(d)
        assert restored.inputs == ["x", "y"]
        assert len(restored.input_items) == 1
        assert len(restored.output_items) == 1


# ── R-005: Graph2Node ─────────────────────────────────────────────────


class TestGraph2Node:

    def test_compute_behavior_hash(self) -> None:
        node = Graph2Node(
            id="mod.py::func",
            actions=[SemanticAction(verb="read", action_type=ActionType.READ)],
            guards=[Guard(condition="x > 0")],
        )
        h = node.compute_behavior_hash()
        assert isinstance(h, str)
        assert len(h) == 64

    def test_behavior_hash_stable(self) -> None:
        node = Graph2Node(
            id="mod.py::func",
            actions=[SemanticAction(verb="read")],
        )
        h1 = node.compute_behavior_hash()
        h2 = node.compute_behavior_hash()
        assert h1 == h2

    def test_behavior_hash_changes(self) -> None:
        n1 = Graph2Node(id="a", actions=[SemanticAction(verb="read")])
        n2 = Graph2Node(id="a", actions=[SemanticAction(verb="write")])
        assert n1.compute_behavior_hash() != n2.compute_behavior_hash()

    def test_roundtrip_dict(self) -> None:
        node = Graph2Node(
            id="mod.py::func",
            actions=[SemanticAction(verb="fetch", action_type=ActionType.READ)],
            guards=[Guard(condition="auth")],
            side_effects=[SideEffect(type="network", effect_type=SideEffectType.NETWORK_CALL)],
            data_flow=DataFlowSummary(inputs=["url"]),
            domain_tags=["api"],
            library_calls=["requests"],
            sql_operations=["SELECT"],
        )
        d = node.to_dict()
        restored = Graph2Node.from_dict(d)
        assert restored.id == "mod.py::func"
        assert len(restored.actions) == 1
        assert restored.actions[0].verb == "fetch"
        assert len(restored.guards) == 1
        assert len(restored.side_effects) == 1
        assert restored.data_flow is not None
        assert restored.domain_tags == ["api"]
        assert restored.library_calls == ["requests"]
        assert restored.sql_operations == ["SELECT"]

    def test_post_init_sets_generated_at(self) -> None:
        node = Graph2Node(id="a")
        assert node.generated_at != ""


# ── R-006/R-007: Graph2 Collection ────────────────────────────────────


class TestGraph2:

    def _make_graph2(self) -> Graph2:
        n1 = Graph2Node(
            id="mod.py::read_user",
            actions=[SemanticAction(verb="read", action_type=ActionType.READ)],
            side_effects=[SideEffect(type="db", effect_type=SideEffectType.DATABASE_READ)],
            domain_tags=["database"],
            library_calls=["sqlalchemy"],
            sql_operations=["SELECT"],
        )
        n2 = Graph2Node(
            id="mod.py::send_email",
            actions=[SemanticAction(verb="send", action_type=ActionType.SEND)],
            side_effects=[SideEffect(type="net", effect_type=SideEffectType.NETWORK_CALL)],
            domain_tags=["api"],
        )
        n3 = Graph2Node(
            id="mod.py::log_event",
            actions=[SemanticAction(verb="log", action_type=ActionType.LOG)],
            side_effects=[SideEffect(type="log", effect_type=SideEffectType.LOGGING)],
            domain_tags=["database"],
        )
        return Graph2(nodes=[n1, n2, n3])

    def test_get_node(self) -> None:
        g = self._make_graph2()
        assert g.get_node("mod.py::read_user") is not None
        assert g.get_node("nonexistent") is None

    def test_upsert_node(self) -> None:
        g = self._make_graph2()
        new_node = Graph2Node(id="mod.py::new_func")
        g.upsert_node(new_node)
        assert g.get_node("mod.py::new_func") is not None
        assert len(g.nodes) == 4

    def test_upsert_replaces(self) -> None:
        g = self._make_graph2()
        replacement = Graph2Node(id="mod.py::read_user", domain_tags=["replaced"])
        g.upsert_node(replacement)
        assert g.get_node("mod.py::read_user").domain_tags == ["replaced"]

    def test_remove_node(self) -> None:
        g = self._make_graph2()
        g.remove_node("mod.py::log_event")
        assert g.get_node("mod.py::log_event") is None
        assert len(g.nodes) == 2

    def test_nodes_with_side_effect(self) -> None:
        g = self._make_graph2()
        db_nodes = g.nodes_with_side_effect(SideEffectType.DATABASE_READ)
        assert len(db_nodes) == 1
        assert db_nodes[0].id == "mod.py::read_user"

    def test_nodes_with_action_type(self) -> None:
        g = self._make_graph2()
        send_nodes = g.nodes_with_action_type(ActionType.SEND)
        assert len(send_nodes) == 1
        assert send_nodes[0].id == "mod.py::send_email"

    def test_nodes_with_domain_tag(self) -> None:
        g = self._make_graph2()
        db_tagged = g.nodes_with_domain_tag("database")
        assert len(db_tagged) == 2

    def test_nodes_with_sql(self) -> None:
        g = self._make_graph2()
        sql_nodes = g.nodes_with_sql()
        assert len(sql_nodes) == 1

    def test_nodes_with_library(self) -> None:
        g = self._make_graph2()
        sa_nodes = g.nodes_with_library("sqlalchemy")
        assert len(sa_nodes) == 1

    def test_behavior_summary(self) -> None:
        g = self._make_graph2()
        summary = g.get_behavior_summary()
        assert "total_nodes" in summary
        assert summary["total_nodes"] == 3
        assert "action_types" in summary
        assert "side_effect_types" in summary
        assert "domain_tags" in summary

    def test_json_roundtrip(self) -> None:
        g = self._make_graph2()
        text = g.to_json()
        restored = Graph2.from_json(text)
        assert len(restored.nodes) == 3
        assert restored.get_node("mod.py::read_user") is not None

    def test_json_compact(self) -> None:
        g = self._make_graph2()
        text = g.to_json(compact=True)
        data = json.loads(text)
        assert "nodes" in data
