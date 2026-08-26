"""codegraph.arch_evolution — Architecture Evolution Engine.

Closed-loop architecture improvement system that:
  1. Detects architectural smells (via advisor)
  2. Generates mutation candidates (via arch_search)
  3. Evaluates against policies (via arch_policy)
  4. Simulates impact (via architecture_simulator)
  5. Records outcomes to memory (via arch_memory)
  6. Learns from history (via arch_memory_intelligence)

This creates a self-improving architecture feedback loop:
  detect → mutate → evaluate → simulate → select → record → learn

Unlike the basic `codegraph evolve` command which runs a simple
advisor→delta→task loop, this engine uses all intelligence layers
for data-driven architecture evolution with safety constraints.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from codegraph.architecture_objectives import (
    ObjectiveWeights,
    adjust_weights_from_memory,
    compute_objective_score,
    CandidateMetrics,
    score_candidates,
    reject_degrading_candidates,
)
from codegraph.logging_config import get_logger

logger = get_logger("arch_evolution")


# ═══════════════════════════════════════════════════════════════════════
# Mutation Safety Tiers
# ═══════════════════════════════════════════════════════════════════════

TIER_SAFE = "safe"          # auto-apply: split module, reduce fan-out
TIER_MEDIUM = "medium"      # review: move function, refactor API
TIER_DANGEROUS = "dangerous"  # human-only: delete subsystem, rewrite

STRATEGY_TIERS: Dict[str, str] = {
    "module_split": TIER_SAFE,
    "fan_out_reduction": TIER_SAFE,
    "fan_in_reduction": TIER_SAFE,
    "component_extraction": TIER_SAFE,
    "deep_chain_reduction": TIER_MEDIUM,
    "dependency_inversion": TIER_MEDIUM,
    "subsystem_boundary": TIER_MEDIUM,
    "cycle_break": TIER_MEDIUM,
    "subsystem_merge": TIER_DANGEROUS,
    "subsystem_delete": TIER_DANGEROUS,
    "rewrite": TIER_DANGEROUS,
}


def get_mutation_tier(strategy: str) -> str:
    """Return the safety tier for a given strategy name."""
    return STRATEGY_TIERS.get(strategy, TIER_MEDIUM)


# ═══════════════════════════════════════════════════════════════════════
# Stage Grouping Helpers (reduce fan-out)
# ═══════════════════════════════════════════════════════════════════════


def _run_detection_and_memory_stages(
    project_root: Path,
    result: EvolutionResult,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], bool]:
    """Run Stages 1-2: Detect architectural smells and consult memory.

    Returns
    -------
    (advice, strategy_ranking, early_exit)
        - advice: advisor result with smells and score
        - strategy_ranking: historical strategy effectiveness
        - early_exit: True if should return early (no smells or advisor failed)
    """
    # Stage 1: Detect
    detect_stage = EvolutionStage(name="detect", status="running")
    result.stages.append(detect_stage)

    try:
        advice = _run_advisor(project_root)
    except Exception as exc:
        detect_stage.status = "failed"
        detect_stage.details = str(exc)
        result.status = "failed"
        return {}, [], True

    smell_count = len(advice.get("smells", []))
    score = advice.get("score", 0.0)

    detect_stage.status = "passed"
    detect_stage.details = f"{smell_count} smells, score={score:.3f}"
    detect_stage.metrics = {
        "smells": smell_count,
        "score": score,
        "grade": advice.get("grade", "?"),
    }

    if smell_count == 0:
        detect_stage.details += " — architecture is clean"
        result.status = "no_change"
        result.score_after = score
        result.recommendations.append("No architectural smells detected")
        _skip_remaining(result, "detect")
        return advice, [], True

    # Stage 2: Memory
    memory_stage = EvolutionStage(name="memory", status="running")
    result.stages.append(memory_stage)

    try:
        strategy_ranking = _get_strategy_ranking(project_root)
        memory_stage.status = "passed"
        if strategy_ranking:
            top = strategy_ranking[0]
            memory_stage.details = (
                f"{len(strategy_ranking)} strategies scored, "
                f"best: {top.get('strategy', '?')} "
                f"({top.get('effectiveness', 0):.0%})"
            )
        else:
            memory_stage.details = "No historical strategy data yet"
    except Exception as exc:
        memory_stage.status = "passed"
        memory_stage.details = f"No memory data yet: {exc}"
        strategy_ranking = []

    return advice, strategy_ranking, False


def _run_mutate_and_policy_stages(
    project_root: Path,
    result: EvolutionResult,
    max_candidates: int,
    strategy_ranking: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any], bool]:
    """Run Stages 3-4: Generate candidates and check policies.

    Returns
    -------
    (candidates, selected, early_exit)
        - candidates: all generated candidates
        - selected: best safe candidate
        - early_exit: True if should return early (no candidates, blocked, or policy violations)
    """
    score = result.score_before

    # Stage 3: Mutate
    mutate_stage = EvolutionStage(name="mutate", status="running")
    result.stages.append(mutate_stage)

    try:
        search_result = _run_arch_search(project_root, max_candidates)
    except Exception as exc:
        mutate_stage.status = "failed"
        mutate_stage.details = str(exc)
        result.status = "failed"
        _skip_remaining(result, "mutate")
        return [], {}, True

    candidates = search_result.get("candidates", [])
    selected = search_result.get("selected")

    # Rerank candidates using memory intelligence
    if selected and strategy_ranking:
        selected = _rerank_with_memory(
            selected, candidates, strategy_ranking,
        )

    if not selected:
        mutate_stage.status = "passed"
        mutate_stage.details = (
            f"{len(candidates)} candidates generated, none safe"
        )
        result.status = "no_change"
        result.score_after = score
        result.recommendations.append(
            "No safe architecture change found — manual review needed"
        )
        _skip_remaining(result, "mutate")
        return candidates, {}, True

    mutate_stage.status = "passed"
    mutate_stage.details = (
        f"{len(candidates)} candidates, selected: "
        f"{selected.get('strategy', '?')}"
    )

    # Check mutation safety tier
    tier = get_mutation_tier(selected.get("strategy", ""))
    if tier == TIER_DANGEROUS:
        mutate_stage.details += f" [BLOCKED: {tier} tier]"
        result.status = "blocked"
        result.score_after = score
        result.recommendations.append(
            f"Strategy '{selected.get('strategy')}' is {tier}-tier — "
            f"requires human approval"
        )
        _skip_remaining(result, "mutate")
        return candidates, {}, True

    mutate_stage.metrics = {
        "candidates": len(candidates),
        "selected_strategy": selected.get("strategy", ""),
        "predicted_score": selected.get("predicted_score", 0.0),
        "safety_tier": tier,
    }

    # Stage 4: Policy
    policy_stage = EvolutionStage(name="policy", status="running")
    result.stages.append(policy_stage)

    try:
        policy_report = _check_policies(project_root)
        blocking = sum(1 for v in policy_report.get("violations", [])
                       if v.get("action") == "block")
        result.policy_violations = len(policy_report.get("violations", []))

        if blocking > 0:
            policy_stage.status = "failed"
            policy_stage.details = f"{blocking} blocking violations"
            result.status = "blocked"
            result.score_after = score
            result.recommendations.append(
                f"Evolution blocked by {blocking} policy violations"
            )
            _skip_remaining(result, "policy")
            return candidates, selected, True

        policy_stage.status = "passed"
        warnings = result.policy_violations - blocking
        policy_stage.details = f"0 blocking, {warnings} warnings"
    except Exception as exc:
        policy_stage.status = "passed"
        policy_stage.details = f"No policies defined: {exc}"

    return candidates, selected, False


def _record_evolution_results(project_root, result, advice):
    """Record evolution decision, metrics, and proposal to memory."""
    _record_to_memory(project_root, result)
    _record_metrics_snapshot(project_root, advice, "evolution")
    _save_evolution_proposal(project_root, result)


def _run_select_and_record_stages(
    project_root: Path,
    result: EvolutionResult,
    advice: Dict[str, Any],
    candidates: List[Dict[str, Any]],
    selected: Dict[str, Any],
    strategy_ranking: List[Dict[str, Any]],
    predicted_score: float,
    score: float,
    dry_run: bool,
) -> float:
    """Run Stages 6-7: Score objectives and record decision.

    Returns
    -------
    obj_score : float
        The objective score for the selected candidate.
    """
    # Stage 6: Select (objective-scored)
    select_stage = EvolutionStage(name="select", status="running")
    result.stages.append(select_stage)

    # Compute objective-based scoring
    weights = ObjectiveWeights()
    if strategy_ranking:
        weights = adjust_weights_from_memory(weights, strategy_ranking)

    raw_cycles = advice.get("cycles", 0)
    n_cycles = len(raw_cycles) if isinstance(raw_cycles, list) else int(raw_cycles)
    baseline_metrics = {
        "score": score,
        "coupling": advice.get("coupling", 0.0),
        "cycles": n_cycles,
    }
    scored = score_candidates(candidates, baseline_metrics, weights)
    scored = reject_degrading_candidates(scored, score)

    obj_score = 0.0
    if scored:
        # Use objective score from the best candidate matching selection
        for sc in scored:
            if sc.strategy == selected.get("strategy", ""):
                obj_score = sc.objective_score
                select_stage.metrics = sc.to_dict()
                break
        else:
            obj_score = scored[0].objective_score
            select_stage.metrics = scored[0].to_dict()

    # Boost candidates that match historically effective strategies
    boosted = _apply_memory_boost(selected, strategy_ranking)

    result.score_after = predicted_score
    result.score_delta = predicted_score - score

    if result.score_delta < -0.02:
        select_stage.status = "failed"
        select_stage.details = (
            f"Predicted degradation ({result.score_delta:+.3f}) — rejected"
        )
        result.status = "blocked"
        result.recommendations.append(
            f"Strategy '{result.selected_strategy}' rejected: "
            f"predicted score drop of {abs(result.score_delta):.3f}"
        )
        _skip_remaining(result, "select")
        return obj_score

    select_stage.status = "passed"
    select_stage.details = (
        f"Accepted: {result.selected_strategy} "
        f"(Δ={result.score_delta:+.3f}, obj={obj_score:.3f})"
    )
    if boosted:
        select_stage.details += " [memory-boosted]"

    # Stage 7: Record
    record_stage = EvolutionStage(name="record", status="running")
    result.stages.append(record_stage)

    if not dry_run:
        try:
            _record_evolution_results(project_root, result, advice)
            record_stage.status = "passed"
            record_stage.details = "Decision + metrics + proposal recorded"
        except Exception as exc:
            record_stage.status = "failed"
            record_stage.details = str(exc)
    else:
        record_stage.status = "skipped"
        record_stage.details = "Dry run — not recorded"

    return obj_score


# ═══════════════════════════════════════════════════════════════════════
# Evolution Stage
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class EvolutionStage:
    """A stage in the evolution pipeline."""

    name: str  # detect, mutate, evaluate, simulate, select, record
    status: str = "pending"  # pending, running, passed, failed, skipped
    details: str = ""
    metrics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "name": self.name,
            "status": self.status,
        }
        if self.details:
            d["details"] = self.details
        if self.metrics:
            d["metrics"] = self.metrics
        return d


# ═══════════════════════════════════════════════════════════════════════
# Evolution Result
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class EvolutionResult:
    """Complete result of an evolution cycle."""

    cycle: int = 1
    status: str = "pending"  # pending, improved, no_change, blocked, failed
    stages: List[EvolutionStage] = field(default_factory=list)
    score_before: float = 0.0
    score_after: float = 0.0
    score_delta: float = 0.0
    selected_strategy: str = ""
    selected_target: str = ""
    policy_violations: int = 0
    recommendations: List[str] = field(default_factory=list)
    timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cycle": self.cycle,
            "status": self.status,
            "score_before": round(self.score_before, 3),
            "score_after": round(self.score_after, 3),
            "score_delta": round(self.score_delta, 3),
            "selected_strategy": self.selected_strategy,
            "selected_target": self.selected_target,
            "policy_violations": self.policy_violations,
            "stages": [s.to_dict() for s in self.stages],
            "recommendations": self.recommendations,
            "timestamp": self.timestamp,
        }

    def format(self) -> str:
        status_icon = {
            "improved": "↑",
            "no_change": "→",
            "blocked": "✗",
            "failed": "✗",
            "pending": "…",
        }.get(self.status, "?")

        lines = [f"Evolution Cycle {self.cycle}: {self.status} {status_icon}"]
        lines.append(f"  Score: {self.score_before:.3f} → {self.score_after:.3f} "
                      f"({self.score_delta:+.3f})")

        if self.selected_strategy:
            lines.append(f"  Strategy: {self.selected_strategy}")
        if self.selected_target:
            lines.append(f"  Target: {self.selected_target}")

        lines.append(f"\n  Stages:")
        for stage in self.stages:
            icon = {"passed": "✓", "failed": "✗", "skipped": "○",
                    "running": "…", "pending": "·"}.get(stage.status, "?")
            line = f"    {icon} {stage.name}"
            if stage.details:
                line += f": {stage.details}"
            lines.append(line)

        if self.recommendations:
            lines.append(f"\n  Recommendations:")
            for r in self.recommendations:
                lines.append(f"    → {r}")

        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# Evolution Engine
# ═══════════════════════════════════════════════════════════════════════


def run_evolution_cycle(
    project_root: Path,
    cycle: int = 1,
    dry_run: bool = False,
    max_candidates: int = 5,
) -> EvolutionResult:
    """Run one full evolution cycle.

    Pipeline:
      1. Detect — run architecture advisor to find smells
      2. Memory — consult past strategy effectiveness
      3. Mutate — generate improvement candidates
      4. Policy — evaluate candidates against policies
      5. Simulate — predict impact of best candidate
      6. Select — pick the best safe candidate
      7. Record — save decision + metrics to memory

    Args:
        project_root: Project root directory.
        cycle: Evolution cycle number.
        dry_run: If True, don't actually apply changes.
        max_candidates: Maximum candidates to generate.

    Returns:
        :class:`EvolutionResult` with stages and outcome.
    """
    result = EvolutionResult(
        cycle=cycle,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

    # ── Stage 1-2: Detect & Memory ──────────────────────────────────
    advice, strategy_ranking, early_exit = _run_detection_and_memory_stages(project_root, result)
    if early_exit:
        return result
    score = advice.get("score", 0.0)
    result.score_before = score

    # ── Stage 3-4: Mutate & Policy ──────────────────────────────────
    candidates, selected, early_exit = _run_mutate_and_policy_stages(
        project_root, result, max_candidates, strategy_ranking
    )
    if early_exit:
        return result

    result.selected_strategy = selected.get("strategy", "")
    result.selected_target = ", ".join(selected.get("target_modules", []))

    # ── Stage 5: Simulate ────────────────────────────────────────
    simulate_stage = EvolutionStage(name="simulate", status="running")
    result.stages.append(simulate_stage)

    predicted_score = selected.get("predicted_score", score)
    simulation_safe = selected.get("simulation_safe", True)

    if not simulation_safe:
        simulate_stage.status = "failed"
        simulate_stage.details = "Simulation predicts unsafe outcome"
        result.status = "blocked"
        result.score_after = score
        _skip_remaining(result, "simulate")
        return result

    simulate_stage.status = "passed"
    simulate_stage.details = f"Predicted score: {predicted_score:.3f}"
    simulate_stage.metrics = {"predicted_score": predicted_score}

    # ── Stage 6-7: Select & Record ──────────────────────────────────
    obj_score = _run_select_and_record_stages(
        project_root, result, advice, candidates, selected, strategy_ranking, predicted_score, score, dry_run
    )

    if result.status != "blocked":
        result.status = "improved" if result.score_delta > 0 else "no_change"

    # Generate recommendations from memory
    result.recommendations.extend(
        _generate_evolution_recommendations(result, strategy_ranking)
    )

    return result


# ═══════════════════════════════════════════════════════════════════════
# Multi-cycle Evolution
# ═══════════════════════════════════════════════════════════════════════


def run_evolution(
    project_root: Path,
    max_cycles: int = 3,
    dry_run: bool = False,
) -> List[EvolutionResult]:
    """Run multiple evolution cycles until convergence.

    Stops when:
      - No more improvements found
      - A policy blocks further changes
      - max_cycles reached
    """
    results: List[EvolutionResult] = []

    for i in range(1, max_cycles + 1):
        logger.info("Evolution cycle %d/%d", i, max_cycles)
        result = run_evolution_cycle(project_root, cycle=i, dry_run=dry_run)
        results.append(result)

        if result.status in ("no_change", "blocked", "failed"):
            logger.info("Evolution stopped at cycle %d: %s", i, result.status)
            break

    return results


# ═══════════════════════════════════════════════════════════════════════
# Evolution Report
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class EvolutionReport:
    """Summary of multi-cycle evolution."""

    cycles: List[EvolutionResult] = field(default_factory=list)
    total_improvement: float = 0.0
    strategies_used: List[str] = field(default_factory=list)
    converged: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_cycles": len(self.cycles),
            "total_improvement": round(self.total_improvement, 3),
            "strategies_used": self.strategies_used,
            "converged": self.converged,
            "cycles": [c.to_dict() for c in self.cycles],
        }

    def format(self) -> str:
        lines = ["Architecture Evolution Report"]
        lines.append(f"  Cycles: {len(self.cycles)}")
        lines.append(f"  Total improvement: {self.total_improvement:+.3f}")
        lines.append(f"  Converged: {'yes' if self.converged else 'no'}")

        if self.strategies_used:
            lines.append(f"  Strategies: {', '.join(self.strategies_used)}")

        for r in self.cycles:
            lines.append(f"\n{r.format()}")

        return "\n".join(lines)

    @classmethod
    def from_results(cls, results: List[EvolutionResult]) -> EvolutionReport:
        total = sum(r.score_delta for r in results)
        strategies = [r.selected_strategy for r in results
                      if r.selected_strategy]
        converged = (results[-1].status == "no_change") if results else False
        return cls(
            cycles=results,
            total_improvement=total,
            strategies_used=strategies,
            converged=converged,
        )


# ═══════════════════════════════════════════════════════════════════════
# Internal Helpers
# ═══════════════════════════════════════════════════════════════════════


def _run_advisor(project_root: Path) -> Dict[str, Any]:
    """Run architecture advisor and return advice dict."""
    from codegraph.arch_schema import SystemArchitecture
    from codegraph.architecture_advisor import advise_architecture
    from codegraph.extractor import load_graph0
    from codegraph.index import IndexStore

    graph0 = load_graph0(project_root)
    with IndexStore(project_root) as index:
        advice = advise_architecture(graph0, index)

    return advice.to_dict()


def _run_arch_search(
    project_root: Path,
    max_candidates: int = 5,
) -> Dict[str, Any]:
    """Run multi-candidate architecture search."""
    from codegraph.arch_search import run_arch_search

    result = run_arch_search(project_root, max_candidates=max_candidates)
    d = result.to_dict()
    # Convert selected to a dict if it exists
    if result.selected:
        d["selected"] = result.selected.to_dict()
    return d


def _check_policies(project_root: Path) -> Dict[str, Any]:
    """Check architecture policies."""
    from codegraph.arch_policy import evaluate_policies
    report = evaluate_policies(project_root)
    return report.to_dict()


def _get_strategy_ranking(project_root: Path) -> List[Dict[str, Any]]:
    """Get strategy ranking from memory intelligence."""
    from codegraph.arch_memory_intelligence import get_strategy_ranking
    scores = get_strategy_ranking(project_root)
    return [s.to_dict() for s in scores]


def _rerank_with_memory(
    selected: Dict[str, Any],
    candidates: List[Dict[str, Any]],
    strategy_ranking: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Rerank candidates using historical strategy effectiveness.

    If a higher-ranked strategy exists among candidates, prefer it
    over the arch-search selection.  Returns the (possibly different)
    selected candidate.
    """
    if not candidates or not strategy_ranking:
        return selected

    # Build effectiveness lookup  {strategy_name: effectiveness}
    eff_map: Dict[str, float] = {
        r["strategy"]: r.get("effectiveness", 0.0)
        for r in strategy_ranking
    }

    selected_eff = eff_map.get(selected.get("strategy", ""), 0.0)

    best_candidate = selected
    best_eff = selected_eff

    for cand in candidates:
        cand_strategy = cand.get("strategy", "")
        cand_eff = eff_map.get(cand_strategy, 0.0)
        # Only override if effectiveness is substantially higher
        if cand_eff > best_eff + 0.15:
            best_candidate = cand
            best_eff = cand_eff

    return best_candidate


