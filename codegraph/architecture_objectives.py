"""codegraph.architecture_objectives — Goal-directed architecture scoring.

Defines a composite scoring function for ranking evolution candidates:

    score = w_m * modularity
          + w_c * coupling_reduction
          + w_y * cycle_reduction
          + w_a * maintainability

Default weights: 0.4, 0.3, 0.2, 0.1.
Memory intelligence can adjust weights based on historical success.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from codegraph.logging_config import get_logger

logger = get_logger("architecture_objectives")

# Default objective weights
DEFAULT_WEIGHTS: Dict[str, float] = {
    "modularity": 0.4,
    "coupling_reduction": 0.3,
    "cycle_reduction": 0.2,
    "maintainability": 0.1,
}


@dataclass
class ObjectiveWeights:
    """Adjustable weights for the architecture scoring function."""

    modularity: float = 0.4
    coupling_reduction: float = 0.3
    cycle_reduction: float = 0.2
    maintainability: float = 0.1

    def to_dict(self) -> Dict[str, float]:
        return {
            "modularity": self.modularity,
            "coupling_reduction": self.coupling_reduction,
            "cycle_reduction": self.cycle_reduction,
            "maintainability": self.maintainability,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, float]) -> ObjectiveWeights:
        return cls(
            modularity=d.get("modularity", 0.4),
            coupling_reduction=d.get("coupling_reduction", 0.3),
            cycle_reduction=d.get("cycle_reduction", 0.2),
            maintainability=d.get("maintainability", 0.1),
        )

    def normalize(self) -> ObjectiveWeights:
        """Return a copy with weights summing to 1.0."""
        total = (self.modularity + self.coupling_reduction
                 + self.cycle_reduction + self.maintainability)
        if total <= 0:
            return ObjectiveWeights()
        return ObjectiveWeights(
            modularity=self.modularity / total,
            coupling_reduction=self.coupling_reduction / total,
            cycle_reduction=self.cycle_reduction / total,
            maintainability=self.maintainability / total,
        )


@dataclass
class CandidateMetrics:
    """Metrics for a single evolution candidate, used for scoring."""

    modularity: float = 0.0        # internal vs external edges ratio
    coupling_reduction: float = 0.0  # reduction in coupling (0..1)
    cycle_reduction: float = 0.0   # fraction of cycles eliminated (0..1)
    maintainability: float = 0.0   # composite maintainability (0..1)

    def to_dict(self) -> Dict[str, float]:
        return {
            "modularity": round(self.modularity, 4),
            "coupling_reduction": round(self.coupling_reduction, 4),
            "cycle_reduction": round(self.cycle_reduction, 4),
            "maintainability": round(self.maintainability, 4),
        }


@dataclass
class ScoredCandidate:
    """A candidate with its objective score."""

    candidate_id: str
    strategy: str
    target_modules: List[str]
    metrics: CandidateMetrics
    objective_score: float = 0.0
    score_breakdown: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "strategy": self.strategy,
            "target_modules": self.target_modules,
            "objective_score": round(self.objective_score, 4),
            "score_breakdown": {k: round(v, 4)
                                for k, v in self.score_breakdown.items()},
            "metrics": self.metrics.to_dict(),
        }


def compute_objective_score(
    metrics: CandidateMetrics,
    weights: Optional[ObjectiveWeights] = None,
) -> tuple[float, Dict[str, float]]:
    """Compute the composite objective score for a candidate.

    Args:
        metrics: The candidate's architecture metrics.
        weights: Scoring weights. Defaults to DEFAULT_WEIGHTS.

    Returns:
        (total_score, breakdown_dict) where breakdown shows each
        component's weighted contribution.
    """
    w = (weights or ObjectiveWeights()).normalize()

    breakdown = {
        "modularity": w.modularity * metrics.modularity,
        "coupling_reduction": w.coupling_reduction * metrics.coupling_reduction,
        "cycle_reduction": w.cycle_reduction * metrics.cycle_reduction,
        "maintainability": w.maintainability * metrics.maintainability,
    }
    total = sum(breakdown.values())
    return total, breakdown


def score_candidates(
    candidates: List[Dict[str, Any]],
    baseline: Dict[str, Any],
    weights: Optional[ObjectiveWeights] = None,
) -> List[ScoredCandidate]:
    """Score and rank a list of evolution candidates.

    Args:
        candidates: Raw candidate dicts from arch_search.
        baseline: Current architecture metrics (score, coupling, cycles, etc.).
        weights: Scoring weights.

    Returns:
        Candidates sorted by objective score (highest first).
    """
    baseline_score = baseline.get("score", 0.0)
    baseline_coupling = baseline.get("coupling", 0.0)
    baseline_cycles = baseline.get("cycles", 0)

    scored: List[ScoredCandidate] = []

    for cand in candidates:
        predicted = cand.get("predicted_score", baseline_score)
        predicted_coupling = cand.get("predicted_coupling", baseline_coupling)
        predicted_cycles = cand.get("predicted_cycles", baseline_cycles)

        # Modularity: predicted score improvement (0..1 normalized)
        mod_score = max(0.0, min(1.0, predicted))

        # Coupling reduction: how much coupling decreased (0..1)
        if baseline_coupling > 0:
            coupling_red = max(0.0, min(1.0,
                (baseline_coupling - predicted_coupling) / baseline_coupling))
        else:
            coupling_red = 1.0 if predicted_coupling == 0 else 0.0

        # Cycle reduction: fraction of cycles eliminated
        if baseline_cycles > 0:
            cycle_red = max(0.0, min(1.0,
                (baseline_cycles - predicted_cycles) / baseline_cycles))
        else:
            cycle_red = 1.0

        # Maintainability: composite of fan-out control + god module avoidance
        fan_out = cand.get("predicted_max_fan_out", 15)
        god_modules = cand.get("predicted_god_modules", 0)
        maint = max(0.0, 1.0 - (fan_out / 50.0) - (god_modules * 0.1))

        metrics = CandidateMetrics(
            modularity=mod_score,
            coupling_reduction=coupling_red,
            cycle_reduction=cycle_red,
            maintainability=maint,
        )

        total, breakdown = compute_objective_score(metrics, weights)

        scored.append(ScoredCandidate(
            candidate_id=cand.get("candidate_id", ""),
            strategy=cand.get("strategy", ""),
            target_modules=cand.get("target_modules", []),
            metrics=metrics,
            objective_score=total,
            score_breakdown=breakdown,
        ))

    scored.sort(key=lambda s: s.objective_score, reverse=True)
    return scored


def reject_degrading_candidates(
    scored: List[ScoredCandidate],
    baseline_score: float,
    threshold: float = 0.0,
) -> List[ScoredCandidate]:
    """Filter out candidates whose modularity score is worse than baseline.

    Args:
        scored: Scored candidates.
        baseline_score: Current architecture score.
        threshold: Minimum acceptable score (default: match baseline).

    Returns:
        Candidates that don't degrade architecture score.
    """
    min_score = max(threshold, baseline_score)
    return [s for s in scored if s.metrics.modularity >= min_score * 0.98]


def adjust_weights_from_memory(
    current: ObjectiveWeights,
    strategy_scores: List[Dict[str, Any]],
) -> ObjectiveWeights:
    """Adjust objective weights based on historical strategy effectiveness.

    If memory shows that coupling-reduction strategies are historically
    most effective, increase the coupling_reduction weight. This creates
    a feedback loop where the system learns to optimize for objectives
    that have historically led to the best outcomes.

    Args:
        current: Current weights.
        strategy_scores: Strategy effectiveness data from memory intelligence.

    Returns:
        Adjusted weights (normalized).
    """
    if not strategy_scores:
        return current

    # Map strategies to objectives they primarily affect
    strategy_objective_map: Dict[str, str] = {
        "module_split": "modularity",
        "fan_out_reduction": "coupling_reduction",
        "fan_in_reduction": "coupling_reduction",
        "cycle_break": "cycle_reduction",
        "component_extraction": "modularity",
        "deep_chain_reduction": "maintainability",
        "dependency_inversion": "coupling_reduction",
        "subsystem_boundary": "modularity",
    }

    # Accumulate effectiveness by objective
    obj_eff: Dict[str, List[float]] = {
        "modularity": [],
        "coupling_reduction": [],
        "cycle_reduction": [],
        "maintainability": [],
    }

    for s in strategy_scores:
        strategy = s.get("strategy", "")
        eff = s.get("effectiveness", 0.0)
        obj = strategy_objective_map.get(strategy)
        if obj and eff > 0:
            obj_eff[obj].append(eff)

    # Adjust weights: boost objectives with historically effective strategies
    adjusted = ObjectiveWeights(
        modularity=current.modularity,
        coupling_reduction=current.coupling_reduction,
        cycle_reduction=current.cycle_reduction,
        maintainability=current.maintainability,
    )

    for obj_name, effs in obj_eff.items():
        if effs:
            avg_eff = sum(effs) / len(effs)
            # Boost weight by up to 50% based on historical effectiveness
            boost = 1.0 + (avg_eff * 0.5)
            current_val = getattr(adjusted, obj_name)
            setattr(adjusted, obj_name, current_val * boost)

    return adjusted.normalize()
