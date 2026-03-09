"""codegraph.models.tasks — Task queue data models.

Tasks B-009, B-010, B-019, B-021, B-022, B-046.
"""

from __future__ import annotations

import enum
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from codegraph.utils.formatting import format_json, iso_now


# ── B-019  Task ID enum with priority ─────────────────────────────────


class TaskID(str, enum.Enum):
    """Task types with built-in priority ordering.

    Lower numeric priority = higher urgency.
    """

    POLICY_VIOLATION = "policy_violation"
    MISSING_IMPORT = "missing_import"
    ORPHAN_NODES = "orphan_nodes"
    UNRESOLVED_DYNAMIC = "unresolved_dynamic"
    INTENT_MISSING = "intent_missing"
    STALE_INTENT = "stale_intent"
    MISSING_ARCHITECTURE_TEST = "missing_architecture_test"
    MISSING_TEST_COVERAGE = "missing_test_coverage"

    @property
    def priority(self) -> int:
        return _TASK_PRIORITY[self]

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, TaskID):
            return NotImplemented
        return self.priority < other.priority

    def __le__(self, other: object) -> bool:
        if not isinstance(other, TaskID):
            return NotImplemented
        return self.priority <= other.priority


_TASK_PRIORITY: Dict[TaskID, int] = {
    TaskID.POLICY_VIOLATION: 1,
    TaskID.MISSING_IMPORT: 2,
    TaskID.ORPHAN_NODES: 3,
    TaskID.UNRESOLVED_DYNAMIC: 4,
    TaskID.INTENT_MISSING: 5,
    TaskID.STALE_INTENT: 6,
    TaskID.MISSING_ARCHITECTURE_TEST: 3,
    TaskID.MISSING_TEST_COVERAGE: 5,
}


# ── B-021  Test change type enum ──────────────────────────────────────


class TestChangeType(str, enum.Enum):
    """How an affected test must be updated."""

    UPDATE_EXECUTION_PATH = "update_execution_path"
    UPDATE_MOCK = "update_mock"
    UPDATE_ASSERTION = "update_assertion"
    ADD_NEW_TEST = "add_new_test"


# ── B-022  Suggested fix enum ─────────────────────────────────────────


class SuggestedFix(str, enum.Enum):
    """Suggested fix types in task hints."""

    CONNECT_CALL = "connect_call"
    ADD_IMPORT = "add_import"
    FLAG_FOR_HUMAN_REVIEW = "flag_for_human_review"
    GENERATE_ARCHI_TEST = "generate_archi_test"


# ── B-009  PolicyViolation ────────────────────────────────────────────


@dataclass
class PolicyViolation:
    """A single policy violation inside a task."""

    source: str
    required_target: str
    policy_reason: str
    current_calls: List[str] = field(default_factory=list)
    suggested_fix: str = ""
    suggested_fix_target: Optional[str] = None
    affected_tests: List[str] = field(default_factory=list)
    test_update_required: bool = False
    test_change_type: Optional[str] = None  # TestChangeType value

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "source": self.source,
            "required_target": self.required_target,
            "policy_reason": self.policy_reason,
            "current_calls": self.current_calls,
            "suggested_fix": self.suggested_fix,
        }
        if self.suggested_fix_target is not None:
            d["suggested_fix_target"] = self.suggested_fix_target
        d["affected_tests"] = self.affected_tests
        d["test_update_required"] = self.test_update_required
        if self.test_change_type is not None:
            d["test_change_type"] = self.test_change_type
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> PolicyViolation:
        return cls(
            source=d["source"],
            required_target=d["required_target"],
            policy_reason=d.get("policy_reason", ""),
            current_calls=d.get("current_calls", []),
            suggested_fix=d.get("suggested_fix", ""),
            suggested_fix_target=d.get("suggested_fix_target"),
            affected_tests=d.get("affected_tests", []),
            test_update_required=d.get("test_update_required", False),
            test_change_type=d.get("test_change_type"),
        )


# ── B-009  TaskNode ───────────────────────────────────────────────────


