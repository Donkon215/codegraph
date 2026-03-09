"""codegraph.models.graph1 — Graph_1 intent-metadata overlay model.

Tasks B-003, B-004, B-016, B-039, B-040.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from codegraph.logging_config import get_logger
from codegraph.utils.formatting import format_json, iso_now

logger = get_logger("models.graph1")


# ── B-039  Arch-layer constants ────────────────────────────────────────

STANDARD_ARCH_LAYERS = frozenset({
    "controller",
    "service",
    "domain",
    "repository",
    "infra",
})


def validate_arch_layer_name(name: str) -> bool:
    """Return *True* if *name* is a recognised architectural layer.

    Non-standard names do not raise but produce a warning.
    """
    if not name:
        return True  # empty is valid (not set)
    if name in STANDARD_ARCH_LAYERS:
        return True
    logger.warning("Non-standard arch_layer: '%s'", name)
    return False


# ── B-016  Intent quality validator ───────────────────────────────────

_BAD_PATTERNS = re.compile(
    r"\b(helper|utility|misc|stuff|data processing|wrapper|handle|do)\b",
    re.IGNORECASE,
)

_MIN_INTENT_LENGTH = 10
_MIN_WORD_COUNT = 3


def validate_intent(intent: str) -> Tuple[bool, List[str]]:
    """Check *intent* against quality heuristics.

    Returns ``(ok, warnings)`` where *ok* is ``False`` only when the
    intent is empty.  Non-empty intents that are low-quality produce
    warnings but still return ``ok=True``.
    """
    warnings: List[str] = []

    if not intent or not intent.strip():
        return False, ["Intent is empty"]

    stripped = intent.strip()

    if len(stripped) < _MIN_INTENT_LENGTH:
        warnings.append(f"Intent is very short ({len(stripped)} chars); consider expanding")

    words = stripped.split()
    if len(words) < _MIN_WORD_COUNT:
        warnings.append(f"Intent has only {len(words)} word(s); prefer verb + object + purpose")

    if _BAD_PATTERNS.search(stripped):
        warnings.append(f"Intent matches low-quality pattern: '{stripped}'")

    return True, warnings


# ── B-003  Graph1Node ─────────────────────────────────────────────────


@dataclass
class Graph1Node:
    """A single Graph_1 metadata overlay node.

    References a Graph_0 node by *id* and carries semantic annotations.
    """

    id: str
    intent: str = ""
    layer: int = 3
    arch_layer: Optional[str] = None
    intent_author: str = ""
    intent_version: int = 1
    intent_timestamp: str = ""
    tags: List[str] = field(default_factory=list)
    intent_body_hash: str = ""  # E-006: body_hash at time of intent
    intent_history: List[Dict[str, Any]] = field(default_factory=list)  # E-025

    def __post_init__(self) -> None:
        if not self.intent_timestamp:
            self.intent_timestamp = iso_now()

    # B-003 step 4
    def update_intent(self, new_intent: str, author: str) -> None:
        """Replace the intent, incrementing *intent_version*."""
        self.intent = new_intent
        self.intent_author = author
        self.intent_version += 1
        self.intent_timestamp = iso_now()

    # Equality by id
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Graph1Node):
            return NotImplemented
        return self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "id": self.id,
            "intent": self.intent,
            "layer": self.layer,
            "intent_author": self.intent_author,
            "intent_version": self.intent_version,
            "intent_timestamp": self.intent_timestamp,
        }
        if self.arch_layer:
            d["arch_layer"] = self.arch_layer
        if self.tags:
            d["tags"] = self.tags
        if self.intent_body_hash:
            d["intent_body_hash"] = self.intent_body_hash
        if self.intent_history:
            d["intent_history"] = self.intent_history
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Graph1Node:
        return cls(
            id=d["id"],
            intent=d.get("intent", ""),
            layer=d.get("layer", 3),
            arch_layer=d.get("arch_layer"),
            intent_author=d.get("intent_author", ""),
            intent_version=d.get("intent_version", 1),
            intent_timestamp=d.get("intent_timestamp", ""),
            tags=d.get("tags", []),
            intent_body_hash=d.get("intent_body_hash", ""),
            intent_history=d.get("intent_history", []),
        )


# ── B-004  Graph1 collection ──────────────────────────────────────────


@dataclass
class Graph1:
    """All Graph_1 metadata overlay nodes."""

    format_version: int = 1
    nodes: List[Graph1Node] = field(default_factory=list)

    _index: Dict[str, Graph1Node] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self._rebuild_index()

    def _rebuild_index(self) -> None:
        self._index = {n.id: n for n in self.nodes}

    # ── Lookup ────────────────────────────────────────────────────────

    def get_node(self, node_id: str) -> Optional[Graph1Node]:
        return self._index.get(node_id)

    def has_node(self, node_id: str) -> bool:
        return node_id in self._index

    # B-004 step 6
    def get_nodes_missing_intent(self) -> List[str]:
        """Return IDs of nodes whose intent is empty or None."""
        return [n.id for n in self.nodes if not n.intent or not n.intent.strip()]

    # B-004 step 7 — needs Graph0 import deferred
    def get_stale_nodes(self, graph0_ids: frozenset[str]) -> List[str]:
        """Return IDs present in Graph_1 but absent from *graph0_ids*."""
        return [n.id for n in self.nodes if n.id not in graph0_ids]

    # B-039  arch-layer helpers
    def get_nodes_by_arch_layer(self, arch_layer: str) -> List[str]:
        return [n.id for n in self.nodes if n.arch_layer == arch_layer]

    def set_arch_layer(self, node_id: str, arch_layer: str) -> None:
        validate_arch_layer_name(arch_layer)
        n = self._index.get(node_id)
        if n is not None:
            n.arch_layer = arch_layer

    # ── Mutation ──────────────────────────────────────────────────────

    # B-004 step 4
    def upsert_node(self, node: Graph1Node) -> None:
        """Insert a new node or merge into existing."""
        existing = self._index.get(node.id)
        if existing is not None:
            existing.update_intent(node.intent, node.intent_author)
            existing.layer = node.layer
            existing.tags = node.tags
            if node.arch_layer:
                existing.arch_layer = node.arch_layer
        else:
            self.nodes.append(node)
            self._index[node.id] = node

    def remove_node(self, node_id: str) -> None:
        if node_id in self._index:
            self.nodes = [n for n in self.nodes if n.id != node_id]
            del self._index[node_id]

    # ── Serialization ─────────────────────────────────────────────────

    def to_json(self, compact: bool = False) -> str:
        data = {
            "format_version": self.format_version,
            "nodes": [n.to_dict() for n in self.nodes],
        }
        return format_json(data, compact=compact)

    @classmethod
    def from_json(cls, text: str) -> Graph1:
        data = json.loads(text)
        nodes = [Graph1Node.from_dict(nd) for nd in data.get("nodes", [])]
        g = cls(format_version=data.get("format_version", 1), nodes=nodes)
        g._rebuild_index()
        return g
