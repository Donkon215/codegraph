"""codegraph.models.graph0 — Graph_0 data model and collection.

Tasks B-001, B-002, B-017, B-024, B-041.
"""

from __future__ import annotations

import enum
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from codegraph.logging_config import get_logger
from codegraph.utils.formatting import format_json, iso_now

logger = get_logger("models.graph0")


# ── B-017  Node type enum ─────────────────────────────────────────────


class NodeType(str, enum.Enum):
    """Valid types for a Graph_0 node."""

    FUNCTION = "function"
    CLASS = "class"
    METHOD = "method"
    MODULE = "module"

    def is_callable(self) -> bool:
        """Return *True* for function-like nodes (function and method)."""
        return self in (NodeType.FUNCTION, NodeType.METHOD)


# ── B-001  Graph0Node ─────────────────────────────────────────────────


@dataclass
class Graph0Node:
    """A single Graph_0 structural node extracted from the AST.

    Equality and hashing are based on *id* only, so two nodes with the
    same identifier but different body hashes compare as equal.
    """

    id: str
    body_hash: str
    file: str
    type: str  # NodeType value
    line: int
    dependency_hash: Optional[str] = None  # B-041 / CAS

    def __post_init__(self) -> None:
        # Validate type field
        try:
            NodeType(self.type)
        except ValueError:
            raise ValueError(
                f"Invalid node type '{self.type}'. "
                f"Valid types: {[t.value for t in NodeType]}"
            )

    # Equality / hash by id only (B-001 step 5/6)
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Graph0Node):
            return NotImplemented
        return self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "id": self.id,
            "body_hash": self.body_hash,
            "file": self.file,
            "type": self.type,
            "line": self.line,
        }
        if self.dependency_hash is not None:
            d["dependency_hash"] = self.dependency_hash
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Graph0Node:
        return cls(
            id=d["id"],
            body_hash=d["body_hash"],
            file=d["file"],
            type=d["type"],
            line=d["line"],
            dependency_hash=d.get("dependency_hash"),
        )


# ── B-024  Collision resolver ─────────────────────────────────────────


class CollisionResolver:
    """Detect and resolve node ID collisions using ``[N]`` disambiguators."""

    def __init__(self) -> None:
        self._seen: Dict[str, int] = {}
        self.collisions: List[tuple[str, str]] = []  # (original, resolved)

    def resolve(self, node_id: str) -> str:
        """Return a unique ID, appending ``[N]`` when *node_id* was seen before."""
        count = self._seen.get(node_id, 0) + 1
        self._seen[node_id] = count
        if count == 1:
            return node_id
        resolved = f"{node_id}[{count}]"
        self.collisions.append((node_id, resolved))
        logger.warning("Node ID collision: %s → %s", node_id, resolved)
        return resolved


# ── B-002  Graph0 collection ──────────────────────────────────────────


@dataclass
class Graph0:
    """The complete Graph_0: all structural nodes plus metadata."""

    graph_version: int = 1
    format_version: int = 1
    extracted_at: str = ""
    source_files: List[str] = field(default_factory=list)
    nodes: List[Graph0Node] = field(default_factory=list)

    # Internal index for O(1) lookup – rebuilt on load.
    _index: Dict[str, Graph0Node] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if not self.extracted_at:
            self.extracted_at = iso_now()
        self._rebuild_index()

    def _rebuild_index(self) -> None:
        self._index = {n.id: n for n in self.nodes}

    # ── Lookup ────────────────────────────────────────────────────────

    def get_node(self, node_id: str) -> Optional[Graph0Node]:
        """O(1) node lookup by *node_id*."""
        return self._index.get(node_id)

    def get_nodes_by_file(self, file_path: str) -> List[Graph0Node]:
        """Return all nodes belonging to *file_path*."""
        return [n for n in self.nodes if n.file == file_path]

    def has_node(self, node_id: str) -> bool:
        return node_id in self._index

    # ── Mutation ──────────────────────────────────────────────────────

    def add_node(self, node: Graph0Node) -> None:
        """Add *node*, raising on duplicate id."""
        if node.id in self._index:
            raise ValueError(f"Duplicate node id: {node.id}")
        self.nodes.append(node)
        self._index[node.id] = node

    def remove_node(self, node_id: str) -> None:
        """Remove node by *node_id*.  No-op if absent."""
        if node_id in self._index:
            self.nodes = [n for n in self.nodes if n.id != node_id]
            del self._index[node_id]

    # B-041 — CAS bulk update
    def update_dependency_hashes(self, hashes: Dict[str, str]) -> None:
        """Set *dependency_hash* on every node listed in *hashes*."""
        for node_id, dep_hash in hashes.items():
            node = self._index.get(node_id)
            if node is not None:
                node.dependency_hash = dep_hash

    # ── Serialization ─────────────────────────────────────────────────

    def to_json(self, compact: bool = False) -> str:
        data = {
            "format_version": self.format_version,
            "graph_version": self.graph_version,
            "extracted_at": self.extracted_at,
            "source_files": self.source_files,
            "nodes": [n.to_dict() for n in self.nodes],
        }
        return format_json(data, compact=compact)

    @classmethod
    def from_json(cls, text: str) -> Graph0:
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("Expected a JSON object for Graph0")
        nodes = [Graph0Node.from_dict(nd) for nd in data.get("nodes", [])]
        g = cls(
            graph_version=data.get("graph_version", 1),
            format_version=data.get("format_version", 1),
            extracted_at=data.get("extracted_at", ""),
            source_files=data.get("source_files", []),
            nodes=nodes,
        )
        g._rebuild_index()
        return g
