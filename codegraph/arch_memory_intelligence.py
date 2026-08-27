"""codegraph.arch_memory_intelligence — Architecture Memory Intelligence.

Adds pattern mining, metrics history tracking, and feedback loops
to the existing arch_memory module. This turns the memory from a
passive log into an active learning system.

Capabilities:
  - Pattern mining: discovers which strategies improve architecture
  - Metrics history: tracks score/modularity/coupling over time
  - Strategy scoring: ranks strategies by historical effectiveness
  - Feedback loop: past outcomes improve future recommendations
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from codegraph.architecture_memory import (
    DecisionRecord,
    ExperimentRecord,
    ArchitectureMemory,
    load_memory,
    save_memory,
)
from codegraph.logging_config import get_logger

logger = get_logger("arch_memory_intelligence")

METRICS_HISTORY_FILE = "metrics_history.json"
STRATEGY_SCORES_FILE = "strategy_scores.json"


# ═══════════════════════════════════════════════════════════════════════
# Metrics Snapshot
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class MetricsSnapshot:
    """Point-in-time architecture metrics."""

    timestamp: str
    score: float = 0.0
    grade: str = ""
    modularity: float = 0.0
    coupling: float = 0.0
    cycles: int = 0
    god_modules: int = 0
    max_fan_in: int = 0
    max_fan_out: int = 0
    total_nodes: int = 0
    total_edges: int = 0
    trigger: str = ""  # what caused this snapshot ("build", "refactor", "evolution")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "score": round(self.score, 3),
            "grade": self.grade,
            "modularity": round(self.modularity, 3),
            "coupling": round(self.coupling, 3),
            "cycles": self.cycles,
            "god_modules": self.god_modules,
            "max_fan_in": self.max_fan_in,
            "max_fan_out": self.max_fan_out,
            "total_nodes": self.total_nodes,
            "total_edges": self.total_edges,
            "trigger": self.trigger,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> MetricsSnapshot:
        return cls(
            timestamp=d.get("timestamp", ""),
            score=d.get("score", 0.0),
            grade=d.get("grade", ""),
            modularity=d.get("modularity", 0.0),
            coupling=d.get("coupling", 0.0),
            cycles=d.get("cycles", 0),
            god_modules=d.get("god_modules", 0),
            max_fan_in=d.get("max_fan_in", 0),
            max_fan_out=d.get("max_fan_out", 0),
            total_nodes=d.get("total_nodes", 0),
            total_edges=d.get("total_edges", 0),
            trigger=d.get("trigger", ""),
        )


# ═══════════════════════════════════════════════════════════════════════
# Strategy Score
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class StrategyScore:
    """Effectiveness score for an architecture strategy."""

    strategy: str  # e.g. "module_split", "fan_out_reduction"
    times_used: int = 0
    times_succeeded: int = 0
    avg_score_improvement: float = 0.0
    avg_modularity_change: float = 0.0
    avg_coupling_change: float = 0.0
    total_score_delta: float = 0.0
    effectiveness: float = 0.0  # 0-1 composite score

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy": self.strategy,
            "times_used": self.times_used,
            "times_succeeded": self.times_succeeded,
            "avg_score_improvement": round(self.avg_score_improvement, 4),
            "avg_modularity_change": round(self.avg_modularity_change, 4),
            "avg_coupling_change": round(self.avg_coupling_change, 4),
            "total_score_delta": round(self.total_score_delta, 4),
            "effectiveness": round(self.effectiveness, 3),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> StrategyScore:
        return cls(
            strategy=d["strategy"],
            times_used=d.get("times_used", 0),
            times_succeeded=d.get("times_succeeded", 0),
            avg_score_improvement=d.get("avg_score_improvement", 0.0),
            avg_modularity_change=d.get("avg_modularity_change", 0.0),
            avg_coupling_change=d.get("avg_coupling_change", 0.0),
            total_score_delta=d.get("total_score_delta", 0.0),
            effectiveness=d.get("effectiveness", 0.0),
        )


# ═══════════════════════════════════════════════════════════════════════
# Pattern
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class ArchPattern:
    """A mined architecture pattern from historical decisions."""

    pattern_id: str
    description: str
    frequency: int = 0
    avg_impact: float = 0.0
    confidence: float = 0.0  # 0-1 how reliable is this pattern
    tags: List[str] = field(default_factory=list)
    examples: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            "description": self.description,
            "frequency": self.frequency,
            "avg_impact": round(self.avg_impact, 3),
            "confidence": round(self.confidence, 3),
            "tags": self.tags,
            "examples": self.examples[:5],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> ArchPattern:
        return cls(
            pattern_id=d["pattern_id"],
            description=d["description"],
            frequency=d.get("frequency", 0),
            avg_impact=d.get("avg_impact", 0.0),
            confidence=d.get("confidence", 0.0),
            tags=d.get("tags", []),
            examples=d.get("examples", []),
        )


# ═══════════════════════════════════════════════════════════════════════
# Intelligence Report
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class MemoryIntelligenceReport:
    """Output of memory intelligence analysis."""

    strategy_scores: List[StrategyScore] = field(default_factory=list)
    patterns: List[ArchPattern] = field(default_factory=list)
    metrics_trend: List[MetricsSnapshot] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy_scores": [s.to_dict() for s in self.strategy_scores],
            "patterns": [p.to_dict() for p in self.patterns],
            "metrics_trend": [m.to_dict() for m in self.metrics_trend[-20:]],
            "recommendations": self.recommendations,
            "summary": {
                "strategies_analyzed": len(self.strategy_scores),
                "patterns_found": len(self.patterns),
                "metrics_snapshots": len(self.metrics_trend),
            },
        }

    def format(self) -> str:
        lines = ["Architecture Memory Intelligence"]
        lines.append(f"  Strategies analyzed: {len(self.strategy_scores)}")
        lines.append(f"  Patterns found: {len(self.patterns)}")
        lines.append(f"  Metrics snapshots: {len(self.metrics_trend)}")

        if self.strategy_scores:
            lines.append("\nStrategy Effectiveness (ranked):")
            ranked = sorted(self.strategy_scores,
                            key=lambda s: s.effectiveness, reverse=True)
            for s in ranked:
                bar = "█" * int(s.effectiveness * 10)
                lines.append(
                    f"  {s.strategy:<25} {bar:<10} "
                    f"{s.effectiveness:.0%} ({s.times_succeeded}/{s.times_used})"
                )

        if self.patterns:
            lines.append("\nMined Patterns:")
            for p in self.patterns[:10]:
                sign = "+" if p.avg_impact >= 0 else ""
                lines.append(
                    f"  [{p.confidence:.0%}] {p.description} "
                    f"(impact: {sign}{p.avg_impact:.3f}, used {p.frequency}x)"
                )

        if self.metrics_trend:
            lines.append("\nMetrics Trend (recent):")
            recent = self.metrics_trend[-5:]
            for m in recent:
                lines.append(
                    f"  {m.timestamp[:10]} — {m.grade} {m.score:.2f} "
                    f"mod={m.modularity:.3f} cyc={m.cycles} god={m.god_modules}"
                )

        if self.recommendations:
            lines.append("\nRecommendations:")
            for r in self.recommendations:
                lines.append(f"  → {r}")

        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# Metrics History
# ═══════════════════════════════════════════════════════════════════════


def record_metrics_snapshot(
    project_root: Path,
    score: float = 0.0,
    grade: str = "",
    modularity: float = 0.0,
    coupling: float = 0.0,
    cycles: int = 0,
    god_modules: int = 0,
    max_fan_in: int = 0,
    max_fan_out: int = 0,
    total_nodes: int = 0,
    total_edges: int = 0,
    trigger: str = "build",
) -> MetricsSnapshot:
    """Record a metrics snapshot to history."""
    snap = MetricsSnapshot(
        timestamp=datetime.now(timezone.utc).isoformat(),
        score=score,
        grade=grade,
        modularity=modularity,
        coupling=coupling,
        cycles=cycles,
        god_modules=god_modules,
        max_fan_in=max_fan_in,
        max_fan_out=max_fan_out,
        total_nodes=total_nodes,
        total_edges=total_edges,
        trigger=trigger,
    )

    history = load_metrics_history(project_root)
    history.append(snap)
    # Keep last 200 entries
    history = history[-200:]
    _save_metrics_history(project_root, history)
    logger.info("Recorded metrics snapshot: %s %s", grade, score)
    return snap


def load_metrics_history(project_root: Path) -> List[MetricsSnapshot]:
    """Load metrics history from disk."""
    path = project_root / ".codegraph" / "memory" / METRICS_HISTORY_FILE
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [MetricsSnapshot.from_dict(d) for d in data]


def _save_metrics_history(
    project_root: Path,
    history: List[MetricsSnapshot],
) -> None:
    mem_dir = project_root / ".codegraph" / "memory"
    mem_dir.mkdir(parents=True, exist_ok=True)
    path = mem_dir / METRICS_HISTORY_FILE
    path.write_text(
        json.dumps([s.to_dict() for s in history], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ═══════════════════════════════════════════════════════════════════════
# Pattern Mining
# ═══════════════════════════════════════════════════════════════════════


def mine_patterns(memory: ArchitectureMemory) -> List[ArchPattern]:
    """Mine patterns from architecture decisions and experiments.

    Looks for:
      - Frequently successful strategies (by tags)
      - Common improvement patterns
      - Strategies that consistently harm score
    """
    patterns: List[ArchPattern] = []

    # Group decisions by tags
    tag_outcomes: Dict[str, List[Tuple[str, float]]] = {}
    for d in memory.decisions:
        for tag in d.tags:
            tag_outcomes.setdefault(tag, []).append(
                (d.result, d.health_delta)
            )

    # Find high-frequency successful tags
    pid = 0
    for tag, outcomes in sorted(tag_outcomes.items(),
                                key=lambda x: len(x[1]), reverse=True):
        if len(outcomes) < 2:
            continue
        successes = sum(1 for r, _ in outcomes if r == "success")
        avg_delta = sum(d for _, d in outcomes) / len(outcomes)
        confidence = successes / len(outcomes)

        pid += 1
        patterns.append(ArchPattern(
            pattern_id=f"p{pid:04d}",
            description=f"Strategy '{tag}' has been used {len(outcomes)} times",
            frequency=len(outcomes),
            avg_impact=avg_delta,
            confidence=confidence,
            tags=[tag],
            examples=[d.decision for d in memory.decisions
                      if tag in d.tags][:5],
        ))

    # Find experiment lessons
    lesson_counts: Counter[str] = Counter()
    for exp in memory.experiments:
        if exp.lesson:
            lesson_counts[exp.lesson] += 1

    for lesson, count in lesson_counts.most_common(5):
        if count < 2:
            continue
        pid += 1
        patterns.append(ArchPattern(
            pattern_id=f"p{pid:04d}",
            description=f"Recurring lesson: {lesson}",
            frequency=count,
            avg_impact=0.0,
            confidence=min(count / 5.0, 1.0),
            tags=["lesson"],
            examples=[],
        ))

    # Find score improvement patterns from metrics history
    for exp in memory.experiments:
        delta = exp.health_after - exp.health_before
        if abs(delta) > 0.05 and exp.outcome == "merged":
            pid += 1
            direction = "improved" if delta > 0 else "degraded"
            patterns.append(ArchPattern(
                pattern_id=f"p{pid:04d}",
                description=f"Experiment '{exp.branch_name}' {direction} health by {abs(delta):.2f}",
                frequency=1,
                avg_impact=delta,
                confidence=0.8,
                tags=["experiment", direction],
                examples=[exp.description],
            ))

    return patterns


# ═══════════════════════════════════════════════════════════════════════
# Strategy Scoring
# ═══════════════════════════════════════════════════════════════════════


def score_strategies(memory: ArchitectureMemory) -> List[StrategyScore]:
    """Score architecture strategies by historical effectiveness.

    Analyzes decisions tagged with strategy types and computes
    success rates, average improvements, and composite effectiveness.
    """
    # Known strategy types (from arch_search)
    strategy_tags = {
        "module_split", "fan_out_reduction", "fan_in_reduction",
        "subsystem_boundary", "dependency_inversion", "component_extraction",
        "cycle_break", "deep_chain_reduction", "refactor", "governance",
    }

    strategy_data: Dict[str, List[DecisionRecord]] = {}
    for d in memory.decisions:
        matched_tags = strategy_tags & set(d.tags)
        for tag in matched_tags:
            strategy_data.setdefault(tag, []).append(d)

    # Also use experiment data
    for exp in memory.experiments:
        # Try to infer strategy from branch name or description
        for strategy in strategy_tags:
            keyword = strategy.replace("_", " ").replace("-", " ")
            if keyword in exp.branch_name.lower() or keyword in exp.description.lower():
                # Create a synthetic decision record
                d = DecisionRecord(
                    decision_id=exp.experiment_id,
                    decision=exp.description,
                    reason="",
                    result="success" if exp.outcome == "merged" else "failed",
                    health_delta=exp.health_after - exp.health_before,
                    tags=[strategy],
                )
                strategy_data.setdefault(strategy, []).append(d)

    scores: List[StrategyScore] = []
    for strategy, decisions in strategy_data.items():
        used = len(decisions)
        succeeded = sum(1 for d in decisions if d.result == "success")
        deltas = [d.health_delta for d in decisions if d.health_delta != 0.0]
        avg_improvement = sum(deltas) / len(deltas) if deltas else 0.0
        total_delta = sum(deltas)

        # Composite effectiveness: success_rate * 0.5 + impact_factor * 0.5
        success_rate = succeeded / used if used > 0 else 0.0
        impact_factor = min(max(avg_improvement + 0.5, 0.0), 1.0)
        effectiveness = success_rate * 0.5 + impact_factor * 0.5

        scores.append(StrategyScore(
            strategy=strategy,
            times_used=used,
            times_succeeded=succeeded,
            avg_score_improvement=avg_improvement,
            total_score_delta=total_delta,
            effectiveness=effectiveness,
        ))

    return sorted(scores, key=lambda s: s.effectiveness, reverse=True)


# ═══════════════════════════════════════════════════════════════════════
# Recommendations from Memory
# ═══════════════════════════════════════════════════════════════════════


def generate_recommendations(
    memory: ArchitectureMemory,
    metrics_history: List[MetricsSnapshot],
    strategy_scores: List[StrategyScore],
) -> List[str]:
    """Generate actionable recommendations from memory analysis."""
    recs: List[str] = []

    # 1. Recommend best-performing strategies
    effective = [s for s in strategy_scores if s.effectiveness > 0.6
                 and s.times_used >= 2]
    for s in effective[:3]:
        recs.append(
            f"'{s.strategy}' has {s.effectiveness:.0%} effectiveness "
            f"across {s.times_used} uses — prioritize this strategy"
        )

    # 2. Warn about poorly-performing strategies
    poor = [s for s in strategy_scores if s.effectiveness < 0.3
            and s.times_used >= 2]
    for s in poor[:2]:
        recs.append(
            f"'{s.strategy}' has low effectiveness ({s.effectiveness:.0%}) "
            f"— consider alternative approaches"
        )

    # 3. Score trend analysis
    if len(metrics_history) >= 3:
        recent = metrics_history[-3:]
        score_trend = recent[-1].score - recent[0].score
        if score_trend > 0.05:
            recs.append(
                f"Architecture score trending up ({score_trend:+.3f}) "
                f"— current approach is working"
            )
        elif score_trend < -0.05:
            recs.append(
                f"Architecture score trending down ({score_trend:+.3f}) "
                f"— review recent changes"
            )

    # 4. God module trend
    if len(metrics_history) >= 2:
        latest = metrics_history[-1]
        previous = metrics_history[-2]
        if latest.god_modules > previous.god_modules:
            recs.append(
                f"God modules increased ({previous.god_modules} → "
                f"{latest.god_modules}) — consider module_split strategy"
            )

    # 5. Cycle detection trend
    if len(metrics_history) >= 2:
        latest = metrics_history[-1]
        previous = metrics_history[-2]
        if latest.cycles > previous.cycles:
            recs.append(
                f"Cycles increased ({previous.cycles} → {latest.cycles}) "
                f"— apply cycle_break strategy"
            )

    # 6. Recommend if no recent decisions
    if not memory.decisions:
        recs.append("No architecture decisions recorded yet — start tracking")

    return recs


# ═══════════════════════════════════════════════════════════════════════
# Full Intelligence Pipeline
# ═══════════════════════════════════════════════════════════════════════


def analyze_memory(project_root: Path) -> MemoryIntelligenceReport:
    """Run full memory intelligence analysis.

    Mines patterns from past decisions, scores strategies by
    effectiveness, analyzes metrics trends, and generates
    recommendations.

    Returns a :class:`MemoryIntelligenceReport`.
    """
    memory = load_memory(project_root)
    metrics_history = load_metrics_history(project_root)
    patterns = mine_patterns(memory)
    strategy_scores = score_strategies(memory)
    recommendations = generate_recommendations(
        memory, metrics_history, strategy_scores,
    )

    return MemoryIntelligenceReport(
        strategy_scores=strategy_scores,
        patterns=patterns,
        metrics_trend=metrics_history,
        recommendations=recommendations,
    )


def get_strategy_ranking(project_root: Path) -> List[StrategyScore]:
    """Get strategies ranked by historical effectiveness.

    Used by evolution engine to prefer strategies that worked before.
    """
    memory = load_memory(project_root)
    return score_strategies(memory)


def save_strategy_scores(
    project_root: Path,
    scores: List[StrategyScore],
) -> Path:
    """Save strategy scores to disk."""
    mem_dir = project_root / ".codegraph" / "memory"
    mem_dir.mkdir(parents=True, exist_ok=True)
    path = mem_dir / STRATEGY_SCORES_FILE
    path.write_text(
        json.dumps([s.to_dict() for s in scores], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path
