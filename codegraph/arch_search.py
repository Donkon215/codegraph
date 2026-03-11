"""codegraph.arch_search — Multi-candidate architecture search engine.

Generates multiple architecture improvement candidates from advisor
findings, simulates each, scores them, and selects the best one.

This module implements the "strategy lab" stage that sits between
the architecture advisor and implementation planning:

    advisor → generate candidates → simulate → score → rank → select best

Each candidate represents a different refactoring strategy (module split,
fan-out reduction, subsystem boundary improvement, etc.) and is evaluated
against architecture metrics before any code changes are made.

Dependencies: intelligence (architecture_advisor, arch_health, risk_metrics,
refactor, architecture_simulator), infrastructure (logging_config, storage),
architecture_memory.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from codegraph.logging_config import get_logger

logger = get_logger("arch_search")


# ── Strategy Types ─────────────────────────────────────────────────────

STRATEGY_TYPES = [
    "module_split",
    "fan_out_reduction",
    "fan_in_reduction",
    "subsystem_boundary",
    "dependency_inversion",
    "component_extraction",
    "cycle_break",
    "deep_chain_reduction",
]


# ── Data Models ────────────────────────────────────────────────────────


@dataclass
class ArchCandidate:
    """A single architecture improvement candidate."""

    candidate_id: str
    strategy: str  # one of STRATEGY_TYPES
    description: str
    target_modules: List[str] = field(default_factory=list)
    expected_impact: str = ""
    risk_level: str = "low"  # low, medium, high

    # Scores filled after simulation
    predicted_score: float = 0.0
    predicted_modularity: float = 0.0
    predicted_coupling: float = 0.0
    predicted_fan_out_delta: float = 0.0
    predicted_god_module_delta: int = 0
    predicted_cycle_delta: int = 0
    has_violations: bool = False
    simulation_safe: bool = True
    simulation_recommendation: str = ""

    # Ranking
    rank: int = 0
    composite_score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "strategy": self.strategy,
            "description": self.description,
            "target_modules": self.target_modules,
            "expected_impact": self.expected_impact,
            "risk_level": self.risk_level,
            "predicted_score": round(self.predicted_score, 4),
            "predicted_modularity": round(self.predicted_modularity, 4),
            "predicted_coupling": round(self.predicted_coupling, 4),
            "predicted_fan_out_delta": round(self.predicted_fan_out_delta, 2),
            "predicted_god_module_delta": self.predicted_god_module_delta,
            "predicted_cycle_delta": self.predicted_cycle_delta,
            "has_violations": self.has_violations,
            "simulation_safe": self.simulation_safe,
            "simulation_recommendation": self.simulation_recommendation,
            "rank": self.rank,
            "composite_score": round(self.composite_score, 4),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ArchCandidate":
        return cls(
            candidate_id=d["candidate_id"],
            strategy=d.get("strategy", ""),
            description=d.get("description", ""),
            target_modules=d.get("target_modules", []),
            expected_impact=d.get("expected_impact", ""),
            risk_level=d.get("risk_level", "low"),
            predicted_score=d.get("predicted_score", 0.0),
            predicted_modularity=d.get("predicted_modularity", 0.0),
            predicted_coupling=d.get("predicted_coupling", 0.0),
            predicted_fan_out_delta=d.get("predicted_fan_out_delta", 0.0),
            predicted_god_module_delta=d.get("predicted_god_module_delta", 0),
            predicted_cycle_delta=d.get("predicted_cycle_delta", 0),
            has_violations=d.get("has_violations", False),
            simulation_safe=d.get("simulation_safe", True),
            simulation_recommendation=d.get("simulation_recommendation", ""),
            rank=d.get("rank", 0),
            composite_score=d.get("composite_score", 0.0),
        )


@dataclass
class ArchSearchResult:
    """Result of a multi-candidate architecture search."""

    candidates: List[ArchCandidate] = field(default_factory=list)
    selected: Optional[ArchCandidate] = None
    baseline_score: float = 0.0
    baseline_modularity: float = 0.0
    baseline_god_modules: int = 0
    baseline_cycles: int = 0
    baseline_coupling: float = 0.0
    discard_reasons: Dict[str, str] = field(default_factory=dict)
    status: str = "pending"  # pending, selected, no_safe_candidate

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "status": self.status,
            "baseline": {
                "score": round(self.baseline_score, 4),
                "modularity": round(self.baseline_modularity, 4),
                "god_modules": self.baseline_god_modules,
                "cycles": self.baseline_cycles,
                "coupling": round(self.baseline_coupling, 4),
            },
            "candidates": [c.to_dict() for c in self.candidates],
            "discard_reasons": self.discard_reasons,
        }
        if self.selected:
            d["selected"] = self.selected.to_dict()
        return d

    def save(self, project_root: Path) -> Path:
        """Save search results to .codegraph/planning/arch_search.json."""
        out_dir = project_root / ".codegraph" / "planning"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "arch_search.json"
        path.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return path

    @classmethod
    def load(cls, project_root: Path) -> Optional["ArchSearchResult"]:
        """Load previous search results if they exist."""
        path = project_root / ".codegraph" / "planning" / "arch_search.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        result = cls(
            status=data.get("status", "pending"),
            baseline_score=data.get("baseline", {}).get("score", 0.0),
            baseline_modularity=data.get("baseline", {}).get("modularity", 0.0),
            baseline_god_modules=data.get("baseline", {}).get("god_modules", 0),
            baseline_cycles=data.get("baseline", {}).get("cycles", 0),
            baseline_coupling=data.get("baseline", {}).get("coupling", 0.0),
            discard_reasons=data.get("discard_reasons", {}),
        )
        for cd in data.get("candidates", []):
            result.candidates.append(ArchCandidate.from_dict(cd))
        sel = data.get("selected")
        if sel:
            result.selected = ArchCandidate.from_dict(sel)
        return result

    def format(self) -> str:
        lines = [
            "Architecture Search Results",
            f"  Status: {self.status}",
            f"  Baseline: score={self.baseline_score:.3f} "
            f"modularity={self.baseline_modularity:.3f} "
            f"god_modules={self.baseline_god_modules} "
            f"cycles={self.baseline_cycles}",
            "",
            f"Candidates ({len(self.candidates)}):",
        ]
        for c in self.candidates:
            safe_icon = "+" if c.simulation_safe else "X"
            lines.append(
                f"  [{safe_icon}] #{c.rank} {c.candidate_id} "
                f"({c.strategy}) score={c.composite_score:.3f}"
            )
            lines.append(f"      {c.description}")
            if not c.simulation_safe:
                reason = self.discard_reasons.get(c.candidate_id, "unsafe")
                lines.append(f"      REJECTED: {reason}")
        if self.selected:
            lines.append("")
            lines.append(f"Selected: {self.selected.candidate_id}")
            lines.append(f"  Strategy: {self.selected.strategy}")
            lines.append(f"  Description: {self.selected.description}")
            lines.append(f"  Targets: {', '.join(self.selected.target_modules)}")
            lines.append(
                f"  Predicted: score={self.selected.predicted_score:.3f} "
                f"modularity={self.selected.predicted_modularity:.3f}"
            )
        elif self.status == "no_safe_candidate":
            lines.append("")
            lines.append("NO_SAFE_ARCHITECTURE_CHANGE")
            lines.append("All candidates failed simulation or regressed metrics.")
        return "\n".join(lines)


# ── Candidate Generation ──────────────────────────────────────────────


def generate_candidates(
    advice_path: Path,
    *,
    max_candidates: int = 5,
) -> List[ArchCandidate]:
    """Generate architecture improvement candidates from advisor findings.

    Reads architecture_advice.json and produces candidates based on
    the detected smells and suggestions. Each candidate represents
    a different refactoring strategy.
    """
    if not advice_path.exists():
        logger.warning("No architecture advice found at %s", advice_path)
        return []

    data = json.loads(advice_path.read_text(encoding="utf-8"))
    smells = data.get("smells", [])
    suggestions = data.get("suggestions", [])

    candidates: List[ArchCandidate] = []
    used_strategies: Set[str] = set()

    # Strategy 1: God module splits
    god_modules = [s for s in smells if s.get("smell_type") == "god_module"]
    if god_modules:
        # Pick the worst god module
        worst = max(god_modules, key=lambda s: s.get("metric_value", 0))
        node = worst.get("node", "unknown")
        node_count = int(worst.get("metric_value", 0))
        candidates.append(ArchCandidate(
            candidate_id=f"split_{_module_name(node)}",
            strategy="module_split",
            description=(
                f"Split god module {node} ({node_count} nodes) "
                f"into focused sub-modules"
            ),
            target_modules=[node],
            expected_impact=(
                f"Reduce god_module count by 1, lower fan-out for {node}"
            ),
            risk_level="medium",
        ))
        used_strategies.add("module_split")

    # Strategy 2: Fan-out reduction
    high_fan_out = [
        s for s in smells if s.get("smell_type") == "high_fan_out"
    ]
    if high_fan_out and "fan_out_reduction" not in used_strategies:
        worst = max(high_fan_out, key=lambda s: s.get("metric_value", 0))
        node = worst.get("node", "unknown")
        fan_out_val = int(worst.get("metric_value", 0))
        candidates.append(ArchCandidate(
            candidate_id=f"reduce_fanout_{_module_name(node)}",
            strategy="fan_out_reduction",
            description=(
                f"Reduce fan-out of {node} ({fan_out_val}) "
                f"by introducing dispatcher or facade"
            ),
            target_modules=[node],
            expected_impact=f"Lower fan-out of {node} below threshold",
            risk_level="medium",
        ))
        used_strategies.add("fan_out_reduction")

    # Strategy 3: Fan-in reduction (decouple hot node)
    high_fan_in = [
        s for s in smells if s.get("smell_type") == "high_fan_in"
    ]
    if high_fan_in and "fan_in_reduction" not in used_strategies:
        worst = max(high_fan_in, key=lambda s: s.get("metric_value", 0))
        node = worst.get("node", "unknown")
        fan_in_val = int(worst.get("metric_value", 0))
        candidates.append(ArchCandidate(
            candidate_id=f"reduce_fanin_{_module_name(node)}",
            strategy="fan_in_reduction",
            description=(
                f"Reduce fan-in of {node} ({fan_in_val}) "
                f"by introducing abstraction layer or splitting interface"
            ),
            target_modules=[node],
            expected_impact=f"Lower fan-in of {node}, reduce blast radius",
            risk_level="low",
        ))
        used_strategies.add("fan_in_reduction")

    # Strategy 4: Cycle breaking
    cycles = [s for s in smells if s.get("smell_type") == "cycle"]
    if cycles and "cycle_break" not in used_strategies:
        cycle = cycles[0]
        nodes = cycle.get("nodes", [])
        candidates.append(ArchCandidate(
            candidate_id="break_cycle",
            strategy="cycle_break",
            description=(
                f"Break dependency cycle involving "
                f"{', '.join(nodes[:3])}"
                + (f" (+{len(nodes)-3} more)" if len(nodes) > 3 else "")
            ),
            target_modules=nodes[:5],
            expected_impact="Eliminate cycle, improve modularity",
            risk_level="high",
        ))
        used_strategies.add("cycle_break")

    # Strategy 5: Large subsystem decomposition
    large_subs = [
        s for s in smells if s.get("smell_type") == "large_subsystem"
    ]
    if large_subs and "subsystem_boundary" not in used_strategies:
        worst = max(large_subs, key=lambda s: s.get("metric_value", 0))
        node = worst.get("node", "unknown")
        size = int(worst.get("metric_value", 0))
        candidates.append(ArchCandidate(
            candidate_id=f"decompose_{_module_name(node)}",
            strategy="subsystem_boundary",
            description=(
                f"Decompose large subsystem {node} ({size} nodes) "
                f"into focused sub-subsystems"
            ),
            target_modules=[node],
            expected_impact="Improve cohesion, reduce subsystem size",
            risk_level="high",
        ))
        used_strategies.add("subsystem_boundary")

    # Strategy 6: Low cohesion improvement
    low_cohesion = [
        s for s in smells if s.get("smell_type") == "low_cohesion"
    ]
    if low_cohesion and "component_extraction" not in used_strategies:
        worst = min(low_cohesion, key=lambda s: s.get("metric_value", 1.0))
        node = worst.get("node", "unknown")
        cohesion_val = worst.get("metric_value", 0.0)
        candidates.append(ArchCandidate(
            candidate_id=f"extract_{_module_name(node)}",
            strategy="component_extraction",
            description=(
                f"Extract loosely coupled components from {node} "
                f"(cohesion={cohesion_val:.2f}) into dedicated modules"
            ),
            target_modules=[node],
            expected_impact="Improve subsystem cohesion above 0.3 threshold",
            risk_level="medium",
        ))
        used_strategies.add("component_extraction")

    # Strategy 7: Deep chain reduction
    deep_chains = [
        s for s in smells if s.get("smell_type") == "deep_chain"
    ]
    if deep_chains and "deep_chain_reduction" not in used_strategies:
        worst = max(deep_chains, key=lambda s: s.get("metric_value", 0))
        depth = int(worst.get("metric_value", 0))
        node = worst.get("node", "unknown")
        candidates.append(ArchCandidate(
            candidate_id=f"flatten_{_module_name(node)}",
            strategy="deep_chain_reduction",
            description=(
                f"Flatten deep dependency chain (depth={depth}) "
                f"rooted at {node}"
            ),
            target_modules=[node],
            expected_impact=f"Reduce max dependency depth below threshold",
            risk_level="medium",
        ))
        used_strategies.add("deep_chain_reduction")

    # Strategy 8: From advisor suggestions (fill remaining slots)
    suggestion_strategies = {
        "split_module": "module_split",
        "reduce_coupling": "fan_out_reduction",
        "extract_subsystem": "subsystem_boundary",
        "introduce_interface": "dependency_inversion",
        "break_cycle": "cycle_break",
    }

    for sug in sorted(suggestions, key=lambda s: s.get("priority", 10)):
        if len(candidates) >= max_candidates:
            break
        action = sug.get("action", "")
        strategy = suggestion_strategies.get(action)
        if strategy and strategy not in used_strategies:
            target = sug.get("target", "unknown")
            candidates.append(ArchCandidate(
                candidate_id=f"sug_{_module_name(target)}_{action}",
                strategy=strategy,
                description=sug.get("reason", f"{action} on {target}"),
                target_modules=[target],
                expected_impact=f"Address {sug.get('source_smell', 'unknown')} smell",
                risk_level="medium",
            ))
            used_strategies.add(strategy)

    return candidates[:max_candidates]


# ── Candidate Simulation ──────────────────────────────────────────────


def simulate_candidates(
    candidates: List[ArchCandidate],
    project_root: Path,
) -> List[ArchCandidate]:
    """Simulate each candidate and fill in predicted metrics.

    Uses architecture_simulator to predict impact of each candidate's
    changes on the architecture without modifying code.
    """
    from codegraph.arch_schema import SystemArchitecture
    from codegraph.architecture_simulator import (
        ArchChange,
        simulate_architecture_changes,
    )

    arch = SystemArchitecture.load(project_root)
    if not arch:
        logger.warning("No architecture found, skipping simulation")
        return candidates

    # Compute baseline metrics
    from codegraph.architecture_simulator import _compute_arch_metrics
    baseline = _compute_arch_metrics(arch)

    for candidate in candidates:
        changes = _strategy_to_changes(candidate, arch)
        if not changes:
            # No simulatable changes — mark as safe but with no score improvement
            candidate.simulation_safe = True
            candidate.simulation_recommendation = "review"
            candidate.predicted_score = baseline.get("coupling", 0.5)
            continue

        result = simulate_architecture_changes(changes, arch)
        candidate.simulation_safe = result.safe
        candidate.simulation_recommendation = result.recommendation

        # Extract predicted metrics from simulation
        for pred in result.predictions:
            if pred.metric == "coupling":
                candidate.predicted_coupling = pred.predicted_value
            elif pred.metric == "cycles":
                candidate.predicted_cycle_delta = int(pred.delta)
            elif pred.metric == "max_fan_out":
                candidate.predicted_fan_out_delta = pred.delta
            elif pred.metric == "constraint_violation":
                candidate.has_violations = True

        # If simulation rejected, mark unsafe
        if result.recommendation == "reject":
            candidate.simulation_safe = False

    return candidates


def _strategy_to_changes(
    candidate: ArchCandidate,
    arch: "SystemArchitecture",
) -> List["ArchChange"]:
    """Convert a candidate strategy into simulatable architecture changes."""
    from codegraph.architecture_simulator import ArchChange

    changes: List[ArchChange] = []

    if candidate.strategy == "module_split":
        # Simulate adding a new component (the extracted module)
        target = candidate.target_modules[0] if candidate.target_modules else ""
        module_name = _module_name(target)
        # Find which subsystem owns this module
        subsystem = _find_subsystem_for_module(target, arch)
        if subsystem:
            changes.append(ArchChange(
                action="add_component",
                subsystem=subsystem,
                component_name=f"{module_name}_extracted",
                module_path=f"codegraph/{module_name}_extracted.py",
                reason=candidate.description,
            ))
            # Add internal edge from original to extracted
            changes.append(ArchChange(
                action="add_edge",
                subsystem=subsystem,
                target_subsystem=subsystem,
                reason=f"{module_name} → {module_name}_extracted (split)",
            ))

    elif candidate.strategy == "subsystem_boundary":
        # Simulate splitting a subsystem into two
        target = candidate.target_modules[0] if candidate.target_modules else ""
        changes.append(ArchChange(
            action="split_subsystem",
            subsystem=target,
            target_subsystem=f"{target}_core",
            reason=candidate.description,
        ))

    elif candidate.strategy == "fan_out_reduction":
        # Simulate adding a dispatcher that absorbs some edges
        target = candidate.target_modules[0] if candidate.target_modules else ""
        subsystem = _find_subsystem_for_module(target, arch)
        if subsystem:
            changes.append(ArchChange(
                action="add_component",
                subsystem=subsystem,
                component_name=f"{_module_name(target)}_dispatcher",
                module_path=f"codegraph/{_module_name(target)}_dispatcher.py",
                reason=candidate.description,
            ))

    elif candidate.strategy == "cycle_break":
        # Simulate removing an edge to break cycle
        if len(candidate.target_modules) >= 2:
            changes.append(ArchChange(
                action="remove_edge",
                subsystem=candidate.target_modules[0],
                target_subsystem=candidate.target_modules[1],
                reason="Break cycle",
            ))

    elif candidate.strategy == "dependency_inversion":
        target = candidate.target_modules[0] if candidate.target_modules else ""
        subsystem = _find_subsystem_for_module(target, arch)
        if subsystem:
            changes.append(ArchChange(
                action="add_component",
                subsystem=subsystem,
                component_name=f"{_module_name(target)}_interface",
                module_path=f"codegraph/{_module_name(target)}_interface.py",
                reason=candidate.description,
            ))

    return changes


# ── Scoring & Ranking ─────────────────────────────────────────────────


def score_candidates(
    candidates: List[ArchCandidate],
    baseline_score: float,
    baseline_modularity: float,
    baseline_coupling: float,
    baseline_god_modules: int,
    baseline_cycles: int,
) -> List[ArchCandidate]:
    """Score and rank candidates using weighted architecture metrics.

    Ranking priorities:
      1. Highest architecture score improvement
      2. Lowest coupling increase
      3. Lowest fan-out growth
      4. No policy violations
      5. Minimal subsystem disruption
    """
    for candidate in candidates:
        if not candidate.simulation_safe:
            candidate.composite_score = -1.0
            continue

        score = 0.0

        # 1. Predicted architecture improvement (40% weight)
        if candidate.predicted_score > 0:
            score_improvement = candidate.predicted_score - baseline_score
            score += 0.4 * max(0, min(1.0, 0.5 + score_improvement * 5))
        else:
            score += 0.2  # neutral if no prediction

        # 2. Coupling reduction (25% weight)
        if candidate.predicted_coupling > 0:
            coupling_delta = baseline_coupling - candidate.predicted_coupling
            score += 0.25 * max(0, min(1.0, 0.5 + coupling_delta * 5))
        else:
            score += 0.125  # neutral

        # 3. Fan-out improvement (15% weight)
        fan_out_bonus = max(0, -candidate.predicted_fan_out_delta)
        score += 0.15 * min(1.0, fan_out_bonus / 5.0)

        # 4. No violations bonus (10% weight)
        if not candidate.has_violations:
            score += 0.10

        # 5. Risk level penalty (10% weight)
        risk_scores = {"low": 0.10, "medium": 0.05, "high": 0.0}
        score += risk_scores.get(candidate.risk_level, 0.0)

        # God module reduction bonus
        if candidate.predicted_god_module_delta < 0:
            score += 0.05 * abs(candidate.predicted_god_module_delta)

        # Cycle reduction bonus
        if candidate.predicted_cycle_delta < 0:
            score += 0.10 * abs(candidate.predicted_cycle_delta)

        candidate.composite_score = min(1.0, score)

    # Sort by composite score descending
    candidates.sort(key=lambda c: c.composite_score, reverse=True)

    # Assign ranks
    for i, c in enumerate(candidates):
        c.rank = i + 1

    return candidates


# ── Search Orchestrator ───────────────────────────────────────────────


def run_arch_search(
    project_root: Path,
    *,
    max_candidates: int = 5,
    save_results: bool = False,
) -> ArchSearchResult:
    """Run the full multi-candidate architecture search.

    1. Read advisor findings
    2. Generate candidates
    3. Simulate each candidate
    4. Score and rank
    5. Select best candidate (or report no safe change)
    """
    result = ArchSearchResult()

    # Load advisor baseline
    advice_path = project_root / ".codegraph" / "architecture" / "architecture_advice.json"
    if not advice_path.exists():
        logger.error("No architecture advice found. Run 'codegraph architect --save' first.")
        result.status = "no_safe_candidate"
        return result

    advice_data = json.loads(advice_path.read_text(encoding="utf-8"))
    result.baseline_score = advice_data.get("score", 0.0)
    result.baseline_modularity = advice_data.get("modularity", 0.0)
    result.baseline_god_modules = advice_data.get("god_module_count", 0)
    result.baseline_cycles = advice_data.get("cycle_count", 0)

    # Compute baseline coupling from raw metrics
    from codegraph.arch_schema import SystemArchitecture
    from codegraph.architecture_simulator import _compute_arch_metrics
    arch = SystemArchitecture.load(project_root)
    if arch:
        metrics = _compute_arch_metrics(arch)
        result.baseline_coupling = metrics.get("coupling", 0.0)
    else:
        result.baseline_coupling = 0.0

    # Step 1: Generate candidates
    logger.info("Generating architecture improvement candidates...")
    candidates = generate_candidates(
        advice_path, max_candidates=max_candidates,
    )

    if not candidates:
        logger.info("No architecture improvements identified.")
        result.status = "no_safe_candidate"
        return result

    logger.info("Generated %d candidates", len(candidates))

    # Step 2: Simulate
    logger.info("Simulating candidates...")
    candidates = simulate_candidates(candidates, project_root)

    # Step 3: Score and rank
    logger.info("Scoring and ranking candidates...")
    candidates = score_candidates(
        candidates,
        baseline_score=result.baseline_score,
        baseline_modularity=result.baseline_modularity,
        baseline_coupling=result.baseline_coupling,
        baseline_god_modules=result.baseline_god_modules,
        baseline_cycles=result.baseline_cycles,
    )

    result.candidates = candidates

    # Step 4: Filter unsafe candidates and record discard reasons
    safe_candidates = []
    for c in candidates:
        if not c.simulation_safe:
            result.discard_reasons[c.candidate_id] = (
                f"Simulation: {c.simulation_recommendation}"
            )
        elif c.has_violations:
            result.discard_reasons[c.candidate_id] = "Architecture violations detected"
        else:
            safe_candidates.append(c)

    # Step 5: Select best
    if safe_candidates:
        result.selected = safe_candidates[0]  # already sorted by score
        result.status = "selected"
        logger.info(
            "Selected candidate: %s (score=%.3f)",
            result.selected.candidate_id,
            result.selected.composite_score,
        )
    else:
        result.status = "no_safe_candidate"
        logger.warning("No safe architecture changes found.")

    # Record to architecture memory
    _record_search_to_memory(result, project_root)

    # Save results
    if save_results:
        path = result.save(project_root)
        logger.info("Search results saved: %s", path)

    return result


# ── Memory Integration ────────────────────────────────────────────────


def _record_search_to_memory(
    result: ArchSearchResult,
    project_root: Path,
) -> None:
    """Record the search decision to architecture memory."""
    try:
        from codegraph.architecture_memory import save_decision

        if result.selected:
            save_decision(
                project_root,
                decision=f"arch_search: selected {result.selected.candidate_id}",
                reason=(
                    f"Strategy: {result.selected.strategy}. "
                    f"{result.selected.description}. "
                    f"Composite score: {result.selected.composite_score:.3f}"
                ),
                result="pending",
                tags=["arch_search", result.selected.strategy],
            )
        elif result.status == "no_safe_candidate":
            save_decision(
                project_root,
                decision="arch_search: no safe candidate found",
                reason=(
                    f"Evaluated {len(result.candidates)} candidates, "
                    f"none passed simulation"
                ),
                result="failed",
                tags=["arch_search", "no_candidate"],
            )
    except Exception:
        logger.debug("Could not record search to architecture memory", exc_info=True)


# ── Helpers ───────────────────────────────────────────────────────────


def _module_name(path: str) -> str:
    """Extract a short module name from a path or node ID."""
    name = path.replace("codegraph/", "").replace(".py", "")
    name = name.split("::")[-1] if "::" in name else name
    name = name.replace("/", "_")
    return name


def _find_subsystem_for_module(
    module_path: str,
    arch: "SystemArchitecture",
) -> Optional[str]:
    """Find which subsystem a module belongs to."""
    for sub in arch.subsystems:
        for comp in sub.components:
            if comp.module and (
                module_path in comp.module
                or comp.module in module_path
            ):
                return sub.name
    return None
