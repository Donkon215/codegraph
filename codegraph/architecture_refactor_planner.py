from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from codegraph.architecture_graph import ArchitectureGraph
from codegraph.architecture_health import build_health_report
from codegraph.architecture_smells import detect_architecture_smells


@dataclass
class RefactorSuggestion:
    problem: str
    component: str
    suggested_actions: List[str] = field(default_factory=list)
    expected_score_delta: str = "+0.00"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "problem": self.problem,
            "component": self.component,
            "suggested_actions": self.suggested_actions,
            "expected_score_delta": self.expected_score_delta,
        }


@dataclass
class ArchitectureViolation:
    violation: str
    source: str
    target: str
    reason: str
    recommended_fix: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "violation": self.violation,
            "source": self.source,
            "target": self.target,
            "reason": self.reason,
            "recommended_fix": self.recommended_fix,
        }


def detect_architecture_violations(project_root: Path, max_items: int = 50) -> List[ArchitectureViolation]:
    workflow_path = project_root / ".codegraph" / "workflow" / "workflow.json"
    rules_path = project_root / ".codegraph" / "workflow" / "suggested_workflow.json"

    if not workflow_path.exists() or not rules_path.exists():
        return []

    try:
        workflow_data = json.loads(workflow_path.read_text(encoding="utf-8"))
        rules_data = json.loads(rules_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    edges = workflow_data.get("edges", [])
    rules = rules_data.get("rules", [])

    violations: List[ArchitectureViolation] = []
    for rule in rules:
        rule_type = rule.get("type", "")
        source_pat = rule.get("source", "")
        target_pat = rule.get("target", "")

        if rule_type == "layer_boundary":
            for edge in edges:
                source = edge.get("source", "")
                target = edge.get("target", "")
                if fnmatch.fnmatch(source, source_pat) and fnmatch.fnmatch(target, target_pat):
                    violations.append(
                        ArchitectureViolation(
                            violation="layer_boundary",
                            source=source,
                            target=target,
                            reason=rule.get("reason", "layer boundary violation"),
                            recommended_fix="introduce service layer",
                        )
                    )
        elif rule_type == "forbidden_call":
            for edge in edges:
                source = edge.get("source", "")
                target = edge.get("target", "")
                if fnmatch.fnmatch(source, source_pat) and fnmatch.fnmatch(target, target_pat):
                    violations.append(
                        ArchitectureViolation(
                            violation="forbidden_call",
                            source=source,
                            target=target,
                            reason=rule.get("reason", "forbidden dependency"),
                            recommended_fix="introduce dependency inversion",
                        )
                    )

        if len(violations) >= max_items:
            break

    return violations[:max_items]


def _compute_fanout(workflow_edges: List[Any]) -> Dict[str, int]:
    fanout: Dict[str, int] = {}
    for edge in workflow_edges:
        fanout[edge.source] = fanout.get(edge.source, 0) + 1
    return fanout


def generate_refactor_plan(project_root: Path, max_items: int = 10) -> Dict[str, Any]:
    arch = ArchitectureGraph.load(project_root)
    smells = detect_architecture_smells(arch, project_root)
    health = build_health_report(project_root)
    fanout = _compute_fanout(arch.workflow_graph.edges)

    suggestions: List[RefactorSuggestion] = []

    for node_id, out_degree in sorted(fanout.items(), key=lambda x: x[1], reverse=True):
        if out_degree < 15:
            continue

        short_name = node_id.split("::")[-1]
        actions = [
            f"extract {short_name}Validator",
            f"extract {short_name}Repository",
            f"extract {short_name}Adapter",
        ]
        suggestions.append(
            RefactorSuggestion(
                problem="high fan-out",
                component=node_id,
                suggested_actions=actions,
                expected_score_delta="+0.04",
            )
        )

    for smell in smells.smells:
        if smell.smell_type == "dependency_cycles":
            suggestions.append(
                RefactorSuggestion(
                    problem="dependency cycle",
                    component=smell.node or "service_layer",
                    suggested_actions=["introduce EventBus", "split cyclic dependency through domain events"],
                    expected_score_delta="+0.03",
                )
            )
        if smell.smell_type == "cross_layer_dependencies":
            suggestions.append(
                RefactorSuggestion(
                    problem="layer violation",
                    component=smell.node or "controller_to_repository",
                    suggested_actions=["introduce Service layer", "move repository access behind service facade"],
                    expected_score_delta="+0.02",
                )
            )

    if health.cycle_count > 0 and not any(s.problem == "dependency cycle" for s in suggestions):
        suggestions.append(
            RefactorSuggestion(
                problem="dependency cycle",
                component="service_layer",
                suggested_actions=["introduce EventBus"],
                expected_score_delta="+0.02",
            )
        )

    deduped: Dict[str, RefactorSuggestion] = {}
    for suggestion in suggestions:
        key = f"{suggestion.problem}:{suggestion.component}"
        if key not in deduped:
            deduped[key] = suggestion

    final_suggestions = list(deduped.values())[:max_items]
    violations = [v.to_dict() for v in detect_architecture_violations(project_root, max_items=max_items)]

    return {
        "refactor_plan": [item.to_dict() for item in final_suggestions],
        "architecture_violations": violations,
        "summary": {
            "suggestions": len(final_suggestions),
            "violations": len(violations),
            "critical_smells": smells.critical_smell_count,
        },
    }


def top_refactor_suggestions(project_root: Path, limit: int = 5) -> List[Dict[str, Any]]:
    plan = generate_refactor_plan(project_root, max_items=limit)
    return plan.get("refactor_plan", [])[:limit]
