"""Unit tests for task generation system.

Tasks O-012: Task generation, O-018: Version staleness.
"""

from __future__ import annotations

import pytest

from codegraph.models.tasks import (
    TaskID,
    TestChangeType,
    SuggestedFix,
    PolicyViolation,
)


class TestTaskIDPriority:
    """Test task type priority ordering."""

    def test_policy_violation_highest(self) -> None:
        assert TaskID.POLICY_VIOLATION.priority == 1

    def test_ordering(self) -> None:
        assert TaskID.POLICY_VIOLATION < TaskID.ORPHAN_NODES
        assert TaskID.ORPHAN_NODES < TaskID.INTENT_MISSING

    def test_all_task_ids_have_priority(self) -> None:
        for task_id in TaskID:
            assert isinstance(task_id.priority, int)
            assert task_id.priority >= 1


class TestTestChangeType:
    """Test change type enumeration."""

    def test_values(self) -> None:
        assert TestChangeType.UPDATE_EXECUTION_PATH.value == "update_execution_path"
        assert TestChangeType.UPDATE_MOCK.value == "update_mock"
        assert TestChangeType.UPDATE_ASSERTION.value == "update_assertion"
        assert TestChangeType.ADD_NEW_TEST.value == "add_new_test"


class TestSuggestedFix:
    """Test suggested fix enumeration."""

    def test_values(self) -> None:
        assert SuggestedFix.CONNECT_CALL.value == "connect_call"
        assert SuggestedFix.ADD_IMPORT.value == "add_import"
        assert SuggestedFix.FLAG_FOR_HUMAN_REVIEW.value == "flag_for_human_review"


class TestPolicyViolation:
    """Test policy violation dataclass."""

    def test_create_violation(self) -> None:
        v = PolicyViolation(
            source="mod.py::caller",
            required_target="mod.py::target",
            policy_reason="Must call target",
        )
        assert v.source == "mod.py::caller"
        assert v.required_target == "mod.py::target"

    def test_with_suggested_fix(self) -> None:
        v = PolicyViolation(
            source="a", required_target="b", policy_reason="test",
            suggested_fix="connect_call",
            suggested_fix_target="b",
        )
        assert v.suggested_fix == "connect_call"
