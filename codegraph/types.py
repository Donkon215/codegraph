"""codegraph.types — Shared TypedDicts, Protocols, enums, and dataclass types.

Covers tasks A-017, A-035.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Sequence, runtime_checkable


# ═══════════════════════════════════════════════════════════════════════
# Enums  (A-017)
# ═══════════════════════════════════════════════════════════════════════


class NodeType(str, enum.Enum):
    """Type of a Graph_0 node."""

    FUNCTION = "function"
    CLASS = "class"
    METHOD = "method"
    MODULE = "module"


class EdgeType(str, enum.Enum):
    """Type of a Workflow edge."""

    CALL = "call"
    TEST = "test"
    TRACE = "trace"
    DYNAMIC = "dynamic"


class Confidence(str, enum.Enum):
    """Confidence source for a Workflow edge."""

    RUNTIME = "runtime"
    TEST = "test"
    STATIC = "static"
    AI_INFERRED = "ai_inferred"


class LayerNumber(int, enum.Enum):
    """Numeric layer designating node origin."""

    STDLIB = 0
    EXTERNAL = 1
    INTERNAL_LIB = 2
    PROJECT = 3
    TEST = 4


class RepairActionType(str, enum.Enum):
    """Types of automated repair actions."""

    CONNECT_CALL = "connect_call"
    ADD_IMPORT = "add_import"
    REMOVE_DEAD_CODE = "remove_dead_code"
    FLAG_FOR_HUMAN_REVIEW = "flag_for_human_review"


class TaskCategory(str, enum.Enum):
    """Categories of generated analysis tasks."""

    POLICY_VIOLATION = "policy_violation"
    MISSING_IMPORT = "missing_import"
    ORPHAN_NODES = "orphan_nodes"
    STALE_INTENT = "stale_intent"
    COVERAGE_GAP = "coverage_gap"
    INFO = "info"


# ═══════════════════════════════════════════════════════════════════════
# TypedDict-style dataclasses for graph nodes / edges  (A-017)
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class Graph0Node:
    """A single Graph_0 structural node."""

    id: str
    body_hash: str
    file: str
    type: str  # NodeType value
    line: int
    dependency_hash: Optional[str] = None  # CAS (Group Q)

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
    def from_dict(cls, d: Dict[str, Any]) -> "Graph0Node":
        return cls(
            id=d["id"],
            body_hash=d["body_hash"],
            file=d["file"],
            type=d["type"],
            line=d["line"],
            dependency_hash=d.get("dependency_hash"),
        )


@dataclass
class Graph1Node:
    """A single Graph_1 intent-metadata node."""

    id: str
    intent: str = ""
    layer: int = 3
    tags: List[str] = field(default_factory=list)
    arch_layer: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"id": self.id, "intent": self.intent, "layer": self.layer}
        if self.tags:
            d["tags"] = self.tags
        if self.arch_layer:
            d["arch_layer"] = self.arch_layer
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Graph1Node":
        return cls(
            id=d["id"],
            intent=d.get("intent", ""),
            layer=d.get("layer", 3),
            tags=d.get("tags", []),
            arch_layer=d.get("arch_layer", ""),
        )


@dataclass
class WorkflowEdge:
    """A single Workflow behaviour edge."""

    source: str
    target: str
    edge_type: str = "call"  # EdgeType value
    confidence: str = "static"  # Confidence value

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "edge_type": self.edge_type,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "WorkflowEdge":
        return cls(
            source=d["source"],
            target=d["target"],
            edge_type=d.get("edge_type", "call"),
            confidence=d.get("confidence", "static"),
        )


@dataclass
class TaskItem:
    """A single task in the agent work queue."""

    task_id: str
    category: str
    description: str
    target_node: str
    priority: int = 5
    context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "category": self.category,
            "description": self.description,
            "target_node": self.target_node,
            "priority": self.priority,
            "context": self.context,
        }


@dataclass
class PolicyViolation:
    """A policy violation detected by the analyzer."""

    rule_id: str
    node_id: str
    violation: str
    severity: str = "warning"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "node_id": self.node_id,
            "violation": self.violation,
            "severity": self.severity,
        }


@dataclass
class RepairAction:
    """A concrete code modification action."""

    action_type: str  # RepairActionType value
    target_node: str
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_type": self.action_type,
            "target_node": self.target_node,
            "details": self.details,
        }


@dataclass
class DeltaResult:
    """Summary of an incremental delta computation."""

    graph_version: int = 0
    changed_files: List[str] = field(default_factory=list)
    added_nodes: List[str] = field(default_factory=list)
    removed_nodes: List[str] = field(default_factory=list)
    modified_nodes: List[str] = field(default_factory=list)
    added_edges: int = 0
    removed_edges: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "graph_version": self.graph_version,
            "changed_files": self.changed_files,
            "added_nodes": self.added_nodes,
            "removed_nodes": self.removed_nodes,
            "modified_nodes": self.modified_nodes,
            "added_edges": self.added_edges,
            "removed_edges": self.removed_edges,
        }


@dataclass
class StatusReport:
    """Output of ``codegraph status``."""

    nodes: int = 0
    edges: int = 0
    nodes_missing_intent: int = 0
    orphan_nodes: int = 0
    workflow_edges: int = 0
    graph_version: int = 0
    cycle: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nodes": self.nodes,
            "edges": self.edges,
            "nodes_missing_intent": self.nodes_missing_intent,
            "orphan_nodes": self.orphan_nodes,
            "workflow_edges": self.workflow_edges,
            "graph_version": self.graph_version,
            "cycle": self.cycle,
        }


# ═══════════════════════════════════════════════════════════════════════
# Protocols  (A-017, A-027, A-035)
# ═══════════════════════════════════════════════════════════════════════


@runtime_checkable
class LanguageExtractor(Protocol):
    """Interface for language-specific AST extractors (A-027)."""

    def supported_extensions(self) -> List[str]:
        ...

    def extract_nodes(self, file_path: Path) -> List[Graph0Node]:
        ...

    def extract_edges(self, file_path: Path, nodes: List[Graph0Node]) -> List[WorkflowEdge]:
        ...


@runtime_checkable
class GraphStore(Protocol):
    """Abstract storage backend — JSON now, SQLite/DuckDB later (A-035)."""

    def load_graph0(self) -> Dict[str, Any]:
        ...

    def save_graph0(self, data: Dict[str, Any]) -> None:
        ...

    def load_graph1(self) -> Dict[str, Any]:
        ...

    def save_graph1(self, data: Dict[str, Any]) -> None:
        ...

    def load_workflow(self) -> Dict[str, Any]:
        ...

    def save_workflow(self, data: Dict[str, Any]) -> None:
        ...

    def load_suggested_workflow(self) -> Dict[str, Any]:
        ...

    def save_suggested_workflow(self, data: Dict[str, Any]) -> None:
        ...

    def load_delta(self) -> Dict[str, Any]:
        ...

    def save_delta(self, data: Dict[str, Any]) -> None:
        ...
