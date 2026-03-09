"""Unit tests for suggested workflow / policy system.

Tasks O-010: Scope resolution, O-011: Policy violation detection.
"""

from __future__ import annotations

import pytest

from codegraph.models.suggested_workflow import (
    SuggestedWorkflowRule,
    RuleType,
)


# ── O-010: Scope Resolution ──────────────────────────────────────────


class TestRuleCreation:
    """Test suggested workflow rule creation and validation."""

    def test_valid_rule(self) -> None:
        rule = SuggestedWorkflowRule(
            id="r1", type="required_call",
            source="mod.py::func_a", target="mod.py::func_b",
            reason="A must call B",
        )
        assert rule.id == "r1"
        assert rule.type == "required_call"

    def test_missing_source_raises(self) -> None:
        with pytest.raises(ValueError, match="source"):
            SuggestedWorkflowRule(
                id="r1", type="required_call",
                target="mod.py::func_b",
                reason="test",
            )

    def test_missing_target_raises(self) -> None:
        with pytest.raises(ValueError, match="target"):
            SuggestedWorkflowRule(
                id="r1", type="required_call",
                source="mod.py::func_a",
                reason="test",
            )

    def test_layer_scope(self) -> None:
        rule = SuggestedWorkflowRule(
            id="r1", type="forbidden_call",
            source_layer=3, target_layer=0,
            reason="Project code must not call stdlib directly",
        )
        assert rule.source_layer == 3
        assert rule.target_layer == 0

    def test_arch_layer_scope(self) -> None:
        rule = SuggestedWorkflowRule(
            id="r1", type="required_call",
            source_arch_layer="controller", target_arch_layer="service",
            reason="Controllers must call services",
        )
        assert rule.source_arch_layer == "controller"

    def test_serialization_roundtrip(self) -> None:
        rule = SuggestedWorkflowRule(
            id="r1", type="required_call",
            source="a", target="b", reason="test",
        )
        d = rule.to_dict()
        restored = SuggestedWorkflowRule.from_dict(d)
        assert restored.id == rule.id
        assert restored.type == rule.type


# ── O-011: Policy Violation Detection ─────────────────────────────────


class TestRuleTypeViolation:
    """Test violation detection logic."""

    def test_required_call_missing_is_violation(self) -> None:
        rt = RuleType.REQUIRED_CALL
        assert rt.is_violation(edge_exists=False) is True

    def test_required_call_present_is_ok(self) -> None:
        rt = RuleType.REQUIRED_CALL
        assert rt.is_violation(edge_exists=True) is False

    def test_forbidden_call_present_is_violation(self) -> None:
        rt = RuleType.FORBIDDEN_CALL
        assert rt.is_violation(edge_exists=True) is True

    def test_forbidden_call_absent_is_ok(self) -> None:
        rt = RuleType.FORBIDDEN_CALL
        assert rt.is_violation(edge_exists=False) is False
