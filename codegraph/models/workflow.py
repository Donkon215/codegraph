"""codegraph.models.workflow — Workflow edge model and collection.

Tasks B-005, B-006, B-018, B-026, B-036, B-037.
"""

from __future__ import annotations

import enum
import json
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from codegraph.utils.formatting import format_json, iso_now


# ── B-018  Edge type enum ─────────────────────────────────────────────


class EdgeType(str, enum.Enum):
    """Edge relationship kind."""

    CALL = "call"
    TEST = "test"
    TRACE = "trace"
    DYNAMIC = "dynamic"


# ── B-018  Confidence enum with ordering ──────────────────────────────


class Confidence(str, enum.Enum):
    """Edge confidence level with built-in ordering.

    Precedence: runtime (4) > test (3) > static (2) > ai_inferred (1).
    """

    RUNTIME = "runtime"
    TEST = "test"
    STATIC = "static"
    AI_INFERRED = "ai_inferred"

    @property
    def rank(self) -> int:
        return _CONF_RANK[self]

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Confidence):
            return NotImplemented
        return self.rank < other.rank

    def __le__(self, other: object) -> bool:
        if not isinstance(other, Confidence):
            return NotImplemented
        return self.rank <= other.rank

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, Confidence):
            return NotImplemented
        return self.rank > other.rank

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, Confidence):
            return NotImplemented
        return self.rank >= other.rank

    @classmethod
    def from_string(cls, s: str) -> Confidence:
        try:
            return cls(s)
        except ValueError:
            raise ValueError(
                f"Invalid confidence '{s}'. "
                f"Valid: {[c.value for c in cls]}"
            ) from None


_CONF_RANK: Dict[Confidence, int] = {
    Confidence.AI_INFERRED: 1,
    Confidence.STATIC: 2,
    Confidence.TEST: 3,
    Confidence.RUNTIME: 4,
}


# ── B-036  Workflow level enum ─────────────────────────────────────────


class WorkflowLevel(str, enum.Enum):
    """Graph compression granularity."""

    FUNCTION = "function"
    CLASS = "class"
    MODULE = "module"


# ── B-005  WorkflowEdge ───────────────────────────────────────────────


@dataclass
class WorkflowEdge:
    """A single Workflow edge between two nodes."""

    source: str
    target: str
    edge_type: str = "call"
    confidence: str = "static"
    source_detail: str = ""  # F-028: which analysis pass / test file produced this
    conditional: bool = False  # F-033: inside if/try/loop

    def is_dynamic(self) -> bool:
        """True when target contains ``::*`` wildcard."""
        return "::*" in self.target

    def _key(self) -> Tuple[str, str, str, str]:
        return (self.source, self.target, self.edge_type, self.confidence)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, WorkflowEdge):
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self) -> int:
        return hash(self._key())

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "source": self.source,
            "target": self.target,
            "edge_type": self.edge_type,
            "confidence": self.confidence,
        }
        if self.source_detail:
            d["source_detail"] = self.source_detail
        if self.conditional:
            d["conditional"] = True
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> WorkflowEdge:
        return cls(
            source=d["source"],
            target=d["target"],
            edge_type=d.get("edge_type", "call"),
            confidence=d.get("confidence", "static"),
            source_detail=d.get("source_detail", ""),
            conditional=d.get("conditional", False),
        )


# ── B-026  Deduplication ──────────────────────────────────────────────


def deduplicate_edges(edges: List[WorkflowEdge]) -> List[WorkflowEdge]:
    """Remove exact duplicate edges while preserving first-occurrence order."""
    seen: Set[Tuple[str, str, str, str]] = set()
    result: List[WorkflowEdge] = []
    for e in edges:
        key = e._key()
        if key not in seen:
            seen.add(key)
            result.append(e)
    return result


# ── B-037  Edge confidence comparison ─────────────────────────────────

