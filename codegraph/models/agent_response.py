"""codegraph.models.agent_response — Agent response data model.

Tasks B-011, B-020, B-027, B-028.
"""

from __future__ import annotations

import enum
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from codegraph.logging_config import get_logger
from codegraph.utils.formatting import format_json

logger = get_logger("models.agent_response")


# ── B-020  Repair action type enum ────────────────────────────────────


class RepairActionType(str, enum.Enum):
    """Valid agent repair action types."""

    CONNECT_CALL = "connect_call"
    ADD_IMPORT = "add_import"
    REMOVE_DEAD_CODE = "remove_dead_code"
    FLAG_FOR_HUMAN_REVIEW = "flag_for_human_review"

    def modifies_code(self) -> bool:
        """Return *True* for actions that change source files."""
        return self != RepairActionType.FLAG_FOR_HUMAN_REVIEW


# ── B-011  IntentProposal ─────────────────────────────────────────────


@dataclass
class IntentProposal:
    """An intent annotation the agent wants to apply."""

    node: str
    intent: str
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"node": self.node, "intent": self.intent}
        if self.tags:
            d["tags"] = self.tags
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> IntentProposal:
        return cls(node=d["node"], intent=d["intent"], tags=d.get("tags", []))


# ── B-011  RepairAction ───────────────────────────────────────────────


@dataclass
class RepairAction:
    """A concrete code-modification action proposed by the agent."""

    node: str
    action: str  # RepairActionType value
    target: Optional[str] = None
    reason: str = ""

    def __post_init__(self) -> None:
        # Validate action type
        try:
            RepairActionType(self.action)
        except ValueError:
            raise ValueError(
                f"Invalid repair action '{self.action}'. "
                f"Valid: {[a.value for a in RepairActionType]}"
            )

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"node": self.node, "action": self.action, "reason": self.reason}
        if self.target is not None:
            d["target"] = self.target
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> RepairAction:
        return cls(
            node=d["node"],
            action=d["action"],
            target=d.get("target"),
            reason=d.get("reason", ""),
        )


# ── B-011  WorkflowSuggestion ─────────────────────────────────────────


@dataclass
class WorkflowSuggestion:
    """A workflow policy rule the agent wants to add."""

    type: str
    source: str
    target: str
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "source": self.source,
            "target": self.target,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> WorkflowSuggestion:
        return cls(
            type=d["type"],
            source=d["source"],
            target=d["target"],
            reason=d.get("reason", ""),
        )


# ── B-011  AgentResponse ──────────────────────────────────────────────


@dataclass
class AgentResponse:
    """The agent_response.json file the agent writes for codegraph to apply."""

    cycle: int = 1
    graph_version: int = 1
    intents: List[IntentProposal] = field(default_factory=list)
    repairs: List[RepairAction] = field(default_factory=list)
    workflow_suggestions: List[WorkflowSuggestion] = field(default_factory=list)

    # ── B-027  Version validation ─────────────────────────────────────

    def validate_version(self, current_version: int) -> Tuple[bool, str]:
        """Check *graph_version* matches *current_version*.

        Returns ``(ok, message)`` — *ok* is False on mismatch.
        """
        if self.graph_version != current_version:
            return (
                False,
                f"Graph version mismatch: response targets v{self.graph_version} "
                f"but current graph is v{current_version}",
            )
        return True, "OK"

    # ── B-028  Cycle validation ───────────────────────────────────────

    def validate_cycle(self, expected_cycle: int) -> Tuple[bool, str]:
        """Warn (but don't reject) on cycle mismatch."""
        if self.cycle != expected_cycle:
            msg = (
                f"Cycle mismatch: response claims cycle {self.cycle} "
                f"but expected {expected_cycle}"
            )
            logger.warning(msg)
            return False, msg
        return True, "OK"

    # ── Serialization ─────────────────────────────────────────────────

    def to_json(self, compact: bool = False) -> str:
        data = {
            "cycle": self.cycle,
            "graph_version": self.graph_version,
            "intents": [i.to_dict() for i in self.intents],
            "repairs": [r.to_dict() for r in self.repairs],
            "workflow_suggestions": [s.to_dict() for s in self.workflow_suggestions],
        }
        return format_json(data, compact=compact)

    @classmethod
    def from_json(cls, text: str) -> AgentResponse:
        data = json.loads(text)
        return cls(
            cycle=data.get("cycle", 1),
            graph_version=data.get("graph_version", 1),
            intents=[IntentProposal.from_dict(d) for d in data.get("intents", [])],
            repairs=[RepairAction.from_dict(d) for d in data.get("repairs", [])],
            workflow_suggestions=[
                WorkflowSuggestion.from_dict(d) for d in data.get("workflow_suggestions", [])
            ],
        )
