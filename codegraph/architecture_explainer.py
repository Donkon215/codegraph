"""codegraph.architecture_explainer — Explainability engine for architecture insights."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class ArchitectureExplanation:
    subject: str
    metrics: Dict[str, float] = field(default_factory=dict)
    analysis: str = ""
    recommendation_reason: str = ""
    confidence: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "subject": self.subject,
            "metrics": {k: round(v, 4) for k, v in self.metrics.items()},
            "analysis": self.analysis,
            "recommendation_reason": self.recommendation_reason,
            "confidence": round(self.confidence, 3),
        }


def explain_microservice_candidate(candidate: Dict[str, Any]) -> ArchitectureExplanation:
    metrics = candidate.get("metrics", {})
    cohesion = float(candidate.get("cohesion_score", 0.0))
    coupling = float(candidate.get("coupling_score", 0.0))
    subject = candidate.get("subsystem_name", "microservice_candidate")

    analysis = (
        f"Cluster {subject} shows high internal cohesion ({cohesion:.2f}) "
        f"and low coupling ({coupling:.2f})."
    )
    reason = (
        "Strong internal interaction with constrained external dependencies "
        "indicates safe service boundary extraction potential."
    )
    confidence = float(candidate.get("confidence", 0.0))

    return ArchitectureExplanation(
        subject=subject,
        metrics={
            "cohesion": cohesion,
            "coupling": coupling,
            "cluster_size": float(metrics.get("cluster_size", 0.0)),
            "api_surface": float(len(candidate.get("api_surface", []))),
        },
        analysis=analysis,
        recommendation_reason=reason,
        confidence=confidence,
    )


def explain_refactor_plan(plan: Dict[str, Any]) -> ArchitectureExplanation:
    steps = plan.get("steps", [])
    problem_type = plan.get("problem_type", "unknown")
    estimated = float(plan.get("estimated_score_delta", 0.0))
    confidence = float(plan.get("confidence", 0.0))
    subject = plan.get("plan_id", "plan")

    analysis = (
        f"Plan addresses {problem_type} with {len(steps)} ordered transformations "
        f"to minimize disruption and preserve behavior."
    )
    reason = (
        f"Stepwise migration reduces architectural risk while targeting expected score "
        f"improvement of {estimated:.3f}."
    )

    return ArchitectureExplanation(
        subject=subject,
        metrics={
            "step_count": float(len(steps)),
            "estimated_score_delta": estimated,
        },
        analysis=analysis,
        recommendation_reason=reason,
        confidence=confidence,
    )


def explain_architecture_pattern(pattern_report: Dict[str, Any]) -> ArchitectureExplanation:
    architecture_type = pattern_report.get("architecture_type", "unknown")
    confidence = float(pattern_report.get("confidence", 0.0))
    violations = pattern_report.get("violations", [])
    analysis = (
        f"Pattern classifier selected '{architecture_type}' based on graph topology "
        f"with confidence {confidence:.2f}."
    )
    reason = (
        f"Detected {len(violations)} pattern violations/anti-pattern edges influencing the decision."
    )
    return ArchitectureExplanation(
        subject=f"pattern:{architecture_type}",
        metrics={
            "confidence": confidence,
            "violations": float(len(violations)),
        },
        analysis=analysis,
        recommendation_reason=reason,
        confidence=confidence,
    )


def explain_decay_report(decay_report: Dict[str, Any]) -> ArchitectureExplanation:
    god_modules = float(len(decay_report.get("god_modules", [])))
    cyclic = float(len(decay_report.get("cyclic_subsystems", [])))
    dead = float(len(decay_report.get("dead_subsystems", [])))
    coupling = float(decay_report.get("coupling_index", 0.0))
    analysis = (
        f"Decay signals detected across god modules ({int(god_modules)}), cycles ({int(cyclic)}), "
        f"and dead subsystems ({int(dead)})."
    )
    reason = "These indicators suggest architectural drift and motivate targeted refactoring plans."
    confidence = min(1.0, 0.4 + (god_modules + cyclic + dead) * 0.05)
    return ArchitectureExplanation(
        subject="architecture_decay",
        metrics={
            "god_modules": god_modules,
            "cyclic_subsystems": cyclic,
            "dead_subsystems": dead,
            "coupling_index": coupling,
        },
        analysis=analysis,
        recommendation_reason=reason,
        confidence=confidence,
    )


def generate_explanations(
    *,
    pattern_report: Dict[str, Any],
    decay_report: Dict[str, Any],
    microservice_candidates: List[Dict[str, Any]],
    refactor_plans: List[Dict[str, Any]],
) -> List[ArchitectureExplanation]:
    explanations: List[ArchitectureExplanation] = []
    explanations.append(explain_architecture_pattern(pattern_report))
    explanations.append(explain_decay_report(decay_report))

    for candidate in microservice_candidates[:5]:
        explanations.append(explain_microservice_candidate(candidate))

    for plan in refactor_plans[:5]:
        explanations.append(explain_refactor_plan(plan))

    explanations.sort(key=lambda explanation: explanation.confidence, reverse=True)
    return explanations
