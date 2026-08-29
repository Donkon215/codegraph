"""codegraph.code_planner — Architecture-aware code implementation planner.

Converts architecture deltas and compiled plans into concrete code
implementation tasks. Ensures Copilot follows architecture rules
rather than improvising randomly.

The planner bridges architecture changes and code changes:

    architecture_delta / plan  →  CodePlan  →  ordered implementation tasks

Output is a .plan.json file containing:
  - create_file tasks
  - create_function tasks
  - add_import tasks
  - add_test tasks
  - update_architecture tasks
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from codegraph.arch_schema import SystemArchitecture
from codegraph.logging_config import get_logger
from codegraph.architecture_delta import ArchitectureDelta
from codegraph.target_architecture import TargetWorkflow

logger = get_logger("code_planner")

PLAN_FILE = ".plan.json"


# ── Plan Task ──────────────────────────────────────────────────────────


@dataclass
class PlanTask:
    """A single task in a code implementation plan."""

    task_type: str  # "create_file", "create_function", "add_import",
    #                 "add_test", "update_architecture", "modify_file"
    target: str  # file path or node ID
    description: str = ""
    subsystem: str = ""
    depends_on: List[str] = field(default_factory=list)  # task IDs
    priority: int = 5  # 1=highest
    task_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "task_type": self.task_type,
            "target": self.target,
        }
        if self.task_id:
            d["task_id"] = self.task_id
        if self.description:
            d["description"] = self.description
        if self.subsystem:
            d["subsystem"] = self.subsystem
        if self.depends_on:
            d["depends_on"] = self.depends_on
        if self.priority != 5:
            d["priority"] = self.priority
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> PlanTask:
        return cls(
            task_type=d["task_type"],
            target=d["target"],
            description=d.get("description", ""),
            subsystem=d.get("subsystem", ""),
            depends_on=d.get("depends_on", []),
            priority=d.get("priority", 5),
            task_id=d.get("task_id", ""),
        )


# ── Code Plan ──────────────────────────────────────────────────────────


@dataclass
class CodePlan:
    """Complete code implementation plan.

    Produced by generate_plan() and consumed by Copilot to implement
    architecture changes in the correct order.
    """

    description: str = ""
    tasks: List[PlanTask] = field(default_factory=list)
    architecture_changes: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def task_count(self) -> int:
        return len(self.tasks)

    @property
    def tasks_by_type(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for t in self.tasks:
            counts[t.task_type] = counts.get(t.task_type, 0) + 1
        return counts

    def to_dict(self) -> Dict[str, Any]:
        return {
            "description": self.description,
            "summary": {
                "total_tasks": self.task_count,
                "by_type": self.tasks_by_type,
                "warnings": len(self.warnings),
            },
            "tasks": [t.to_dict() for t in self.tasks],
            "architecture_changes": self.architecture_changes,
            "warnings": self.warnings,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> CodePlan:
        tasks = [PlanTask.from_dict(t) for t in d.get("tasks", [])]
        return cls(
            description=d.get("description", ""),
            tasks=tasks,
            architecture_changes=d.get("architecture_changes", []),
            warnings=d.get("warnings", []),
        )

    def save(self, project_root: Path) -> Path:
        path = project_root / ".codegraph" / "planning" / PLAN_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("Saved code plan → %s", path)
        return path

    @classmethod
    def load(cls, project_root: Path) -> Optional[CodePlan]:
        path = project_root / ".codegraph" / "planning" / PLAN_FILE
        if not path.exists():
            return None
        text = path.read_text(encoding="utf-8")
        return cls.from_dict(json.loads(text))

    def format(self) -> str:
        lines = [f"Code Plan: {self.description}"]
        lines.append(f"  Total tasks: {self.task_count}")
        by_type = self.tasks_by_type
        if by_type:
            lines.append("  By type: " + ", ".join(
                f"{k}={v}" for k, v in sorted(by_type.items())
            ))
        if self.tasks:
            lines.append("\nTasks (ordered):")
            for i, t in enumerate(self.tasks, 1):
                dep_str = ""
                if t.depends_on:
                    dep_str = f" (after: {', '.join(t.depends_on)})"
                lines.append(
                    f"  {i}. [{t.task_type}] {t.target}"
                    f" — {t.description}{dep_str}"
                )
        if self.warnings:
            lines.append("\nWarnings:")
            for w in self.warnings:
                lines.append(f"  ⚠ {w}")
        return "\n".join(lines)

    def ordered_tasks(self) -> List[PlanTask]:
        """Return tasks sorted by priority then dependency order."""
        # Simple topological-ish sort: priority first, then by dependency
        id_to_task: Dict[str, PlanTask] = {}
        for t in self.tasks:
            if t.task_id:
                id_to_task[t.task_id] = t

        result: List[PlanTask] = []
        visited: Set[str] = set()

        def _visit(task: PlanTask) -> None:
            tid = task.task_id or id(task)
            if tid in visited:
                return
            visited.add(tid)
            for dep_id in task.depends_on:
                if dep_id in id_to_task and dep_id not in visited:
                    _visit(id_to_task[dep_id])
            result.append(task)

        for t in sorted(self.tasks, key=lambda x: x.priority):
            _visit(t)
        return result


# ── Plan Generation ────────────────────────────────────────────────────


def generate_plan(
    delta: ArchitectureDelta,
    architecture: SystemArchitecture,
    *,
    target: Optional[TargetWorkflow] = None,
) -> CodePlan:
    """Generate a code plan from an architecture delta.

    Analyzes the delta (added/removed nodes and edges) and
    produces ordered tasks for Copilot to implement.
    """
    plan = CodePlan(description="Plan from architecture delta")
    task_counter = 0

    # Build module→subsystem mapping
    mod_to_sub = _build_module_mapping(architecture)

    # 1. Added nodes → create_file + create_function tasks
    for node_info in delta.added_nodes:
        node_id = node_info.node_id
        module = node_info.module
        subsystem = node_info.subsystem

        if module:
            task_counter += 1
            file_task_id = f"t{task_counter:03d}"
            plan.tasks.append(PlanTask(
                task_type="create_file",
                target=module,
                description=f"Create module {module}",
                subsystem=subsystem,
                priority=1,
                task_id=file_task_id,
            ))

        if node_id and "::" in node_id:
            task_counter += 1
            plan.tasks.append(PlanTask(
                task_type="create_function",
                target=node_id,
                description=f"Implement {node_id}",
                subsystem=subsystem,
                priority=2,
                task_id=f"t{task_counter:03d}",
                depends_on=[file_task_id] if module else [],
            ))

        # Add test for new nodes
        if module:
            task_counter += 1
            test_path = _module_to_test(module)
            plan.tasks.append(PlanTask(
                task_type="add_test",
                target=test_path,
                description=f"Add tests for {module}",
                subsystem=subsystem,
                priority=4,
                task_id=f"t{task_counter:03d}",
                depends_on=[file_task_id] if module else [],
            ))

    # 2. Added edges → add_import tasks
    for edge_info in delta.added_edges:
        source = edge_info.source
        target_node = edge_info.target
        if source and target_node:
            task_counter += 1
            plan.tasks.append(PlanTask(
                task_type="add_import",
                target=source,
                description=f"Connect {source} → {target_node}",
                subsystem=mod_to_sub.get(
                    source.split("::")[0] if "::" in source else source, ""
                ),
                priority=3,
                task_id=f"t{task_counter:03d}",
            ))

    # 3. Removed edges → flag for removal
    for edge_info in delta.removed_edges:
        source = edge_info.source
        target_node = edge_info.target
        if source and target_node:
            task_counter += 1
            plan.tasks.append(PlanTask(
                task_type="modify_file",
                target=source,
                description=f"Remove dependency {source} → {target_node}",
                priority=3,
                task_id=f"t{task_counter:03d}",
            ))

    # 4. Architecture file updates
    if delta.added_nodes or delta.removed_nodes:
        task_counter += 1
        plan.tasks.append(PlanTask(
            task_type="update_architecture",
            target=".codegraph/architecture/system.json",
            description="Update architecture definition to match changes",
            priority=5,
            task_id=f"t{task_counter:03d}",
        ))

    return plan


def validate_plan(
    plan: CodePlan,
    architecture: SystemArchitecture,
) -> List[str]:
    """Validate a code plan against architecture constraints.

    Returns a list of violation descriptions. Empty list means valid.
    """
    violations: List[str] = []

    # Build constraint map
    forbidden: List[tuple[str, str]] = []
    for c in architecture.constraints:
        if c.constraint_type == "forbidden":
            forbidden.append((c.source, c.target))

    # Build subsystem→modules mapping
    sub_modules: Dict[str, Set[str]] = {}
    for s in architecture.subsystems:
        sub_modules[s.name] = set(s.module_paths)

    # Check each add_import task for constraint violations
    for task in plan.tasks:
        if task.task_type == "add_import" and task.subsystem:
            # The task's subsystem is the source
            # Try to infer target subsystem from description
            for forbidden_src, forbidden_tgt in forbidden:
                if task.subsystem == forbidden_src:
                    # Check if the target is in a forbidden subsystem
                    desc_lower = task.description.lower()
                    if forbidden_tgt in desc_lower:
                        violations.append(
                            f"Task {task.task_id}: import from "
                            f"{task.subsystem} → {forbidden_tgt} is forbidden "
                            f"({task.description})"
                        )

    return violations


# ── Helpers ────────────────────────────────────────────────────────────


def _build_module_mapping(
    architecture: SystemArchitecture,
) -> Dict[str, str]:
    """Build module_path → subsystem_name mapping."""
    mapping: Dict[str, str] = {}
    for s in architecture.subsystems:
        for c in s.components:
            if c.module:
                mapping[c.module] = s.name
    return mapping


def _module_to_test(module_path: str) -> str:
    """Convert a module path to its expected test file path."""
    p = Path(module_path)
    name = p.stem
    return f"tests/test_{name}.py"