def _apply_memory_boost(
    selected: Dict[str, Any],
    strategy_ranking: List[Dict[str, Any]],
) -> bool:
    """Boost candidate score if its strategy historically performs well.

    Returns True if a boost was applied.
    """
    if not strategy_ranking:
        return False

    strategy = selected.get("strategy", "")
    for ranked in strategy_ranking:
        if ranked["strategy"] == strategy and ranked["effectiveness"] > 0.6:
            return True

    return False


def _record_to_memory(
    project_root: Path,
    result: EvolutionResult,
) -> None:
    """Record evolution result to architecture memory."""
    from codegraph.architecture_memory import record_decision

    record_decision(
        project_root,
        decision=f"Evolution cycle {result.cycle}: {result.selected_strategy}",
        reason=f"Target: {result.selected_target}",
        result="success" if result.status == "improved" else "partial",
        health_delta=result.score_delta,
        tags=[result.selected_strategy, "evolution"],
    )


def _record_metrics_snapshot(
    project_root: Path,
    advice: Dict[str, Any],
    trigger: str = "evolution",
) -> None:
    """Record current metrics to history."""
    from codegraph.arch_memory_intelligence import record_metrics_snapshot

    record_metrics_snapshot(
        project_root,
        score=advice.get("score", 0.0),
        grade=advice.get("grade", ""),
        modularity=advice.get("modularity", 0.0),
        coupling=advice.get("coupling", 0.0),
        cycles=advice.get("cycles", 0),
        god_modules=len([s for s in advice.get("smells", [])
                         if s.get("smell_type") == "god_module"]),
        trigger=trigger,
    )


