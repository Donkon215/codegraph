"""codegraph.models.graph2 — Graph_2 semantic behavior layer.

Tasks B-044, B-045 — data models.
Tasks R-001 through R-007 — expanded semantic models, enums, query methods.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from codegraph.utils.formatting import format_json, iso_now


# ═══════════════════════════════════════════════════════════════════════
# R-001 — Action Type Enum
# ═══════════════════════════════════════════════════════════════════════


class ActionType(str, Enum):
    """Semantic action verbs for function behavior classification."""

    READ = "read"
    WRITE = "write"
    CREATE = "create"
    DELETE = "delete"
    UPDATE = "update"
    VALIDATE = "validate"
    TRANSFORM = "transform"
    SEND = "send"
    RECEIVE = "receive"
    QUERY = "query"
    COMPUTE = "compute"
    AUTHORIZE = "authorize"
    LOG = "log"
    CONFIGURE = "configure"
    DISPATCH = "dispatch"
    SUBSCRIBE = "subscribe"
    CACHE = "cache"
    RETRY = "retry"
    PARSE = "parse"
    FORMAT = "format"
    UNKNOWN = "unknown"


# ═══════════════════════════════════════════════════════════════════════
# R-002 — Side Effect Type Enum
# ═══════════════════════════════════════════════════════════════════════


class SideEffectType(str, Enum):
    """Categories of observable side effects."""

    DATABASE_READ = "database_read"
    DATABASE_WRITE = "database_write"
    NETWORK_CALL = "network_call"
    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    PROCESS_SPAWN = "process_spawn"
    ENVIRONMENT_READ = "environment_read"
    ENVIRONMENT_WRITE = "environment_write"
    LOGGING = "logging"
    METRICS = "metrics"
    CACHE_READ = "cache_read"
    CACHE_WRITE = "cache_write"
    MESSAGE_PUBLISH = "message_publish"
    MESSAGE_CONSUME = "message_consume"
    SYSTEM_CALL = "system_call"
    NONE = "none"


@dataclass
class SemanticAction:
    """A single action performed by a node (verb + object)."""

    verb: str = ""
    object: str = ""
    description: str = ""
    action_type: ActionType = ActionType.UNKNOWN
    confidence: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verb": self.verb,
            "object": self.object,
            "description": self.description,
            "action_type": self.action_type.value,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> SemanticAction:
        at = ActionType.UNKNOWN
        raw = d.get("action_type", "")
        if raw:
            try:
                at = ActionType(raw)
            except ValueError:
                at = ActionType.UNKNOWN
        return cls(
            verb=d.get("verb", ""),
            object=d.get("object", ""),
            description=d.get("description", ""),
            action_type=at,
            confidence=d.get("confidence", 0.0),
        )


# ═══════════════════════════════════════════════════════════════════════
# R-003 — Guard Dataclass
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class Guard:
    """A precondition / guard clause for a node."""

    condition: str = ""
    description: str = ""
    raises: str = ""  # Exception type if guard fails
    early_return: bool = False  # True if guard causes early return instead of raise

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "condition": self.condition,
            "description": self.description,
        }
        if self.raises:
            d["raises"] = self.raises
        if self.early_return:
            d["early_return"] = True
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Guard:
        if isinstance(d, dict):
            return cls(
                condition=d.get("condition", ""),
                description=d.get("description", ""),
                raises=d.get("raises", ""),
                early_return=d.get("early_return", False),
            )
        return cls()


@dataclass
class SideEffect:
    """A side effect produced by a node."""

    type: str = ""  # e.g. DATABASE_WRITE, NETWORK_CALL, FILE_IO
    target: str = ""
    description: str = ""
    effect_type: SideEffectType = SideEffectType.NONE
    reversible: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "target": self.target,
            "description": self.description,
            "effect_type": self.effect_type.value,
            "reversible": self.reversible,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> SideEffect:
        et = SideEffectType.NONE
        raw = d.get("effect_type", "")
        if raw:
            try:
                et = SideEffectType(raw)
            except ValueError:
                et = SideEffectType.NONE
        return cls(
            type=d.get("type", ""),
            target=d.get("target", ""),
            description=d.get("description", ""),
            effect_type=et,
            reversible=d.get("reversible", False),
        )


# ═══════════════════════════════════════════════════════════════════════
# R-004 — DataFlow Items
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class DataFlowItem:
    """A single data-flow input, output, or transform with type info."""

    name: str = ""
    type_annotation: str = ""
    source: str = ""  # Where the data comes from / goes to

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"name": self.name}
        if self.type_annotation:
            d["type"] = self.type_annotation
        if self.source:
            d["source"] = self.source
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> DataFlowItem:
        if isinstance(d, str):
            return cls(name=d)
        return cls(
            name=d.get("name", ""),
            type_annotation=d.get("type", ""),
            source=d.get("source", ""),
        )


@dataclass
class DataFlowSummary:
    """Summarised data-flow through a node."""

    inputs: List[str] = field(default_factory=list)
    outputs: List[str] = field(default_factory=list)
    transforms: List[str] = field(default_factory=list)
    input_items: List[DataFlowItem] = field(default_factory=list)
    output_items: List[DataFlowItem] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "inputs": self.inputs,
            "outputs": self.outputs,
            "transforms": self.transforms,
        }
        if self.input_items:
            d["input_items"] = [i.to_dict() for i in self.input_items]
        if self.output_items:
            d["output_items"] = [o.to_dict() for o in self.output_items]
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> DataFlowSummary:
        return cls(
            inputs=d.get("inputs", []),
            outputs=d.get("outputs", []),
            transforms=d.get("transforms", []),
            input_items=[DataFlowItem.from_dict(i) for i in d.get("input_items", [])],
            output_items=[DataFlowItem.from_dict(o) for o in d.get("output_items", [])],
        )


@dataclass
class Graph2Node:
    """A single Graph_2 semantic behavior node."""

    id: str
    actions: List[SemanticAction] = field(default_factory=list)
    guards: List[Guard] = field(default_factory=list)
    side_effects: List[SideEffect] = field(default_factory=list)
    data_flow: Optional[DataFlowSummary] = None
    domain_tags: List[str] = field(default_factory=list)
    behavior_hash: Optional[str] = None
    confidence: float = 0.0
    generated_at: str = ""
    # R-005 — Library associations
    library_calls: List[str] = field(default_factory=list)
    # R-006 — SQL classification
    sql_operations: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.generated_at:
            self.generated_at = iso_now()

    def compute_behavior_hash(self) -> str:
        """R-020 — Compute hash of semantic behavior for change detection."""
        parts: List[str] = []
        for a in sorted(self.actions, key=lambda x: (x.verb, x.object)):
            parts.append(f"A:{a.verb}:{a.object}")
        for g in sorted(self.guards, key=lambda x: x.condition):
            parts.append(f"G:{g.condition}")
        for se in sorted(self.side_effects, key=lambda x: (x.type, x.target)):
            parts.append(f"SE:{se.type}:{se.target}")
        if self.data_flow:
            parts.append(f"DF:{'|'.join(sorted(self.data_flow.inputs))}")
            parts.append(f"DF:{'|'.join(sorted(self.data_flow.outputs))}")
        for tag in sorted(self.domain_tags):
            parts.append(f"DT:{tag}")
        payload = ":".join(parts) if parts else self.id
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "id": self.id,
            "actions": [a.to_dict() for a in self.actions],
            "guards": [g.to_dict() for g in self.guards],
            "side_effects": [se.to_dict() for se in self.side_effects],
            "domain_tags": self.domain_tags,
            "confidence": self.confidence,
            "generated_at": self.generated_at,
        }
        if self.data_flow is not None:
            d["data_flow"] = self.data_flow.to_dict()
        if self.behavior_hash is not None:
            d["behavior_hash"] = self.behavior_hash
        if self.library_calls:
            d["library_calls"] = self.library_calls
        if self.sql_operations:
            d["sql_operations"] = self.sql_operations
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Graph2Node:
        df = None
        if "data_flow" in d:
            df = DataFlowSummary.from_dict(d["data_flow"])
        return cls(
            id=d["id"],
            actions=[SemanticAction.from_dict(a) for a in d.get("actions", [])],
            guards=[Guard.from_dict(g) for g in d.get("guards", [])],
            side_effects=[SideEffect.from_dict(se) for se in d.get("side_effects", [])],
            data_flow=df,
            domain_tags=d.get("domain_tags", []),
            behavior_hash=d.get("behavior_hash"),
            confidence=d.get("confidence", 0.0),
            generated_at=d.get("generated_at", ""),
            library_calls=d.get("library_calls", []),
            sql_operations=d.get("sql_operations", []),
        )


# ═══════════════════════════════════════════════════════════════════════
# R-007 — Graph2 Collection with Query Methods
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class Graph2:
    """All Graph_2 semantic behavior nodes."""

    format_version: int = 1
    generated_at: str = ""
    nodes: List[Graph2Node] = field(default_factory=list)

    _index: Dict[str, Graph2Node] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if not self.generated_at:
            self.generated_at = iso_now()
        self._rebuild_index()

    def _rebuild_index(self) -> None:
        self._index = {n.id: n for n in self.nodes}

    def get_node(self, node_id: str) -> Optional[Graph2Node]:
        return self._index.get(node_id)

    def upsert_node(self, node: Graph2Node) -> None:
        existing = self._index.get(node.id)
        if existing is not None:
            self.nodes = [n for n in self.nodes if n.id != node.id]
        self.nodes.append(node)
        self._index[node.id] = node

    def remove_node(self, node_id: str) -> None:
        """Remove a node by ID."""
        if node_id in self._index:
            del self._index[node_id]
            self.nodes = [n for n in self.nodes if n.id != node_id]

    # --- R-007 query methods ---

    def nodes_with_side_effect(self, effect_type: SideEffectType) -> List[Graph2Node]:
        """Find all nodes that produce a given side effect type."""
        return [
            n for n in self.nodes
            if any(se.effect_type == effect_type for se in n.side_effects)
        ]

    def nodes_with_action_type(self, action_type: ActionType) -> List[Graph2Node]:
        """Find all nodes performing a given action type."""
        return [
            n for n in self.nodes
            if any(a.action_type == action_type for a in n.actions)
        ]

    def nodes_with_domain_tag(self, tag: str) -> List[Graph2Node]:
        """Find all nodes tagged with a specific domain."""
        return [n for n in self.nodes if tag in n.domain_tags]

    def nodes_with_sql(self) -> List[Graph2Node]:
        """Find all nodes that perform SQL operations."""
        return [n for n in self.nodes if n.sql_operations]

    def nodes_with_library(self, library: str) -> List[Graph2Node]:
        """Find all nodes that call a specific library."""
        return [n for n in self.nodes if library in n.library_calls]

    def get_behavior_summary(self) -> Dict[str, Any]:
        """Build summary statistics of semantic behaviors."""
        action_counts: Dict[str, int] = {}
        effect_counts: Dict[str, int] = {}
        domain_counts: Dict[str, int] = {}

        for node in self.nodes:
            for a in node.actions:
                action_counts[a.action_type.value] = action_counts.get(a.action_type.value, 0) + 1
            for se in node.side_effects:
                effect_counts[se.effect_type.value] = effect_counts.get(se.effect_type.value, 0) + 1
            for tag in node.domain_tags:
                domain_counts[tag] = domain_counts.get(tag, 0) + 1

        return {
            "total_nodes": len(self.nodes),
            "action_types": action_counts,
            "side_effect_types": effect_counts,
            "domain_tags": domain_counts,
        }

    def to_json(self, compact: bool = False) -> str:
        data = {
            "format_version": self.format_version,
            "generated_at": self.generated_at,
            "nodes": [n.to_dict() for n in self.nodes],
        }
        return format_json(data, compact=compact)

    @classmethod
    def from_json(cls, text: str) -> Graph2:
        data = json.loads(text)
        nodes = [Graph2Node.from_dict(nd) for nd in data.get("nodes", [])]
        g = cls(
            format_version=data.get("format_version", 1),
            generated_at=data.get("generated_at", ""),
            nodes=nodes,
        )
        g._rebuild_index()
        return g