@dataclass
class TaskNode:
    """A node entry within a task payload."""

    id: str
    file: Optional[str] = None
    type: Optional[str] = None
    calls: List[str] = field(default_factory=list)
    called_by: List[str] = field(default_factory=list)
    suggested_fix: str = ""
    missing_import: Optional[str] = None
    dynamic_target: Optional[str] = None
    previous_intent: Optional[str] = None
    body_hash_changed: Optional[bool] = None
    reason: Optional[str] = None
    # B-046  semantic context
    semantic_context: Optional[Dict[str, Any]] = None
    safety_warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"id": self.id}
        if self.file is not None:
            d["file"] = self.file
        if self.type is not None:
            d["type"] = self.type
        if self.calls:
            d["calls"] = self.calls
        if self.called_by:
            d["called_by"] = self.called_by
        if self.suggested_fix:
            d["suggested_fix"] = self.suggested_fix
        if self.missing_import is not None:
            d["missing_import"] = self.missing_import
        if self.dynamic_target is not None:
            d["dynamic_target"] = self.dynamic_target
        if self.previous_intent is not None:
            d["previous_intent"] = self.previous_intent
        if self.body_hash_changed is not None:
            d["body_hash_changed"] = self.body_hash_changed
        if self.reason is not None:
            d["reason"] = self.reason
        if self.semantic_context is not None:
            d["semantic_context"] = self.semantic_context
        if self.safety_warnings:
            d["safety_warnings"] = self.safety_warnings
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> TaskNode:
        return cls(
            id=d["id"],
            file=d.get("file"),
            type=d.get("type"),
            calls=d.get("calls", []),
            called_by=d.get("called_by", []),
            suggested_fix=d.get("suggested_fix", ""),
            missing_import=d.get("missing_import"),
            dynamic_target=d.get("dynamic_target"),
            previous_intent=d.get("previous_intent"),
            body_hash_changed=d.get("body_hash_changed"),
            reason=d.get("reason"),
            semantic_context=d.get("semantic_context"),
            safety_warnings=d.get("safety_warnings", []),
        )


# ── B-009  TaskItem ───────────────────────────────────────────────────


@dataclass
class TaskItem:
    """A single task in the agent work queue."""

    task_id: str
    priority: int = 5
    nodes: Optional[List[TaskNode]] = None
    violations: Optional[List[PolicyViolation]] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"task_id": self.task_id, "priority": self.priority}
        if self.nodes is not None:
            d["nodes"] = [n.to_dict() for n in self.nodes]
        if self.violations is not None:
            d["violations"] = [v.to_dict() for v in self.violations]
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> TaskItem:
        nodes = None
        if "nodes" in d:
            nodes = [TaskNode.from_dict(nd) for nd in d["nodes"]]
        violations = None
        if "violations" in d:
            violations = [PolicyViolation.from_dict(vd) for vd in d["violations"]]
        return cls(
            task_id=d["task_id"],
            priority=d.get("priority", 5),
            nodes=nodes,
            violations=violations,
        )


# ── B-010  TaskBatch ──────────────────────────────────────────────────


@dataclass
class TaskBatch:
    """Top-level tasks.json structure wrapping all tasks."""

    cycle: int = 1
    graph_version: int = 1
    generated_at: str = ""
    tasks: List[TaskItem] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.generated_at:
            self.generated_at = iso_now()

    def get_tasks_by_type(self, task_id: str) -> List[TaskItem]:
        return [t for t in self.tasks if t.task_id == task_id]

    def get_tasks_by_priority(self) -> List[TaskItem]:
        """Return tasks sorted by priority (ascending = highest urgency first)."""
        return sorted(self.tasks, key=lambda t: t.priority)

    def to_json(self, compact: bool = False) -> str:
        sorted_tasks = sorted(self.tasks, key=lambda t: t.priority)
        data = {
            "cycle": self.cycle,
            "graph_version": self.graph_version,
            "generated_at": self.generated_at,
            "tasks": [t.to_dict() for t in sorted_tasks],
        }
        return format_json(data, compact=compact)

    @classmethod
    def from_json(cls, text: str) -> TaskBatch:
        data = json.loads(text)
        tasks = [TaskItem.from_dict(td) for td in data.get("tasks", [])]
        return cls(
            cycle=data.get("cycle", 1),
            graph_version=data.get("graph_version", 1),
            generated_at=data.get("generated_at", ""),
            tasks=tasks,
        )
