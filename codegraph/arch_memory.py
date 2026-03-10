"""codegraph.arch_memory — Architecture decision memory.

Records architecture decisions, refactoring outcomes, and lessons
learned. Enables the system to learn from past experiments.

Stores:
  - decisions: architecture choices with rationale and outcome
  - patterns: successful architecture patterns
  - experiments: branch results (merged/rejected and why)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from codegraph.logging_config import get_logger

logger = get_logger("arch_memory")

MEMORY_DIR = "memory"
DECISIONS_FILE = "decisions.json"
EXPERIMENTS_FILE = "experiments.json"


@dataclass
class ArchDecision:
    """A recorded architecture decision."""

    decision_id: str
    decision: str
    reason: str
    result: str = ""  # "success", "partial", "failed", "pending"
    health_delta: float = 0.0
    metrics_before: Dict[str, Any] = field(default_factory=dict)
    metrics_after: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""
    related_nodes: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "decision_id": self.decision_id,
            "decision": self.decision,
            "reason": self.reason,
            "result": self.result,
            "timestamp": self.timestamp,
        }
        if self.health_delta:
            d["health_delta"] = round(self.health_delta, 3)
        if self.metrics_before:
            d["metrics_before"] = self.metrics_before
        if self.metrics_after:
            d["metrics_after"] = self.metrics_after
        if self.related_nodes:
            d["related_nodes"] = self.related_nodes[:20]
        if self.tags:
            d["tags"] = self.tags
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> ArchDecision:
        return cls(
            decision_id=d["decision_id"],
            decision=d["decision"],
            reason=d.get("reason", ""),
            result=d.get("result", "pending"),
            health_delta=d.get("health_delta", 0.0),
            metrics_before=d.get("metrics_before", {}),
            metrics_after=d.get("metrics_after", {}),
            timestamp=d.get("timestamp", ""),
            related_nodes=d.get("related_nodes", []),
            tags=d.get("tags", []),
        )


@dataclass
class ArchExperiment:
    """Record of a branch experiment."""

    experiment_id: str
    branch_name: str
    description: str
    outcome: str = ""  # "merged", "rejected", "abandoned"
    health_before: float = 0.0
    health_after: float = 0.0
    cycles_before: int = 0
    cycles_after: int = 0
    coupling_before: float = 0.0
    coupling_after: float = 0.0
    lesson: str = ""
    timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "branch_name": self.branch_name,
            "description": self.description,
            "outcome": self.outcome,
            "health_before": round(self.health_before, 3),
            "health_after": round(self.health_after, 3),
            "cycles_before": self.cycles_before,
            "cycles_after": self.cycles_after,
            "coupling_before": round(self.coupling_before, 4),
            "coupling_after": round(self.coupling_after, 4),
            "lesson": self.lesson,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> ArchExperiment:
        return cls(
            experiment_id=d["experiment_id"],
            branch_name=d.get("branch_name", ""),
            description=d.get("description", ""),
            outcome=d.get("outcome", ""),
            health_before=d.get("health_before", 0.0),
            health_after=d.get("health_after", 0.0),
            cycles_before=d.get("cycles_before", 0),
            cycles_after=d.get("cycles_after", 0),
            coupling_before=d.get("coupling_before", 0.0),
            coupling_after=d.get("coupling_after", 0.0),
            lesson=d.get("lesson", ""),
            timestamp=d.get("timestamp", ""),
        )


@dataclass
class ArchMemory:
    """Long-term architecture knowledge store."""

    decisions: List[ArchDecision] = field(default_factory=list)
    experiments: List[ArchExperiment] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decisions": [d.to_dict() for d in self.decisions],
            "experiments": [e.to_dict() for e in self.experiments],
            "summary": {
                "total_decisions": len(self.decisions),
                "total_experiments": len(self.experiments),
                "successful_experiments": sum(
                    1 for e in self.experiments if e.outcome == "merged"
                ),
                "rejected_experiments": sum(
                    1 for e in self.experiments if e.outcome == "rejected"
                ),
            },
        }

    def format(self) -> str:
        lines = ["Architecture Memory"]
        lines.append(f"  Decisions: {len(self.decisions)}")
        lines.append(f"  Experiments: {len(self.experiments)}")

        success = sum(1 for e in self.experiments if e.outcome == "merged")
        reject = sum(1 for e in self.experiments if e.outcome == "rejected")
        if self.experiments:
            lines.append(f"  Success rate: {success}/{len(self.experiments)}")

        if self.decisions:
            lines.append("\nRecent decisions:")
            for d in self.decisions[-5:]:
                lines.append(f"  [{d.result}] {d.decision}")
                if d.health_delta:
                    lines.append(f"    Health: {'+' if d.health_delta >= 0 else ''}{d.health_delta:.1f}")

        if self.experiments:
            lines.append("\nRecent experiments:")
            for e in self.experiments[-5:]:
                lines.append(f"  [{e.outcome}] {e.branch_name}: {e.description}")
                if e.lesson:
                    lines.append(f"    Lesson: {e.lesson}")

        return "\n".join(lines)


# ── Memory Operations ──────────────────────────────────────────────────


def load_memory(project_root: Path) -> ArchMemory:
    """Load architecture memory from disk."""
    mem = ArchMemory()
    mem_dir = project_root / ".codegraph" / MEMORY_DIR

    decisions_path = mem_dir / DECISIONS_FILE
    if decisions_path.exists():
        data = json.loads(decisions_path.read_text(encoding="utf-8"))
        mem.decisions = [ArchDecision.from_dict(d) for d in data.get("decisions", [])]

    experiments_path = mem_dir / EXPERIMENTS_FILE
    if experiments_path.exists():
        data = json.loads(experiments_path.read_text(encoding="utf-8"))
        mem.experiments = [ArchExperiment.from_dict(e) for e in data.get("experiments", [])]

    return mem


def save_memory(project_root: Path, memory: ArchMemory) -> None:
    """Save architecture memory to disk."""
    mem_dir = project_root / ".codegraph" / MEMORY_DIR
    mem_dir.mkdir(parents=True, exist_ok=True)

    decisions_path = mem_dir / DECISIONS_FILE
    decisions_path.write_text(
        json.dumps({"decisions": [d.to_dict() for d in memory.decisions]},
                   indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    experiments_path = mem_dir / EXPERIMENTS_FILE
    experiments_path.write_text(
        json.dumps({"experiments": [e.to_dict() for e in memory.experiments]},
                   indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    logger.info("Saved architecture memory: %d decisions, %d experiments",
                len(memory.decisions), len(memory.experiments))


def record_decision(
    project_root: Path,
    decision: str,
    reason: str,
    result: str = "pending",
    health_delta: float = 0.0,
    related_nodes: Optional[List[str]] = None,
    tags: Optional[List[str]] = None,
) -> ArchDecision:
    """Record a new architecture decision."""
    memory = load_memory(project_root)

    next_id = f"d{len(memory.decisions) + 1:04d}"
    now = datetime.now(timezone.utc).isoformat()

    dec = ArchDecision(
        decision_id=next_id,
        decision=decision,
        reason=reason,
        result=result,
        health_delta=health_delta,
        timestamp=now,
        related_nodes=related_nodes or [],
        tags=tags or [],
    )
    memory.decisions.append(dec)
    save_memory(project_root, memory)
    logger.info("Recorded decision %s: %s", next_id, decision)
    return dec


def record_experiment(
    project_root: Path,
    branch_name: str,
    description: str,
    outcome: str,
    lesson: str = "",
    health_before: float = 0.0,
    health_after: float = 0.0,
    cycles_before: int = 0,
    cycles_after: int = 0,
) -> ArchExperiment:
    """Record the result of a branch experiment."""
    memory = load_memory(project_root)

    next_id = f"e{len(memory.experiments) + 1:04d}"
    now = datetime.now(timezone.utc).isoformat()

    exp = ArchExperiment(
        experiment_id=next_id,
        branch_name=branch_name,
        description=description,
        outcome=outcome,
        health_before=health_before,
        health_after=health_after,
        cycles_before=cycles_before,
        cycles_after=cycles_after,
        lesson=lesson,
        timestamp=now,
    )
    memory.experiments.append(exp)
    save_memory(project_root, memory)
    logger.info("Recorded experiment %s: %s → %s", next_id, branch_name, outcome)
    return exp


def get_relevant_decisions(
    project_root: Path,
    tags: Optional[List[str]] = None,
    result_filter: Optional[str] = None,
    limit: int = 10,
) -> List[ArchDecision]:
    """Query architecture decisions by tags or result."""
    memory = load_memory(project_root)
    results = memory.decisions

    if tags:
        tag_set = set(tags)
        results = [d for d in results if tag_set & set(d.tags)]

    if result_filter:
        results = [d for d in results if d.result == result_filter]

    return results[-limit:]


def get_experiment_success_rate(project_root: Path) -> float:
    """Get the success rate of architecture experiments."""
    memory = load_memory(project_root)
    if not memory.experiments:
        return 0.0
    merged = sum(1 for e in memory.experiments if e.outcome == "merged")
    return merged / len(memory.experiments)