def _skip_remaining(result: EvolutionResult, after_stage: str) -> None:
    """Mark all stages after the given stage as skipped."""
    found = False
    for stage in result.stages:
        if found and stage.status == "pending":
            stage.status = "skipped"
        if stage.name == after_stage:
            found = True


def _generate_evolution_recommendations(
    result: EvolutionResult,
    strategy_ranking: List[Dict[str, Any]],
) -> List[str]:
    """Generate recommendations based on evolution outcome."""
    recs: List[str] = []

    if result.status == "improved" and result.score_delta > 0.05:
        recs.append(
            f"Significant improvement ({result.score_delta:+.3f}) — "
            f"consider running another cycle"
        )

    if result.status == "blocked":
        recs.append(
            "Evolution blocked — review policies or try manual refactoring"
        )

    # Suggest historically effective strategies
    effective = [s for s in strategy_ranking
                 if s.get("effectiveness", 0) > 0.7
                 and s.get("strategy") != result.selected_strategy]
    if effective:
        top = effective[0]
        recs.append(
            f"Consider '{top['strategy']}' — "
            f"{top['effectiveness']:.0%} historical effectiveness"
        )

    return recs


def save_evolution_report(
    project_root: Path,
    report: EvolutionReport,
) -> Path:
    """Save evolution report to disk."""
    planning_dir = project_root / ".codegraph" / "planning"
    planning_dir.mkdir(parents=True, exist_ok=True)
    path = planning_dir / "evolution_report.json"
    path.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Saved evolution report: %d cycles", len(report.cycles))
    return path


def _save_evolution_proposal(
    project_root: Path,
    result: EvolutionResult,
) -> None:
    """Persist selected candidate as a proposal for the compiler to review."""
    from codegraph.evolution_proposals import (
        create_proposal_from_evolution,
        load_proposals,
        save_proposals,
    )

    proposal = create_proposal_from_evolution(result.to_dict(), result.cycle)
    if proposal is None:
        return

    store = load_proposals(project_root)
    store.add(proposal)
    save_proposals(project_root, store)
    logger.info("Saved evolution proposal: %s", proposal.proposal_id)
