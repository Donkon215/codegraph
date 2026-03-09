"""codegraph.planning — Agent planning layer for multi-step repairs.

Generates structured plans from task batches, validates plan feasibility,
and tracks plan execution progress.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from codegraph.logging_config import get_logger

logger = get_logger("planning")


@dataclass
class PlanStep:
    """A single step in an agent repair plan."""

    step_id: int = 0
    action: str = ""  # "add_intent", "flag_orphan", "connect_call", "remove_dead_code"
    node_id: str = ""
    target: Optional[str] = None
    description: str = ""
    depends_on: List[int] = field(default_factory=list)
    status: str = "pending"  # "pending", "in_progress", "completed", "failed"

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "step_id": self.step_id,
            "action": self.action,
            "node_id": self.node_id,
            "description": self.description,
            "status": self.status,
        }
        if self.target:
            d["target"] = self.target
        if self.depends_on:
            d["depends_on"] = self.depends_on
        return d


@dataclass
class RepairPlan:
    """A structured multi-step repair plan for the agent."""

    plan_id: str = ""
    graph_version: int = 0
    cycle: int = 1
    steps: List[PlanStep] = field(default_factory=list)
    total_intents: int = 0
    total_repairs: int = 0
    total_flags: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "graph_version": self.graph_version,
            "cycle": self.cycle,
            "steps": [s.to_dict() for s in self.steps],
            "summary": {
                "total_steps": len(self.steps),
                "total_intents": self.total_intents,
                "total_repairs": self.total_repairs,
                "total_flags": self.total_flags,
            },
        }

    def to_json(self, compact: bool = False) -> str:
        indent = None if compact else 2
        return json.dumps(self.to_dict(), indent=indent)

    def format(self) -> str:
        lines = [
            f"Plan {self.plan_id} (cycle {self.cycle}, graph v{self.graph_version})",
            f"  Steps: {len(self.steps)}",
            f"  Intents: {self.total_intents}  Repairs: {self.total_repairs}  Flags: {self.total_flags}",
        ]
        if self.steps:
            lines.append("\nSteps:")
            for s in self.steps[:20]:
                dep = f" (after {s.depends_on})" if s.depends_on else ""
                lines.append(f"  {s.step_id}. [{s.action}] {s.node_id}{dep}")
                if s.description:
                    lines.append(f"      {s.description}")
        if len(self.steps) > 20:
            lines.append(f"  … and {len(self.steps) - 20} more steps")
        return "\n".join(lines)


def generate_plan(
    tasks_data: Dict[str, Any],
    graph_version: int,
    cycle: int = 1,
) -> RepairPlan:
    """Generate a repair plan from a tasks batch.

    Reads the tasks.json structure and creates an ordered plan
    with dependency tracking.
    """
    plan = RepairPlan(
        plan_id=f"plan_c{cycle}_v{graph_version}",
        graph_version=graph_version,
        cycle=cycle,
    )

    tasks = tasks_data.get("tasks", [])
    step_id = 1

    # Sort tasks by priority (lower = higher priority)
    tasks.sort(key=lambda t: t.get("priority", 99))

    for task in tasks:
        task_id = task.get("task_id", "")
        nodes = task.get("nodes", [])
        priority = task.get("priority", 10)

        if "intent_missing" in task_id:
            for node_id in nodes:
                plan.steps.append(PlanStep(
                    step_id=step_id,
                    action="add_intent",
                    node_id=node_id,
                    description=f"Read source code and write intent for {node_id}",
                ))
                plan.total_intents += 1
                step_id += 1

        elif "orphan" in task_id:
            for node_id in nodes:
                plan.steps.append(PlanStep(
                    step_id=step_id,
                    action="flag_orphan",
                    node_id=node_id,
                    description=f"Classify orphan: entry_point, dead_code, or review",
                ))
                plan.total_flags += 1
                step_id += 1

        elif "policy_violation" in task_id:
            for node_id in nodes:
                target = task.get("details", {}).get("target", "")
                plan.steps.append(PlanStep(
                    step_id=step_id,
                    action="connect_call",
                    node_id=node_id,
                    target=target,
                    description=f"Add call from {node_id} to {target} per policy",
                ))
                plan.total_repairs += 1
                step_id += 1

        elif "stale_intent" in task_id:
            for node_id in nodes:
                plan.steps.append(PlanStep(
                    step_id=step_id,
                    action="update_intent",
                    node_id=node_id,
                    description=f"Re-read source and update intent for {node_id}",
                ))
                plan.total_intents += 1
                step_id += 1

        elif "missing_import" in task_id or "missing_edge" in task_id:
            for node_id in nodes:
                plan.steps.append(PlanStep(
                    step_id=step_id,
                    action="flag_for_review",
                    node_id=node_id,
                    description=f"Review missing edge for {node_id}",
                ))
                plan.total_flags += 1
                step_id += 1

        elif "coverage_gap" in task_id:
            for node_id in nodes:
                plan.steps.append(PlanStep(
                    step_id=step_id,
                    action="flag_for_review",
                    node_id=node_id,
                    description=f"Review coverage gap for {node_id}",
                ))
                plan.total_flags += 1
                step_id += 1

    return plan


def validate_plan(plan: RepairPlan) -> List[str]:
    """Validate a repair plan for consistency.

    Returns a list of issues found (empty = valid).
    """
    issues: List[str] = []

    # Check step IDs are unique
    seen_ids = set()
    for step in plan.steps:
        if step.step_id in seen_ids:
            issues.append(f"Duplicate step_id: {step.step_id}")
        seen_ids.add(step.step_id)

    # Check dependency references exist
    for step in plan.steps:
        for dep in step.depends_on:
            if dep not in seen_ids:
                issues.append(f"Step {step.step_id} depends on non-existent step {dep}")

    # Check graph version is set
    if plan.graph_version <= 0:
        issues.append("graph_version not set")

    return issues


def save_plan(plan: RepairPlan, project_root: Path) -> Path:
    """Save a repair plan to .codegraph/plans/."""
    plans_dir = project_root / ".codegraph" / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    path = plans_dir / f"{plan.plan_id}.json"
    path.write_text(plan.to_json(), encoding="utf-8")
    return path


def load_plan(project_root: Path, plan_id: str) -> Optional[RepairPlan]:
    """Load a named plan from .codegraph/plans/."""
    path = project_root / ".codegraph" / "plans" / f"{plan_id}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    plan = RepairPlan(
        plan_id=data.get("plan_id", ""),
        graph_version=data.get("graph_version", 0),
        cycle=data.get("cycle", 1),
    )
    summary = data.get("summary", {})
    plan.total_intents = summary.get("total_intents", 0)
    plan.total_repairs = summary.get("total_repairs", 0)
    plan.total_flags = summary.get("total_flags", 0)
    for sd in data.get("steps", []):
        plan.steps.append(PlanStep(
            step_id=sd.get("step_id", 0),
            action=sd.get("action", ""),
            node_id=sd.get("node_id", ""),
            target=sd.get("target"),
            description=sd.get("description", ""),
            depends_on=sd.get("depends_on", []),
            status=sd.get("status", "pending"),
        ))
    return plan
