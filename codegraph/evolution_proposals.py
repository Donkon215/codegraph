"""codegraph.evolution_proposals — Proposal layer between evolution and compiler.

The evolution engine produces *proposals* (structural improvement suggestions).
The architecture compiler is the sole authority that validates and applies them.

Proposals are stored at ``.codegraph/evolution/proposals.json``.

Workflow::

    arch_evolution  →  EvolutionProposal  →  architecture_compiler
       (suggest)         (persist)              (validate + apply)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from codegraph.logging_config import get_logger

logger = get_logger("evolution_proposals")

# Proposal statuses
STATUS_PENDING = "pending"
STATUS_ACCEPTED = "accepted"
STATUS_REJECTED = "rejected"
STATUS_EXPIRED = "expired"


@dataclass
class EvolutionProposal:
    """A single architecture improvement proposal from the evolution engine."""

    proposal_id: str
    strategy: str  # e.g. module_split, fan_out_reduction
    target_modules: List[str]
    predicted_score_delta: float
    safety_tier: str  # safe, medium, dangerous
    reason: str
    source_cycle: int = 0
    status: str = STATUS_PENDING
    rejection_reason: str = ""
    timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "strategy": self.strategy,
            "target_modules": self.target_modules,
            "predicted_score_delta": round(self.predicted_score_delta, 4),
            "safety_tier": self.safety_tier,
            "reason": self.reason,
            "source_cycle": self.source_cycle,
            "status": self.status,
            "rejection_reason": self.rejection_reason,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> EvolutionProposal:
        return cls(
            proposal_id=d["proposal_id"],
            strategy=d["strategy"],
            target_modules=d.get("target_modules", []),
            predicted_score_delta=d.get("predicted_score_delta", 0.0),
            safety_tier=d.get("safety_tier", "medium"),
            reason=d.get("reason", ""),
            source_cycle=d.get("source_cycle", 0),
            status=d.get("status", STATUS_PENDING),
            rejection_reason=d.get("rejection_reason", ""),
            timestamp=d.get("timestamp", ""),
        )

    def format(self) -> str:
        icon = {"pending": "○", "accepted": "✓", "rejected": "✗",
                "expired": "◌"}.get(self.status, "?")
        line = (
            f"{icon} [{self.proposal_id}] {self.strategy} → "
            f"{', '.join(self.target_modules)} "
            f"(Δ={self.predicted_score_delta:+.3f}, tier={self.safety_tier})"
        )
        if self.rejection_reason:
            line += f"\n    Rejected: {self.rejection_reason}"
        return line


@dataclass
class ProposalStore:
    """Collection of evolution proposals with persistence."""

    proposals: List[EvolutionProposal] = field(default_factory=list)

    def pending(self) -> List[EvolutionProposal]:
        return [p for p in self.proposals if p.status == STATUS_PENDING]

    def add(self, proposal: EvolutionProposal) -> None:
        self.proposals.append(proposal)

    def accept(self, proposal_id: str) -> bool:
        for p in self.proposals:
            if p.proposal_id == proposal_id:
                p.status = STATUS_ACCEPTED
                return True
        return False

    def reject(self, proposal_id: str, reason: str = "") -> bool:
        for p in self.proposals:
            if p.proposal_id == proposal_id:
                p.status = STATUS_REJECTED
                p.rejection_reason = reason
                return True
        return False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "proposals": [p.to_dict() for p in self.proposals],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> ProposalStore:
        proposals = [EvolutionProposal.from_dict(p)
                     for p in d.get("proposals", [])]
        return cls(proposals=proposals)

    def format(self) -> str:
        if not self.proposals:
            return "No evolution proposals."
        lines = [f"Evolution Proposals ({len(self.proposals)}):"]
        for p in self.proposals:
            lines.append(f"  {p.format()}")
        pending = len(self.pending())
        if pending:
            lines.append(f"\n  {pending} pending proposal(s)")
        return "\n".join(lines)


def _proposals_path(project_root: Path) -> Path:
    return project_root / ".codegraph" / "evolution" / "proposals.json"


def load_proposals(project_root: Path) -> ProposalStore:
    """Load proposals from disk."""
    path = _proposals_path(project_root)
    if not path.exists():
        return ProposalStore()
    data = json.loads(path.read_text(encoding="utf-8"))
    return ProposalStore.from_dict(data)


def save_proposals(project_root: Path, store: ProposalStore) -> Path:
    """Save proposals to disk."""
    path = _proposals_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(store.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Saved %d proposals to %s", len(store.proposals), path)
    return path


def create_proposal_from_evolution(
    result_dict: Dict[str, Any],
    cycle: int = 0,
) -> Optional[EvolutionProposal]:
    """Create a proposal from an evolution result's selected candidate.

    Args:
        result_dict: The evolution result dict containing selected strategy/target.
        cycle: The evolution cycle number.

    Returns:
        An EvolutionProposal if a strategy was selected, else None.
    """
    strategy = result_dict.get("selected_strategy", "")
    if not strategy:
        return None

    now = datetime.now(timezone.utc).isoformat()
    proposal_id = f"evo_{cycle}_{now[:10].replace('-', '')}"

    return EvolutionProposal(
        proposal_id=proposal_id,
        strategy=strategy,
        target_modules=result_dict.get("selected_target", "").split(", "),
        predicted_score_delta=result_dict.get("score_delta", 0.0),
        safety_tier=result_dict.get("safety_tier",
                                    result_dict.get("stages", [{}])[-1].get(
                                        "metrics", {}).get("safety_tier", "medium")),
        reason=f"Evolution cycle {cycle}: {strategy}",
        source_cycle=cycle,
        status=STATUS_PENDING,
        timestamp=now,
    )
