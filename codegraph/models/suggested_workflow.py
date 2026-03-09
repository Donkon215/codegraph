"""codegraph.models.suggested_workflow — SuggestedWorkflow rules & collection.

Tasks B-007, B-008, B-023, B-032.
"""

from __future__ import annotations

import enum
import fnmatch
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from codegraph.logging_config import get_logger
from codegraph.utils.formatting import format_json, iso_now

if TYPE_CHECKING:
    from codegraph.models.graph0 import Graph0Node
    from codegraph.models.graph1 import Graph1

logger = get_logger("models.suggested_workflow")


# ── B-023  Rule type enum ─────────────────────────────────────────────


class RuleType(str, enum.Enum):
    """Suggested workflow rule type."""

    REQUIRED_CALL = "required_call"
    FORBIDDEN_CALL = "forbidden_call"

    def is_violation(self, edge_exists: bool) -> bool:
        """Return *True* when the current state violates the rule."""
        if self == RuleType.REQUIRED_CALL:
            return not edge_exists
        return edge_exists  # FORBIDDEN_CALL


# ── B-007  SuggestedWorkflowRule ───────────────────────────────────────


@dataclass
class SuggestedWorkflowRule:
    """A single architecture policy rule."""

    id: str = ""
    type: str = "required_call"  # RuleType value
    source: Optional[str] = None
    target: Optional[str] = None
    source_layer: Optional[int] = None
    target_layer: Optional[int] = None
    source_arch_layer: Optional[str] = None
    target_arch_layer: Optional[str] = None
    reason: str = ""
    added_by: str = ""
    added_at: str = ""

    def __post_init__(self) -> None:
        if not self.added_at:
            self.added_at = iso_now()
        # B-007 step 4 — at least one source specifier required
        has_source = any([self.source, self.source_layer is not None, self.source_arch_layer])
        has_target = any([self.target, self.target_layer is not None, self.target_arch_layer])
        if not has_source:
            raise ValueError("Rule requires at least one of source/source_layer/source_arch_layer")
        if not has_target:
            raise ValueError("Rule requires at least one of target/target_layer/target_arch_layer")

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"id": self.id, "type": self.type, "reason": self.reason}
        if self.source is not None:
            d["source"] = self.source
        if self.target is not None:
            d["target"] = self.target
        if self.source_layer is not None:
            d["source_layer"] = self.source_layer
        if self.target_layer is not None:
            d["target_layer"] = self.target_layer
        if self.source_arch_layer is not None:
            d["source_arch_layer"] = self.source_arch_layer
        if self.target_arch_layer is not None:
            d["target_arch_layer"] = self.target_arch_layer
        d["added_by"] = self.added_by
        d["added_at"] = self.added_at
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> SuggestedWorkflowRule:
        return cls(
            id=d.get("id", ""),
            type=d.get("type", "required_call"),
            source=d.get("source"),
            target=d.get("target"),
            source_layer=d.get("source_layer"),
            target_layer=d.get("target_layer"),
            source_arch_layer=d.get("source_arch_layer"),
            target_arch_layer=d.get("target_arch_layer"),
            reason=d.get("reason", ""),
            added_by=d.get("added_by", ""),
            added_at=d.get("added_at", ""),
        )


# ── B-032  Glob pattern matcher / rule scope expansion ────────────────


def expand_rule_scope(
    scope: str,
    nodes: List[Graph0Node],
    graph1: Optional[Graph1] = None,
) -> List[str]:
    """Expand a rule scope pattern to concrete node IDs.

    *scope* can be:
      - An exact node ID
      - A module path (e.g. ``src/api``)
      - A glob pattern (e.g. ``src/api/*``)
    """
    # Exact match
    ids = {n.id for n in nodes}
    if scope in ids:
        return [scope]

    # Glob / fnmatch against node IDs
    matches = [nid for nid in ids if fnmatch.fnmatch(nid, scope)]
    if not matches:
        # Try matching against file paths
        matches = [n.id for n in nodes if fnmatch.fnmatch(n.file, scope)]
    if not matches:
        logger.warning("Rule scope '%s' matched zero nodes", scope)
    return sorted(matches)


def expand_layer_scope(
    layer: int,
    graph1: Graph1,
) -> List[str]:
    """Return IDs of all Graph_1 nodes at *layer*."""
    return [n.id for n in graph1.nodes if n.layer == layer]


def expand_arch_layer_scope(
    arch_layer: str,
    graph1: Graph1,
) -> List[str]:
    """Return IDs of all Graph_1 nodes with *arch_layer*."""
    return graph1.get_nodes_by_arch_layer(arch_layer)


# ── B-008  SuggestedWorkflow collection ───────────────────────────────


@dataclass
class SuggestedWorkflow:
    """All architecture policy rules."""

    version: int = 1
    rules: List[SuggestedWorkflowRule] = field(default_factory=list)

    _next_id: int = field(default=1, repr=False)
    _index: Dict[str, SuggestedWorkflowRule] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self._rebuild()

    def _rebuild(self) -> None:
        self._index = {r.id: r for r in self.rules if r.id}
        # Determine next auto-id
        max_num = 0
        for r in self.rules:
            if r.id.startswith("rule_"):
                try:
                    max_num = max(max_num, int(r.id[5:]))
                except ValueError:
                    pass
        self._next_id = max_num + 1

    def _auto_id(self) -> str:
        rid = f"rule_{self._next_id:03d}"
        self._next_id += 1
        return rid

    # ── CRUD ──────────────────────────────────────────────────────────

    def add_rule(self, rule: SuggestedWorkflowRule) -> str:
        """Add *rule*.  Assigns an auto-ID if empty and returns the id."""
        if not rule.id:
            rule.id = self._auto_id()
        if rule.id in self._index:
            raise ValueError(f"Duplicate rule id: {rule.id}")
        self.rules.append(rule)
        self._index[rule.id] = rule
        return rule.id

    def remove_rule(self, rule_id: str) -> None:
        if rule_id not in self._index:
            logger.warning("Rule '%s' not found for removal", rule_id)
            return
        self.rules = [r for r in self.rules if r.id != rule_id]
        del self._index[rule_id]

    def get_rule(self, rule_id: str) -> Optional[SuggestedWorkflowRule]:
        return self._index.get(rule_id)

    def list_rules(self) -> List[SuggestedWorkflowRule]:
        return list(self.rules)

    # ── Serialization ─────────────────────────────────────────────────

    def to_json(self, compact: bool = False) -> str:
        data = {
            "version": self.version,
            "rules": [r.to_dict() for r in self.rules],
        }
        return format_json(data, compact=compact)

    @classmethod
    def from_json(cls, text: str) -> SuggestedWorkflow:
        data = json.loads(text)
        rules = [SuggestedWorkflowRule.from_dict(rd) for rd in data.get("rules", [])]
        sw = cls(version=data.get("version", 1), rules=rules)
        sw._rebuild()
        return sw
