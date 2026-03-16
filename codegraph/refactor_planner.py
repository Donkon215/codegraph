"""codegraph.refactor_planner — Multi-step architecture repair planning."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from codegraph.dependency_inversion import DependencyInversionSuggestion
from codegraph.index import IndexStore
from codegraph.simulator import (
    simulate_dependency_inversion,
    simulate_subsystem_extraction,
)


@dataclass
class RefactorStep:
    step_number: int
    action: str
    target_nodes: List[str]
    description: str
    expected_effect: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_number": self.step_number,
            "action": self.action,
            "target_nodes": self.target_nodes,
            "description": self.description,
            "expected_effect": self.expected_effect,
        }


@dataclass
class RefactorPlan:
    plan_id: str
    problem_type: str
    steps: List[RefactorStep] = field(default_factory=list)
    estimated_score_delta: float = 0.0
    confidence: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "problem_type": self.problem_type,
            "steps": [step.to_dict() for step in self.steps],
            "estimated_score_delta": round(self.estimated_score_delta, 4),
            "confidence": round(self.confidence, 3),
        }


def _cycle_plan(plan_id: str, modules: List[str]) -> RefactorPlan:
    return RefactorPlan(
        plan_id=plan_id,
        problem_type="cyclic_subsystem",
        steps=[
            RefactorStep(
                step_number=1,
                action="introduce_interface",
                target_nodes=modules[:2],
                description="Define interface abstraction to break direct cycle coupling",
                expected_effect="decouples concrete implementation dependencies",
            ),
            RefactorStep(
                step_number=2,
                action="invert_dependency",
                target_nodes=modules,
                description="Point high-level modules to interface instead of concrete modules",
                expected_effect="dependency direction follows architectural layers",
            ),
            RefactorStep(
                step_number=3,
                action="move_implementation",
                target_nodes=modules,
                description="Isolate concrete implementation behind interface boundary",
                expected_effect="removes bidirectional compile-time coupling",
            ),
            RefactorStep(
                step_number=4,
                action="remove_cycle",
                target_nodes=modules,
                description="Delete obsolete direct calls creating SCC loop",
                expected_effect="cycle cluster eliminated",
            ),
        ],
        confidence=0.78,
    )


def _extract_plan(plan_id: str, modules: List[str]) -> RefactorPlan:
    return RefactorPlan(
        plan_id=plan_id,
        problem_type="extractable_subsystem",
        steps=[
            RefactorStep(
                step_number=1,
                action="define_service_boundary",
                target_nodes=modules,
                description="Create explicit module boundary and API contract",
                expected_effect="limits accidental external coupling",
            ),
            RefactorStep(
                step_number=2,
                action="extract_subsystem",
                target_nodes=modules,
                description="Move cohesive modules into dedicated subsystem package",
                expected_effect="increases modularity and subsystem isolation",
            ),
            RefactorStep(
                step_number=3,
                action="redirect_dependencies",
                target_nodes=modules,
                description="Update callers to consume extracted subsystem API",
                expected_effect="reduces cross-subsystem edges",
            ),
        ],
        confidence=0.8,
    )


def _dependency_inversion_plan(
    plan_id: str,
    suggestion: DependencyInversionSuggestion,
) -> RefactorPlan:
    return RefactorPlan(
        plan_id=plan_id,
        problem_type="dependency_inversion",
        steps=[
            RefactorStep(
                step_number=1,
                action="introduce_interface",
                target_nodes=[suggestion.interface_name],
                description=f"Introduce interface {suggestion.interface_name}",
                expected_effect="decouples high-level policy from low-level details",
            ),
            RefactorStep(
                step_number=2,
                action="invert_dependency",
                target_nodes=[suggestion.source_node, suggestion.target_node],
                description=(
                    f"Redirect {suggestion.source_node} to depend on {suggestion.interface_name}"
                ),
                expected_effect="removes direct high->low dependency",
            ),
            RefactorStep(
                step_number=3,
                action="bind_implementation",
                target_nodes=[suggestion.target_node, suggestion.interface_name],
                description=(
                    f"Make {suggestion.target_node} implement {suggestion.interface_name}"
                ),
                expected_effect="restores behavior through abstraction",
            ),
        ],
        confidence=suggestion.confidence,
    )


def _estimate_plan_delta(
    plan: RefactorPlan,
    index: IndexStore,
    project_root: Optional[Path],
) -> float:
    if not plan.steps:
        return 0.0

    first_step = plan.steps[0]
    if first_step.action == "define_service_boundary":
        result = simulate_subsystem_extraction(index, first_step.target_nodes, project_root=project_root)
        return max(0.0, result.score_delta)

    if first_step.action == "introduce_interface" and len(plan.steps) >= 2:
        second = plan.steps[1]
        if second.target_nodes and len(second.target_nodes) >= 2:
            source = second.target_nodes[0]
            target = second.target_nodes[1]
            iface = first_step.target_nodes[0] if first_step.target_nodes else "Interface"
            result = simulate_dependency_inversion(index, source, target, iface, project_root=project_root)
            return max(0.0, result.score_delta)

    return 0.01


def generate_refactor_plans(
    architecture_decay_report: Dict[str, Any],
    architecture_detection_report: Dict[str, Any],
    subsystem_clusters: List[Dict[str, Any]],
    *,
    index: Optional[IndexStore] = None,
    dependency_inversions: Optional[List[DependencyInversionSuggestion]] = None,
    project_root: Optional[Path] = None,
) -> List[RefactorPlan]:
    """Generate ordered multi-step repair plans from architecture findings."""
    plans: List[RefactorPlan] = []
    plan_counter = 1

    for cluster in architecture_decay_report.get("cyclic_subsystems", [])[:5]:
        modules = cluster.get("modules", [])
        if not modules:
            continue
        plans.append(_cycle_plan(f"plan-cycle-{plan_counter}", modules))
        plan_counter += 1

    for candidate in subsystem_clusters[:5]:
        modules = candidate.get("nodes", [])
        if len(modules) < 2:
            continue
        plans.append(_extract_plan(f"plan-extract-{plan_counter}", modules))
        plan_counter += 1

    for suggestion in dependency_inversions or []:
        plans.append(_dependency_inversion_plan(f"plan-invert-{plan_counter}", suggestion))
        plan_counter += 1

    if index is not None:
        for plan in plans:
            plan.estimated_score_delta = _estimate_plan_delta(plan, index, project_root)

    plans.sort(key=lambda plan: (plan.estimated_score_delta, plan.confidence), reverse=True)
    return plans
