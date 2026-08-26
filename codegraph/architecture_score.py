"""codegraph.architecture_score — Architecture score persistence and facade.

The canonical score computation lives in ``architecture_scoring``
(``compute_architecture_index``); this module provides the
``ArchitectureScore`` dataclass, its persistence (``save``/``load``),
the partition-blended ``compute_score`` facade, and ``compare_scores``
used by ``codegraph score --compare``.

Output file: .codegraph/architecture_score.json
CLI command: codegraph score
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from codegraph.logging_config import get_logger

logger = get_logger("architecture_score")

SCORE_FILE = "architecture_score.json"

# ── Weight configuration ──────────────────────────────────────────────
W_MODULARITY = 0.30
W_ISOLATION = 0.25
W_COUPLING = 0.20
W_FANOUT = 0.15
W_CYCLE = 0.10


# ═══════════════════════════════════════════════════════════════════════
# Score Dataclass
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class ArchitectureScore:
    """Architecture quality score with individual metrics."""

    score: float = 0.0
    grade: str = "F"
    metrics: Dict[str, float] = field(default_factory=dict)
    subsystem_scores: Dict[str, float] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": round(self.score, 4),
            "grade": self.grade,
            "metrics": {k: round(v, 4) for k, v in self.metrics.items()},
            "subsystem_scores": {
                k: round(v, 4) for k, v in self.subsystem_scores.items()
            },
            "metadata": self.metadata,
        }

    def format(self) -> str:
        lines = [f"Architecture Score: {self.score:.2%} ({self.grade})"]
        lines.append("  Metrics:")

        if "coupling_score" in self.metrics:
            lines.append(f"    Coupling Score:         {self.metrics.get('coupling_score', 0):.3f} (weight 0.25)")
            lines.append(f"    Cohesion Score:         {self.metrics.get('cohesion_score', 0):.3f} (weight 0.20)")
            lines.append(f"    Layer Integrity:        {self.metrics.get('layer_integrity', 0):.3f} (weight 0.15)")
            lines.append(f"    Cycle Penalty:          {self.metrics.get('cycle_penalty', 0):.3f} (weight 0.15)")
            lines.append(f"    Architecture Drift:     {self.metrics.get('architecture_drift', 0):.3f} (weight 0.10)")
            lines.append(f"    Test Coverage:          {self.metrics.get('test_coverage', 0):.3f} (weight 0.10)")
            lines.append(f"    Dead Code Ratio:        {self.metrics.get('dead_code_ratio', 0):.3f} (weight 0.05)")
            lines.append(f"    Pattern Consistency:    {self.metrics.get('pattern_consistency', 0):.3f} (influence)")
            lines.append(f"    Penalty Total:          {self.metrics.get('penalty_total', 0):.3f}")
        elif "structural_health" in self.metrics:
            lines.append(f"    Structural Health:      {self.metrics.get('structural_health', 0):.3f} (weight 0.25)")
            lines.append(f"    Dependency Correctness: {self.metrics.get('dependency_correctness', 0):.3f} (weight 0.25)")
            lines.append(f"    Behavioral Integrity:   {self.metrics.get('behavioral_integrity', 0):.3f} (weight 0.20)")
            lines.append(f"    Architecture Stability: {self.metrics.get('architecture_stability', 0):.3f} (weight 0.15)")
            lines.append(f"    Intent Alignment:       {self.metrics.get('intent_alignment', 0):.3f} (weight 0.15)")
            lines.append(f"    Penalty Total:          {self.metrics.get('penalty_total', 0):.3f}")
        else:
            lines.append(f"    Modularity:          {self.metrics.get('modularity', 0):.3f}  (weight {W_MODULARITY})")
            lines.append(f"    Subsystem Isolation: {self.metrics.get('subsystem_isolation', 0):.3f}  (weight {W_ISOLATION})")
            lines.append(f"    Coupling:            {self.metrics.get('coupling', 0):.3f}  (weight {W_COUPLING})")
            lines.append(f"    Fan-out Penalty:     {self.metrics.get('fanout_penalty', 0):.3f}  (weight {W_FANOUT})")
            lines.append(f"    Cycle Penalty:       {self.metrics.get('cycle_penalty', 0):.3f}  (weight {W_CYCLE})")

        if self.subsystem_scores:
            lines.append("\n  Subsystem Scores:")
            for name, sc in sorted(self.subsystem_scores.items(), key=lambda x: x[1]):
                bar = "█" * int(sc * 20) + "░" * (20 - int(sc * 20))
                lines.append(f"    {name:30s} {sc:.2%}  {bar}")

        if self.metadata:
            lines.append("\n  Details:")
            for k, v in self.metadata.items():
                lines.append(f"    {k}: {v}")

        return "\n".join(lines)

    def save(self, project_root: Path) -> Path:
        path = project_root / ".codegraph" / SCORE_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("Architecture score saved: %s", path)
        return path

    @classmethod
    def load(cls, project_root: Path) -> Optional["ArchitectureScore"]:
        """Load a previously saved baseline score."""
        path = project_root / ".codegraph" / SCORE_FILE
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(
                score=data.get("score", 0.0),
                grade=data.get("grade", "F"),
                metrics=data.get("metrics", {}),
                subsystem_scores=data.get("subsystem_scores", {}),
                metadata=data.get("metadata", {}),
            )
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load score: %s", exc)
            return None


# ═══════════════════════════════════════════════════════════════════════
# Score Computation
# ═══════════════════════════════════════════════════════════════════════


def compute_score(project_root: Path) -> ArchitectureScore:
    """Compute architecture score via the multi-axis architecture scoring engine."""
    from codegraph.architecture_scoring import (
        compute_architecture_index,
        _grade,
    )
    from codegraph.graph_partitioning import load_or_build_partitions
    from codegraph.architecture_graph import ArchitectureGraph

    index = compute_architecture_index(project_root)
    graph = ArchitectureGraph.load(project_root)
    partitions = load_or_build_partitions(project_root, graph)

    metrics = dict(index.dimensions)
    metrics["penalty_total"] = sum(index.penalties.values()) if index.penalties else 0.0

    partition_scores: Dict[str, float] = {}
    total_nodes = 0
    weighted_sum = 0.0
    for pid, part in partitions.partitions.items():
        size = len(part.nodes)
        if size <= 1:
            continue  # single-node partitions have no internal structure to score
        internal = len(part.internal_edges)
        boundary = len(part.boundary_nodes)
        if internal == 0 and boundary == 0:
            continue  # partitions with no edge participation have no measurable structure
        density = min(1.0, internal / max(1.0, float(size)))
        boundary_penalty = min(1.0, boundary / max(1.0, size))
        part_score = max(0.0, min(1.0, (0.7 * density) + (0.3 * (1.0 - boundary_penalty))))
        partition_scores[pid] = part_score
        weighted_sum += part_score * size
        total_nodes += size

    partition_weighted_score = (weighted_sum / total_nodes) if total_nodes > 0 else index.score
    # Blend global architecture quality with partition subsystem quality.
    # Global measures coupling, cohesion, cycles, layers, drift.
    # Partition measures subsystem density and isolation.
    blended_score = 0.5 * index.score + 0.5 * partition_weighted_score
    metrics["partition_weighted_score"] = partition_weighted_score

    return ArchitectureScore(
        score=blended_score,
        grade=_grade(blended_score),
        metrics=metrics,
        subsystem_scores=partition_scores,
        metadata={
            **index.metadata,
            "penalties": index.penalties,
            "scoring_model": "multi_axis_v2",
            "global_score": index.score,
            "partition_count": len(partition_scores),
        },
    )


def compare_scores(
    baseline: ArchitectureScore,
    current: ArchitectureScore,
) -> Dict[str, Any]:
    """Compare two scores and return the diff."""
    delta = current.score - baseline.score
    metric_deltas = {}
    for key in baseline.metrics:
        old_val = baseline.metrics.get(key, 0.0)
        new_val = current.metrics.get(key, 0.0)
        metric_deltas[key] = round(new_val - old_val, 4)

    improved = delta >= 0
    no_regression = delta >= -0.05  # Allow up to 5% regression

    return {
        "baseline_score": round(baseline.score, 4),
        "current_score": round(current.score, 4),
        "delta": round(delta, 4),
        "improved": improved,
        "no_regression": no_regression,
        "merge_allowed": no_regression,
        "metric_deltas": metric_deltas,
        "baseline_grade": baseline.grade,
        "current_grade": current.grade,
    }


# ═══════════════════════════════════════════════════════════════════════
# Private Helpers
# ═══════════════════════════════════════════════════════════════════════
