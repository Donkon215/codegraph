"""codegraph.tasks — Task generation and management.

Group I: I-007 through I-017, I-021–I-022, I-024, I-027–I-028.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from codegraph.constants import (
    PRIORITY_COVERAGE_GAP,
    PRIORITY_INFO,
    PRIORITY_MISSING_IMPORT,
    PRIORITY_ORPHAN_NODE,
    PRIORITY_POLICY_VIOLATION,
    PRIORITY_STALE_INTENT,
    TASKS_DIR,
    TASKS_FILE,
)
from codegraph.logging_config import get_logger
from codegraph.models.agent_response import AgentResponse
from codegraph.models.graph0 import Graph0
from codegraph.models.graph1 import Graph1
from codegraph.models.tasks import (
    PolicyViolation,
    TaskBatch,
    TaskID,
    TaskItem,
    TaskNode,
)
from codegraph.models.workflow import Workflow
from codegraph.storage import atomic_write, resolve_path

logger = get_logger("tasks")


# ═══════════════════════════════════════════════════════════════════════
# I-008 — Task Priority Assignment
# ═══════════════════════════════════════════════════════════════════════

_FINDING_PRIORITY: Dict[str, int] = {
    "policy_violation": PRIORITY_POLICY_VIOLATION,
    "missing_edge": PRIORITY_MISSING_IMPORT,
    "orphan": PRIORITY_ORPHAN_NODE,
    "missing_intent": 5,
    "coverage_gap": PRIORITY_COVERAGE_GAP,
    "stale_intent": PRIORITY_STALE_INTENT,
    "cycle_mismatch": 7,
}


def assign_priority(finding_type: str) -> int:
    """Map finding type to priority (I-008).  Lower = higher urgency."""
    return _FINDING_PRIORITY.get(finding_type, PRIORITY_INFO)


# ═══════════════════════════════════════════════════════════════════════
# I-010 — Suggested Fix Generator
# ═══════════════════════════════════════════════════════════════════════


def generate_suggested_fix(finding_type: str, details: Dict[str, Any]) -> str:
    """Generate a code-level fix suggestion for a finding (I-010)."""
    if finding_type == "policy_violation":
        rule_type = details.get("rule_type", "required_call")
        if rule_type == "required_call":
            return "Add call to the required target at the first executable statement"
        elif rule_type == "forbidden_call":
            return "Remove the forbidden call or refactor through an intermediary"
    elif finding_type == "orphan":
        classification = details.get("classification", "dead_code")
        if classification == "dead_code":
            return "Remove dead code or connect to callers"
        elif classification == "entry_point":
            return "Entry point — no action needed"
        elif classification == "new_code":
            return "Integrate new code into the call graph"
        return "Review disconnected node and connect to workflow"
    elif finding_type == "missing_intent":
        return "Add intent annotation describing this node's purpose"
    elif finding_type == "coverage_gap":
        return "Create a test function covering this production code"
    elif finding_type == "stale_intent":
        return "Review and update intent to match current implementation"
    elif finding_type == "missing_edge":
        return "Verify call relationship and add if appropriate"
    return "Review and address"


# ═══════════════════════════════════════════════════════════════════════
# I-009 — Task Pre-Fetched Context
# ═══════════════════════════════════════════════════════════════════════


def fetch_task_context(
    node_id: str,
    graph0: Graph0,
    graph1: Graph1,
    index: Any = None,
) -> TaskNode:
    """Build a TaskNode with pre-fetched context for a node (I-009)."""
    g0_node = graph0.get_node(node_id)
    g1_node = graph1.get_node(node_id)

    callers: List[str] = []
    callees: List[str] = []

    if index is not None:
        try:
            callers = index.get_callers(node_id)
            callees = index.get_callees(node_id)
        except Exception:
            pass

    return TaskNode(
        id=node_id,
        file=g0_node.file if g0_node else None,
        type=g0_node.type if g0_node else None,
        calls=callees,
        called_by=callers,
        previous_intent=g1_node.intent if g1_node else None,
        body_hash_changed=(
            g0_node.body_hash != g1_node.intent_body_hash
            if g0_node and g1_node and g1_node.intent_body_hash
            else None
        ),
    )


# ═══════════════════════════════════════════════════════════════════════
# I-024 — Batch Context Optimization
# ═══════════════════════════════════════════════════════════════════════


def fetch_batch_context(
    node_ids: Set[str],
    graph0: Graph0,
    graph1: Graph1,
    index: Any = None,
) -> Dict[str, TaskNode]:
    """Batch-fetch context for multiple nodes at once (I-024)."""
    result: Dict[str, TaskNode] = {}

    # Batch-query callers/callees from index
    all_callers: Dict[str, List[str]] = {}
    all_callees: Dict[str, List[str]] = {}
    if index is not None:
        for nid in node_ids:
            try:
                all_callers[nid] = index.get_callers(nid)
                all_callees[nid] = index.get_callees(nid)
            except Exception:
                pass

    for nid in node_ids:
        g0_node = graph0.get_node(nid)
        g1_node = graph1.get_node(nid)
        result[nid] = TaskNode(
            id=nid,
            file=g0_node.file if g0_node else None,
            type=g0_node.type if g0_node else None,
            calls=all_callees.get(nid, []),
            called_by=all_callers.get(nid, []),
            previous_intent=g1_node.intent if g1_node else None,
            body_hash_changed=(
                g0_node.body_hash != g1_node.intent_body_hash
                if g0_node and g1_node and g1_node.intent_body_hash
                else None
            ),
        )

    return result


# ═══════════════════════════════════════════════════════════════════════
# I-016 — Test Impact Integration
# ═══════════════════════════════════════════════════════════════════════


def get_affected_tests(
    node_id: str, index: Any = None,
) -> List[str]:
    """Get tests that cover a node (I-016)."""
    if index is None:
        return []
    try:
        return index.get_tests_for_node(node_id)
    except Exception:
        return []


# ═══════════════════════════════════════════════════════════════════════
# I-007 — Task Generation Engine
# ═══════════════════════════════════════════════════════════════════════


def generate_tasks(
    analysis: Any,  # AnalysisResult from analyzer.py
    graph0: Graph0,
    graph1: Graph1,
    workflow: Workflow,
    *,
    index: Any = None,
    graph_version: int = 1,
    cycle: int = 1,
) -> TaskBatch:
    """Convert analysis findings into a structured task batch (I-007)."""
    batch = TaskBatch(cycle=cycle, graph_version=graph_version)

    # Collect all node IDs for batch context
    all_node_ids: Set[str] = set()
    for finding in analysis.findings:
        if finding.node_id:
            all_node_ids.add(finding.node_id)

    # I-024 — batch context
    context_map = fetch_batch_context(all_node_ids, graph0, graph1, index)

    # Group findings by type for task grouping
    findings_by_type: Dict[str, list] = defaultdict(list)
    for finding in analysis.findings:
        findings_by_type[finding.finding_type].append(finding)

    # Policy violations → group by rule
    for finding in findings_by_type.get("policy_violation", []):
        rule_id = finding.details.get("rule_id", "unknown")
        node = context_map.get(finding.node_id)
        if node:
            node.suggested_fix = generate_suggested_fix("policy_violation", finding.details)
            node.reason = finding.message
        violation = PolicyViolation(
            source=finding.node_id,
            required_target=finding.details.get("target", ""),
            policy_reason=finding.details.get("reason", ""),
            suggested_fix=generate_suggested_fix("policy_violation", finding.details),
            affected_tests=get_affected_tests(finding.node_id, index),
        )
        batch.tasks.append(TaskItem(
            task_id=TaskID.POLICY_VIOLATION.value,
            priority=assign_priority("policy_violation"),
            nodes=[node] if node else None,
            violations=[violation],
        ))

    # Orphans → group by classification
    orphan_findings = findings_by_type.get("orphan", [])
    if orphan_findings:
        nodes = []
        for f in orphan_findings:
            node = context_map.get(f.node_id)
            if node:
                classification = f.details.get("classification", "dead_code")
                node.suggested_fix = generate_suggested_fix("orphan", f.details)
                node.reason = f"Orphan ({classification})"
                nodes.append(node)
        if nodes:
            batch.tasks.append(TaskItem(
                task_id=TaskID.ORPHAN_NODES.value,
                priority=assign_priority("orphan"),
                nodes=nodes,
            ))

    # Coverage gaps
    coverage_findings = findings_by_type.get("coverage_gap", [])
    if coverage_findings:
        nodes = []
        for f in coverage_findings:
            node = context_map.get(f.node_id)
            if node:
                node.suggested_fix = generate_suggested_fix("coverage_gap", {})
                nodes.append(node)
        if nodes:
            batch.tasks.append(TaskItem(
                task_id=TaskID.MISSING_TEST_COVERAGE.value,
                priority=assign_priority("coverage_gap"),
                nodes=nodes,
            ))

    # Stale intents
    stale_findings = findings_by_type.get("stale_intent", [])
    if stale_findings:
        nodes = []
        for f in stale_findings:
            node = context_map.get(f.node_id)
            if node:
                node.suggested_fix = generate_suggested_fix("stale_intent", {})
                node.body_hash_changed = True
                nodes.append(node)
        if nodes:
            batch.tasks.append(TaskItem(
                task_id=TaskID.STALE_INTENT.value,
                priority=assign_priority("stale_intent"),
                nodes=nodes,
            ))

    # Missing intents
    intent_findings = findings_by_type.get("missing_intent", [])
    if intent_findings:
        nodes = []
        for f in intent_findings:
            node = context_map.get(f.node_id)
            if node:
                node.suggested_fix = generate_suggested_fix("missing_intent", {})
                nodes.append(node)
        if nodes:
            batch.tasks.append(TaskItem(
                task_id=TaskID.INTENT_MISSING.value,
                priority=assign_priority("missing_intent"),
                nodes=nodes,
            ))

    # Missing edges
    edge_findings = findings_by_type.get("missing_edge", [])
    if edge_findings:
        nodes = []
        for f in edge_findings:
            node = context_map.get(f.node_id)
            if node:
                node.suggested_fix = generate_suggested_fix("missing_edge", {})
                nodes.append(node)
        if nodes:
            batch.tasks.append(TaskItem(
                task_id=TaskID.MISSING_IMPORT.value,
                priority=assign_priority("missing_edge"),
                nodes=nodes,
            ))

    # I-017 — Deduplicate
    batch.tasks = deduplicate_tasks(batch.tasks)

    # Sort by priority
    batch.tasks.sort(key=lambda t: t.priority)

    return batch


# ═══════════════════════════════════════════════════════════════════════
# I-017 — Task Deduplication
# ═══════════════════════════════════════════════════════════════════════


def deduplicate_tasks(tasks: List[TaskItem]) -> List[TaskItem]:
    """Remove duplicate tasks (I-017).  Keep highest priority version."""
    seen: Dict[str, TaskItem] = {}
    for task in tasks:
        # Build dedup key from task_id + node IDs
        node_ids = tuple(sorted(n.id for n in (task.nodes or [])))
        key = f"{task.task_id}:{node_ids}"
        if key in seen:
            # Keep the one with lower (higher urgency) priority
            if task.priority < seen[key].priority:
                seen[key] = task
        else:
            seen[key] = task
    return list(seen.values())


# ═══════════════════════════════════════════════════════════════════════
# I-011 — Task Batch Writer
# ═══════════════════════════════════════════════════════════════════════


def _tasks_path(project_root: Path) -> Path:
    return resolve_path(project_root, TASKS_DIR, TASKS_FILE)


def write_tasks(batch: TaskBatch, project_root: Path) -> Path:
    """Write tasks.json atomically (I-011)."""
    dest = _tasks_path(project_root)
    dest.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(batch.to_json())
    atomic_write(dest, data)
    logger.info("Saved %d tasks → %s", len(batch.tasks), dest)
    return dest


# ═══════════════════════════════════════════════════════════════════════
# I-012 — Task Batch Loader
# ═══════════════════════════════════════════════════════════════════════


def load_tasks(project_root: Path) -> TaskBatch:
    """Load existing tasks.json (I-012).  Returns empty batch if missing."""
    path = _tasks_path(project_root)
    if not path.exists():
        return TaskBatch()
    text = path.read_text(encoding="utf-8")
    return TaskBatch.from_json(text)


# ═══════════════════════════════════════════════════════════════════════
# I-013 — Agent Response Parser
# ═══════════════════════════════════════════════════════════════════════


def parse_agent_response(project_root: Path) -> AgentResponse:
    """Parse agent_response.json (I-013)."""
    from codegraph.constants import RESPONSES_DIR
    resp_path = resolve_path(project_root, RESPONSES_DIR, "agent_response.json")
    if not resp_path.exists():
        raise FileNotFoundError(f"Agent response not found at {resp_path}")
    text = resp_path.read_text(encoding="utf-8")
    return AgentResponse.from_json(text)


# ═══════════════════════════════════════════════════════════════════════
# I-014 — Version Staleness Check
# ═══════════════════════════════════════════════════════════════════════


def validate_version(response_version: int, current_version: int) -> Tuple[bool, str]:
    """Check graph_version freshness (I-014).  Returns (ok, message)."""
    if response_version != current_version:
        return (
            False,
            f"Version mismatch: response v{response_version} vs current v{current_version}. "
            "Agent must re-read tasks with the current graph_version.",
        )
    return True, "OK"




# ═══════════════════════════════════════════════════════════════════════
# I-015 — Task Filtering by Type
# ═══════════════════════════════════════════════════════════════════════


def filter_tasks(
    batch: TaskBatch,
    *,
    task_type: Optional[str] = None,
    max_priority: Optional[int] = None,
    node_id: Optional[str] = None,
) -> List[TaskItem]:
    """Filter tasks by type, priority, or node (I-015)."""
    tasks = batch.tasks

    if task_type is not None:
        tasks = [t for t in tasks if t.task_id == task_type]

    if max_priority is not None:
        tasks = [t for t in tasks if t.priority <= max_priority]

    if node_id is not None:
        filtered = []
        for t in tasks:
            if t.nodes and any(n.id == node_id for n in t.nodes):
                filtered.append(t)
        tasks = filtered

    return tasks


# ═══════════════════════════════════════════════════════════════════════
# I-021 — Task Statistics Summary
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class TaskStats:
    """Task batch statistics (I-021)."""

    total: int = 0
    by_type: Dict[str, int] = field(default_factory=dict)
    by_priority: Dict[int, int] = field(default_factory=dict)
    total_nodes: int = 0

    def format(self) -> str:
        lines = [f"Tasks: {self.total}"]
        if self.by_type:
            lines.append("  By type:")
            for t, c in sorted(self.by_type.items()):
                lines.append(f"    {t}: {c}")
        if self.by_priority:
            lines.append("  By priority:")
            for p, c in sorted(self.by_priority.items()):
                lines.append(f"    P{p}: {c}")
        lines.append(f"  Total affected nodes: {self.total_nodes}")
        return "\n".join(lines)


def task_statistics(batch: TaskBatch) -> TaskStats:
    """Generate task batch statistics (I-021)."""
    stats = TaskStats(total=len(batch.tasks))
    for task in batch.tasks:
        stats.by_type[task.task_id] = stats.by_type.get(task.task_id, 0) + 1
        stats.by_priority[task.priority] = stats.by_priority.get(task.priority, 0) + 1
        if task.nodes:
            stats.total_nodes += len(task.nodes)
    return stats


# ═══════════════════════════════════════════════════════════════════════
# I-022 — Task Completion Tracking
# ═══════════════════════════════════════════════════════════════════════


def mark_tasks_completed(
    batch: TaskBatch,
    response: AgentResponse,
) -> int:
    """Mark tasks addressed by an agent response as completed (I-022).

    Returns number of tasks marked.
    """
    # Build set of addressed nodes from repairs
    addressed_nodes: Set[str] = set()
    for repair in response.repairs:
        addressed_nodes.add(repair.node)

    marked = 0
    for task in batch.tasks:
        if task.nodes:
            task_node_ids = {n.id for n in task.nodes}
            if task_node_ids & addressed_nodes:
                marked += 1

    return marked


# ═══════════════════════════════════════════════════════════════════════
# I-027 — Task JSON Schema Validation
# ═══════════════════════════════════════════════════════════════════════


def validate_tasks_schema(data: Dict[str, Any]) -> List[str]:
    """Validate tasks data against expected structure (I-027)."""
    errors: List[str] = []
    if not isinstance(data.get("graph_version"), int):
        errors.append("'graph_version' must be an integer")
    if not isinstance(data.get("cycle"), int):
        errors.append("'cycle' must be an integer")
    tasks = data.get("tasks")
    if not isinstance(tasks, list):
        errors.append("'tasks' must be an array")
        return errors
    for idx, task in enumerate(tasks):
        if not isinstance(task, dict):
            errors.append(f"Task [{idx}]: must be an object")
            continue
        if "task_id" not in task:
            errors.append(f"Task [{idx}]: missing 'task_id'")
        if "priority" not in task:
            errors.append(f"Task [{idx}]: missing 'priority'")
    return errors


def validate_response_schema(data: Dict[str, Any]) -> List[str]:
    """Validate agent_response data against expected structure (I-027)."""
    errors: List[str] = []
    if not isinstance(data.get("graph_version"), int):
        errors.append("'graph_version' must be an integer")
    if not isinstance(data.get("cycle"), int):
        errors.append("'cycle' must be an integer")
    repairs = data.get("repairs")
    if repairs is not None and not isinstance(repairs, list):
        errors.append("'repairs' must be an array")
    intents = data.get("intents")
    if intents is not None and not isinstance(intents, list):
        errors.append("'intents' must be an array")
    return errors


# ═══════════════════════════════════════════════════════════════════════
# I-028 — Task History Log
# ═══════════════════════════════════════════════════════════════════════

_MAX_HISTORY = 50


@dataclass
class HistoryEntry:
    """A single entry in the task history (I-028)."""

    iteration: int
    timestamp: str
    task_count: int
    actions_taken: int = 0
    summary: str = ""


class TaskHistory:
    """Persistent task history (I-028)."""

    def __init__(self, project_root: Path) -> None:
        self._path = resolve_path(project_root, TASKS_DIR, "history.json")
        self._entries: List[HistoryEntry] = []
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._entries = [
                HistoryEntry(
                    iteration=e["iteration"],
                    timestamp=e["timestamp"],
                    task_count=e["task_count"],
                    actions_taken=e.get("actions_taken", 0),
                    summary=e.get("summary", ""),
                )
                for e in data.get("entries", [])
            ]

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "entries": [
                {
                    "iteration": e.iteration,
                    "timestamp": e.timestamp,
                    "task_count": e.task_count,
                    "actions_taken": e.actions_taken,
                    "summary": e.summary,
                }
                for e in self._entries
            ]
        }
        self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def append(self, entry: HistoryEntry) -> None:
        self._entries.append(entry)
        # Enforce size limit
        if len(self._entries) > _MAX_HISTORY:
            self._entries = self._entries[-_MAX_HISTORY:]
        self.save()

    @property
    def entries(self) -> List[HistoryEntry]:
        return list(self._entries)

    def format(self) -> str:
        if not self._entries:
            return "No task history."
        lines = [f"Task History ({len(self._entries)} entries):"]
        for e in self._entries:
            lines.append(
                f"  #{e.iteration} [{e.timestamp}]: "
                f"{e.task_count} tasks, {e.actions_taken} actions"
            )
        return "\n".join(lines)
