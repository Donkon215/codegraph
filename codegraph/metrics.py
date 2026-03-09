"""codegraph.metrics — Build and health metrics collection.

Collects timing, count, and health metrics during graph operations.
Metrics can be emitted as JSON for agent consumption or displayed
as a human-readable dashboard.

Tasks P-014 / P-015.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Timer:
    """Measures elapsed time for a named operation."""

    name: str
    _start: float = field(default=0.0, repr=False)
    elapsed: float = 0.0

    def start(self) -> "Timer":
        self._start = time.perf_counter()
        return self

    def stop(self) -> float:
        self.elapsed = time.perf_counter() - self._start
        return self.elapsed

    def __enter__(self) -> "Timer":
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()


@dataclass
class BuildMetrics:
    """Metrics collected during a build operation."""

    files_scanned: int = 0
    nodes_extracted: int = 0
    edges_built: int = 0
    parse_errors: int = 0
    extraction_time: float = 0.0
    workflow_time: float = 0.0
    index_time: float = 0.0
    total_time: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "files_scanned": self.files_scanned,
            "nodes_extracted": self.nodes_extracted,
            "edges_built": self.edges_built,
            "parse_errors": self.parse_errors,
            "timings": {
                "extraction_s": round(self.extraction_time, 3),
                "workflow_s": round(self.workflow_time, 3),
                "index_s": round(self.index_time, 3),
                "total_s": round(self.total_time, 3),
            },
        }


@dataclass
class HealthMetrics:
    """Health dashboard data for a codegraph project."""

    total_nodes: int = 0
    total_edges: int = 0
    nodes_with_intent: int = 0
    nodes_missing_intent: int = 0
    stale_intents: int = 0
    layer_violations: int = 0
    dangling_rules: int = 0
    dead_code_candidates: int = 0
    policy_violations: int = 0

    @property
    def intent_coverage(self) -> float:
        """Fraction of nodes with intent annotations."""
        if self.total_nodes == 0:
            return 1.0
        return self.nodes_with_intent / self.total_nodes

    @property
    def health_score(self) -> float:
        """Overall health score (0.0–1.0).

        Weighted combination of:
          - Intent coverage (40%)
          - Absence of violations (30%)
          - Absence of stale intents (20%)
          - Absence of dead code (10%)
        """
        intent_score = self.intent_coverage

        violation_count = self.layer_violations + self.policy_violations
        violation_score = max(0.0, 1.0 - violation_count / max(self.total_nodes, 1))

        stale_score = max(0.0, 1.0 - self.stale_intents / max(self.total_nodes, 1))

        dead_score = max(0.0, 1.0 - self.dead_code_candidates / max(self.total_nodes, 1))

        return round(
            0.4 * intent_score
            + 0.3 * violation_score
            + 0.2 * stale_score
            + 0.1 * dead_score,
            3,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_nodes": self.total_nodes,
            "total_edges": self.total_edges,
            "intent_coverage": round(self.intent_coverage, 3),
            "nodes_with_intent": self.nodes_with_intent,
            "nodes_missing_intent": self.nodes_missing_intent,
            "stale_intents": self.stale_intents,
            "layer_violations": self.layer_violations,
            "dangling_rules": self.dangling_rules,
            "dead_code_candidates": self.dead_code_candidates,
            "policy_violations": self.policy_violations,
            "health_score": self.health_score,
        }

    def summary(self) -> str:
        """Human-readable health summary."""
        lines = [
            f"Nodes: {self.total_nodes}  Edges: {self.total_edges}",
            f"Intent coverage: {self.intent_coverage:.0%} "
            f"({self.nodes_with_intent}/{self.total_nodes})",
        ]
        issues = []
        if self.stale_intents:
            issues.append(f"{self.stale_intents} stale intents")
        if self.layer_violations:
            issues.append(f"{self.layer_violations} layer violations")
        if self.policy_violations:
            issues.append(f"{self.policy_violations} policy violations")
        if self.dangling_rules:
            issues.append(f"{self.dangling_rules} dangling rules")
        if self.dead_code_candidates:
            issues.append(f"{self.dead_code_candidates} dead code candidates")
        if issues:
            lines.append("Issues: " + ", ".join(issues))
        else:
            lines.append("No issues detected")
        lines.append(f"Health score: {self.health_score:.0%}")
        return "\n".join(lines)


class MetricsCollector:
    """Collects metrics during a codegraph session."""

    def __init__(self) -> None:
        self.build = BuildMetrics()
        self.health = HealthMetrics()
        self._timers: dict[str, Timer] = {}

    def timer(self, name: str) -> Timer:
        """Get or create a named timer."""
        if name not in self._timers:
            self._timers[name] = Timer(name=name)
        return self._timers[name]

    def to_dict(self) -> dict[str, Any]:
        return {
            "build": self.build.to_dict(),
            "health": self.health.to_dict(),
            "timers": {
                name: round(t.elapsed, 3) for name, t in self._timers.items()
            },
        }
