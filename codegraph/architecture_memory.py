"""codegraph.architecture_memory — Persistent architecture memory.

Persists architecture decisions, refactor history, simulation results,
and advisor findings so the system can learn from past architecture
evolution.

Stores in .codegraph/memory/:
  - decisions.json:   architecture choices with rationale and outcome
  - simulations.json: simulation result history per subsystem change
  - advice.json:      architecture advisor snapshot history

Dependencies: infrastructure (logging_config), stdlib only.
Must NOT depend on governance subsystem.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from codegraph.logging_config import get_logger

logger = get_logger("architecture_memory")

MEMORY_DIR = "memory"
DECISIONS_FILE = "decisions.json"
SIMULATIONS_FILE = "simulations.json"
ADVICE_FILE = "advice.json"
PATTERNS_FILE = "patterns.json"


# ── Data structures ───────────────────────────────────────────────────


@dataclass
class DecisionRecord:
    """A persisted architecture decision."""

    decision_id: str
    decision: str
    reason: str
    result: str = "pending"  # pending, success, partial, failed
    timestamp: str = ""
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "decision": self.decision,
            "reason": self.reason,
            "result": self.result,
            "timestamp": self.timestamp,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "DecisionRecord":
        return cls(
            decision_id=d["decision_id"],
            decision=d["decision"],
            reason=d.get("reason", ""),
            result=d.get("result", "pending"),
            timestamp=d.get("timestamp", ""),
            tags=d.get("tags", []),
        )


@dataclass
class SimulationRecord:
    """A persisted architecture simulation result."""

    simulation_id: str
    subsystem_name: str
    recommendation: str  # accept, review, reject
    safe: bool
    timestamp: str = ""
    reasons: List[str] = field(default_factory=list)
    predictions: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "simulation_id": self.simulation_id,
            "subsystem_name": self.subsystem_name,
            "recommendation": self.recommendation,
            "safe": self.safe,
            "timestamp": self.timestamp,
            "reasons": self.reasons,
            "predictions": self.predictions,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SimulationRecord":
        return cls(
            simulation_id=d["simulation_id"],
            subsystem_name=d.get("subsystem_name", ""),
            recommendation=d.get("recommendation", "accept"),
            safe=d.get("safe", True),
            timestamp=d.get("timestamp", ""),
            reasons=d.get("reasons", []),
            predictions=d.get("predictions", []),
        )


@dataclass
class AdviceRecord:
    """A persisted architecture advisor snapshot."""

    advice_id: str
    grade: str
    score: float
    smell_count: int
    suggestion_count: int
    timestamp: str = ""
    top_smells: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "advice_id": self.advice_id,
            "grade": self.grade,
            "score": round(self.score, 3),
            "smell_count": self.smell_count,
            "suggestion_count": self.suggestion_count,
            "timestamp": self.timestamp,
            "top_smells": self.top_smells[:5],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AdviceRecord":
        return cls(
            advice_id=d["advice_id"],
            grade=d.get("grade", "A"),
            score=d.get("score", 1.0),
            smell_count=d.get("smell_count", 0),
            suggestion_count=d.get("suggestion_count", 0),
            timestamp=d.get("timestamp", ""),
            top_smells=d.get("top_smells", []),
        )


# ── Storage helpers ───────────────────────────────────────────────────


def _load_json_list(path: Path, key: str) -> List[Dict[str, Any]]:
    """Load a list of records from a JSON file keyed by *key*."""
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get(key, [])


def _save_json_list(path: Path, key: str, items: List[Dict[str, Any]]) -> None:
    """Persist a list of record dicts to *path* under *key*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({key: items}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ── Public API ────────────────────────────────────────────────────────


def save_decision(
    project_root: Path,
    decision: str,
    reason: str,
    result: str = "pending",
    tags: Optional[List[str]] = None,
) -> DecisionRecord:
    """Persist an architecture decision with its rationale and outcome.

    Args:
        project_root: Project root directory (where .codegraph lives).
        decision: Short description of the architecture decision.
        reason: Rationale for the decision.
        result: Outcome status – ``pending``, ``success``, ``partial``, or ``failed``.
        tags: Optional classification tags (e.g. ``["refactor", "cycle"]``).

    Returns:
        The newly created and persisted :class:`DecisionRecord`.
    """
    path = project_root / ".codegraph" / MEMORY_DIR / DECISIONS_FILE
    existing = [DecisionRecord.from_dict(d) for d in _load_json_list(path, "decisions")]

    record = DecisionRecord(
        decision_id=f"d{len(existing) + 1:04d}",
        decision=decision,
        reason=reason,
        result=result,
        timestamp=datetime.now(timezone.utc).isoformat(),
        tags=tags or [],
    )
    existing.append(record)
    _save_json_list(path, "decisions", [r.to_dict() for r in existing])
    logger.info("Saved decision %s: %s", record.decision_id, decision)
    return record


def load_decisions(
    project_root: Path,
    result_filter: Optional[str] = None,
    tags: Optional[List[str]] = None,
    limit: int = 50,
) -> List[DecisionRecord]:
    """Load persisted architecture decisions, optionally filtered.

    Args:
        project_root: Project root directory.
        result_filter: If set, only return records with this ``result`` value.
        tags: If set, only return records that share at least one tag.
        limit: Maximum number of records to return (most recent first).

    Returns:
        Filtered list of :class:`DecisionRecord`, up to *limit* items.
    """
    path = project_root / ".codegraph" / MEMORY_DIR / DECISIONS_FILE
    records = [DecisionRecord.from_dict(d) for d in _load_json_list(path, "decisions")]

    if result_filter:
        records = [r for r in records if r.result == result_filter]
    if tags:
        tag_set = set(tags)
        records = [r for r in records if tag_set & set(r.tags)]

    return records[-limit:]


def record_simulation(
    project_root: Path,
    subsystem_name: str,
    recommendation: str,
    safe: bool,
    reasons: Optional[List[str]] = None,
    predictions: Optional[List[Dict[str, Any]]] = None,
) -> SimulationRecord:
    """Record the outcome of an architecture simulation.

    Call this after running ``codegraph arch-simulate`` so the history of
    simulation decisions is preserved and can inform future choices.

    Args:
        project_root: Project root directory.
        subsystem_name: Name of the subsystem that was simulated.
        recommendation: Simulation recommendation: ``accept``, ``review``, or ``reject``.
        safe: Whether the simulation engine considered the change safe.
        reasons: Human-readable reasons from the simulation result.
        predictions: Raw prediction dicts (from ``ArchSimulationResult.to_dict()``).

    Returns:
        The newly created and persisted :class:`SimulationRecord`.
    """
    path = project_root / ".codegraph" / MEMORY_DIR / SIMULATIONS_FILE
    existing = [SimulationRecord.from_dict(d) for d in _load_json_list(path, "simulations")]

    record = SimulationRecord(
        simulation_id=f"s{len(existing) + 1:04d}",
        subsystem_name=subsystem_name,
        recommendation=recommendation,
        safe=safe,
        timestamp=datetime.now(timezone.utc).isoformat(),
        reasons=reasons or [],
        predictions=predictions or [],
    )
    existing.append(record)
    _save_json_list(path, "simulations", [r.to_dict() for r in existing])
    logger.info(
        "Recorded simulation %s for '%s' → %s",
        record.simulation_id,
        subsystem_name,
        recommendation,
    )
    return record


def record_advice(
    project_root: Path,
    grade: str,
    score: float,
    smells: Optional[List[Dict[str, Any]]] = None,
    suggestions: Optional[List[Dict[str, Any]]] = None,
) -> AdviceRecord:
    """Record a snapshot of architecture advisor findings.

    Call this after running ``codegraph architect`` to build a historical
    trend of system health scores and detected smells.

    Args:
        project_root: Project root directory.
        grade: Letter health grade from the advisor (``A``–``F``).
        score: Numeric health score in ``[0.0, 1.0]``.
        smells: List of smell dicts (from ``ArchAdvice.to_dict()["smells"]``).
        suggestions: List of suggestion dicts (from ``ArchAdvice.to_dict()["suggestions"]``).

    Returns:
        The newly created and persisted :class:`AdviceRecord`.
    """
    resolved_smells = smells or []
    resolved_suggestions = suggestions or []

    path = project_root / ".codegraph" / MEMORY_DIR / ADVICE_FILE
    existing = [AdviceRecord.from_dict(d) for d in _load_json_list(path, "advice")]

    record = AdviceRecord(
        advice_id=f"a{len(existing) + 1:04d}",
        grade=grade,
        score=score,
        smell_count=len(resolved_smells),
        suggestion_count=len(resolved_suggestions),
        timestamp=datetime.now(timezone.utc).isoformat(),
        top_smells=resolved_smells[:5],
    )
    existing.append(record)
    _save_json_list(path, "advice", [r.to_dict() for r in existing])
    logger.info(
        "Recorded advice %s: grade=%s score=%.2f smells=%d",
        record.advice_id,
        grade,
        score,
        len(resolved_smells),
    )
    return record


def load_advice_history(
    project_root: Path,
    limit: int = 20,
) -> List[AdviceRecord]:
    """Load persisted architecture advisor snapshots.

    Args:
        project_root: Project root directory.
        limit: Maximum number of records to return (most recent first).

    Returns:
        List of :class:`AdviceRecord`, up to *limit* items.
    """
    path = project_root / ".codegraph" / MEMORY_DIR / ADVICE_FILE
    records = [AdviceRecord.from_dict(d) for d in _load_json_list(path, "advice")]
    return records[-limit:]


def learn_interaction_patterns(project_root: Path, limit: int = 200) -> List[Dict[str, Any]]:
    """Learn common architecture interaction patterns from workflow/history.

    Stores pattern frequency and confidence to .codegraph/memory/patterns.json.
    """
    workflow_path = project_root / ".codegraph" / "workflow" / "workflow.json"
    patterns: Dict[str, int] = {}

    if workflow_path.exists():
        try:
            workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
            for edge in workflow.get("edges", []):
                src = edge.get("source", "")
                tgt = edge.get("target", "")
                if not src or not tgt:
                    continue
                src_parts = src.split("::")
                tgt_parts = tgt.split("::")
                if len(src_parts) >= 2 and len(tgt_parts) >= 2:
                    src_kind = src_parts[-2] if len(src_parts) >= 3 else src_parts[-1]
                    tgt_kind = tgt_parts[-2] if len(tgt_parts) >= 3 else tgt_parts[-1]
                    key = f"{src_kind} -> {tgt_kind}"
                    patterns[key] = patterns.get(key, 0) + 1
        except Exception:
            pass

    total = sum(patterns.values())
    entries: List[Dict[str, Any]] = []
    for pattern, occurrences in sorted(patterns.items(), key=lambda x: x[1], reverse=True)[:limit]:
        confidence = (occurrences / total) if total else 0.0
        entries.append({
            "pattern": pattern,
            "confidence": round(confidence, 4),
            "occurrences": occurrences,
        })

    out = project_root / ".codegraph" / MEMORY_DIR / PATTERNS_FILE
    _save_json_list(out, "patterns", entries)
    logger.info("Learned %d interaction patterns", len(entries))
    return entries