_EDGE_TYPE_RANK: Dict[str, int] = {
    EdgeType.TRACE.value: 4,
    EdgeType.CALL.value: 3,
    EdgeType.TEST.value: 2,
    EdgeType.DYNAMIC.value: 1,
}


def compare_edges(a: WorkflowEdge, b: WorkflowEdge) -> WorkflowEdge:
    """Return whichever edge has higher confidence.

    Ties are broken by edge-type rank: trace > call > test > dynamic.
    """
    ca = Confidence.from_string(a.confidence)
    cb = Confidence.from_string(b.confidence)
    if ca != cb:
        return a if ca > cb else b
    ra = _EDGE_TYPE_RANK.get(a.edge_type, 0)
    rb = _EDGE_TYPE_RANK.get(b.edge_type, 0)
    return a if ra >= rb else b


def best_edge_for(edges: List[WorkflowEdge]) -> WorkflowEdge:
    """Return the highest-confidence edge from the list."""
    if not edges:
        raise ValueError("Empty edge list")
    best = edges[0]
    for e in edges[1:]:
        best = compare_edges(best, e)
    return best


# ── B-006  Workflow collection ────────────────────────────────────────


@dataclass
class Workflow:
    """All Workflow edges with metadata and indexed lookups."""

    format_version: int = 1
    built_at: str = ""
    level: str = "function"
    edges: List[WorkflowEdge] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)  # F-035

    _source_map: Dict[str, List[WorkflowEdge]] = field(default_factory=lambda: defaultdict(list), repr=False)
    _target_map: Dict[str, List[WorkflowEdge]] = field(default_factory=lambda: defaultdict(list), repr=False)

    def __post_init__(self) -> None:
        if not self.built_at:
            self.built_at = iso_now()
        self._rebuild_indexes()

    def _rebuild_indexes(self) -> None:
        self._source_map = defaultdict(list)
        self._target_map = defaultdict(list)
        for e in self.edges:
            self._source_map[e.source].append(e)
            self._target_map[e.target].append(e)

    # ── Lookup ────────────────────────────────────────────────────────

    def get_edges_from(self, source_id: str) -> List[WorkflowEdge]:
        return list(self._source_map.get(source_id, []))

    def get_edges_to(self, target_id: str) -> List[WorkflowEdge]:
        return list(self._target_map.get(target_id, []))

    def get_dynamic_edges(self) -> List[WorkflowEdge]:
        return [e for e in self.edges if e.is_dynamic()]

    # ── Mutation ──────────────────────────────────────────────────────

    def add_edge(self, edge: WorkflowEdge) -> bool:
        """Add *edge* if not a duplicate.  Returns True if added."""
        key = edge._key()
        for existing in self._source_map.get(edge.source, []):
            if existing._key() == key:
                return False
        self.edges.append(edge)
        self._source_map[edge.source].append(edge)
        self._target_map[edge.target].append(edge)
        return True

    def remove_edge(self, source: str, target: str) -> None:
        """Remove all edges between *source* and *target*."""
        self.edges = [e for e in self.edges if not (e.source == source and e.target == target)]
        self._rebuild_indexes()

    # ── Serialization ─────────────────────────────────────────────────

    def to_json(self, compact: bool = False) -> str:
        data: Dict[str, Any] = {
            "format_version": self.format_version,
            "built_at": self.built_at,
            "level": self.level,
            "edges": [e.to_dict() for e in self.edges],
        }
        if self.metadata:
            data["metadata"] = self.metadata
        return format_json(data, compact=compact)

    @classmethod
    def from_json(cls, text: str) -> Workflow:
        data = json.loads(text)
        edges = [WorkflowEdge.from_dict(ed) for ed in data.get("edges", [])]
        w = cls(
            format_version=data.get("format_version", 1),
            built_at=data.get("built_at", ""),
            level=data.get("level", "function"),
            edges=edges,
            metadata=data.get("metadata", {}),
        )
        w._rebuild_indexes()
        return w
