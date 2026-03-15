"""codegraph.architecture_graph — Canonical architecture model.

Single source of truth for architecture state.
All persisted views (Graph_0, Graph_1, workflow, semantic graph) are
projections derived from canonical fields on this model.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from codegraph.constants import GRAPHS_DIR
from codegraph.models.graph0 import Graph0, Graph0Node
from codegraph.models.graph1 import Graph1, Graph1Node
from codegraph.models.workflow import Workflow, WorkflowEdge
from codegraph.storage import resolve_path


@dataclass
class ArchitectureGraph:
    """Canonical architecture state.

    Canonical fields:
      - `nodes`: unified per-node records
      - `edges`: unified workflow/context edges
      - `node_types`: node_id -> type
      - `edge_types`: edge_key -> edge_type
      - `metadata`: graph-level metadata

    Compatibility views (`structure_graph`, `intent_graph`, `workflow_graph`)
    are computed projections from canonical fields.
    """

    nodes: List[Dict[str, Any]] = field(default_factory=list)
    edges: List[Dict[str, Any]] = field(default_factory=list)
    node_types: Dict[str, str] = field(default_factory=dict)
    edge_types: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    semantic_graph: Dict[str, Any] = field(default_factory=dict)
    _structure_graph_cache: Optional[Graph0] = field(default=None, init=False, repr=False)
    _intent_graph_cache: Optional[Graph1] = field(default=None, init=False, repr=False)
    _workflow_graph_cache: Optional[Workflow] = field(default=None, init=False, repr=False)

    @property
    def structure_graph(self) -> Graph0:
        if self._structure_graph_cache is None:
            self._structure_graph_cache = self._to_graph0()
        return self._structure_graph_cache

    @property
    def intent_graph(self) -> Graph1:
        if self._intent_graph_cache is None:
            self._intent_graph_cache = self._to_graph1()
        return self._intent_graph_cache

    @property
    def workflow_graph(self) -> Workflow:
        if self._workflow_graph_cache is None:
            self._workflow_graph_cache = self._to_workflow()
        return self._workflow_graph_cache

    @classmethod
    def from_views(
        cls,
        *,
        structure_graph: Optional[Graph0] = None,
        intent_graph: Optional[Graph1] = None,
        semantic_graph: Optional[Dict[str, Any]] = None,
        workflow_graph: Optional[Workflow] = None,
    ) -> "ArchitectureGraph":
        g0 = structure_graph or Graph0()
        g1 = intent_graph or Graph1()
        wf = workflow_graph or Workflow()

        g1_map = {n.id: n for n in g1.nodes}
        canonical_nodes: List[Dict[str, Any]] = []
        node_types: Dict[str, str] = {}

        for node in g0.nodes:
            overlay = g1_map.get(node.id)
            record: Dict[str, Any] = {
                "id": node.id,
                "file": node.file,
                "line": node.line,
                "body_hash": node.body_hash,
                "type": node.type,
            }
            if node.dependency_hash is not None:
                record["dependency_hash"] = node.dependency_hash
            if overlay is not None:
                record.update({
                    "intent": overlay.intent,
                    "layer": overlay.layer,
                    "arch_layer": overlay.arch_layer,
                    "intent_author": overlay.intent_author,
                    "intent_version": overlay.intent_version,
                    "intent_timestamp": overlay.intent_timestamp,
                    "tags": list(overlay.tags),
                    "intent_body_hash": overlay.intent_body_hash,
                    "intent_history": list(overlay.intent_history),
                })
            canonical_nodes.append(record)
            node_types[node.id] = node.type

        for overlay in g1.nodes:
            if overlay.id in node_types:
                continue
            canonical_nodes.append({
                "id": overlay.id,
                "file": overlay.id.split("::", 1)[0],
                "line": 1,
                "body_hash": "",
                "type": "function",
                "intent": overlay.intent,
                "layer": overlay.layer,
                "arch_layer": overlay.arch_layer,
                "intent_author": overlay.intent_author,
                "intent_version": overlay.intent_version,
                "intent_timestamp": overlay.intent_timestamp,
                "tags": list(overlay.tags),
                "intent_body_hash": overlay.intent_body_hash,
                "intent_history": list(overlay.intent_history),
            })
            node_types[overlay.id] = "function"

        canonical_edges: List[Dict[str, Any]] = []
        edge_types: Dict[str, str] = {}
        for index, edge in enumerate(wf.edges):
            edge_record = {
                "source": edge.source,
                "target": edge.target,
                "edge_type": edge.edge_type,
                "confidence": edge.confidence,
                "source_detail": edge.source_detail,
                "conditional": edge.conditional,
            }
            canonical_edges.append(edge_record)
            edge_key = f"{edge.source}->{edge.target}#{index}"
            edge_types[edge_key] = edge.edge_type

        metadata: Dict[str, Any] = {
            "graph_version": g0.graph_version,
            "graph0_format_version": g0.format_version,
            "graph1_format_version": g1.format_version,
            "workflow_format_version": wf.format_version,
            "workflow_level": wf.level,
            "source_files": list(g0.source_files),
            "extracted_at": g0.extracted_at,
            "workflow_built_at": wf.built_at,
            "workflow_metadata": dict(wf.metadata or {}),
        }

        return cls(
            nodes=canonical_nodes,
            edges=canonical_edges,
            node_types=node_types,
            edge_types=edge_types,
            metadata=metadata,
            semantic_graph=semantic_graph or {},
        )

    @classmethod
    def load(cls, project_root: Path) -> "ArchitectureGraph":
        from codegraph.annotator import load_graph1
        from codegraph.extractor import load_graph0
        from codegraph.workflow import load_workflow

        graph0 = load_graph0(project_root)
        graph1 = load_graph1(project_root)
        workflow = load_workflow(project_root)

        graph2_path = resolve_path(project_root, GRAPHS_DIR, "graph2.json")
        semantics: Dict[str, Any] = {}
        if graph2_path.exists():
            try:
                semantics = json.loads(graph2_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                semantics = {}

        return cls.from_views(
            structure_graph=graph0,
            intent_graph=graph1,
            semantic_graph=semantics,
            workflow_graph=workflow,
        )

    def to_views(self) -> Dict[str, Any]:
        self._sync_from_view_caches()
        return {
            "graph0": self.structure_graph,
            "graph1": self.intent_graph,
            "graph2": self.semantic_graph,
            "workflow": self.workflow_graph,
        }

    def save_derived_views(self, project_root: Path) -> None:
        from codegraph.annotator import save_graph1
        from codegraph.extractor import save_graph0
        from codegraph.storage import atomic_write
        from codegraph.workflow import write_workflow

        self._sync_from_view_caches()

        graph0 = self.structure_graph
        graph1 = self.intent_graph
        workflow = self.workflow_graph

        save_graph0(graph0, project_root)
        save_graph1(graph1, project_root)
        write_workflow(workflow, project_root)

        graph2_path = resolve_path(project_root, GRAPHS_DIR, "graph2.json")
        atomic_write(graph2_path, self.semantic_graph or {})

    def _sync_from_view_caches(self) -> None:
        if self._structure_graph_cache is None and self._intent_graph_cache is None and self._workflow_graph_cache is None:
            return

        synchronized = ArchitectureGraph.from_views(
            structure_graph=self._structure_graph_cache or self._to_graph0(),
            intent_graph=self._intent_graph_cache or self._to_graph1(),
            semantic_graph=self.semantic_graph,
            workflow_graph=self._workflow_graph_cache or self._to_workflow(),
        )

        self.nodes = synchronized.nodes
        self.edges = synchronized.edges
        self.node_types = synchronized.node_types
        self.edge_types = synchronized.edge_types
        self.metadata = synchronized.metadata

        self._structure_graph_cache = synchronized._to_graph0()
        self._intent_graph_cache = synchronized._to_graph1()
        self._workflow_graph_cache = synchronized._to_workflow()

    def _to_graph0(self) -> Graph0:
        graph0_nodes: List[Graph0Node] = []
        seen: set[str] = set()

        for node in self.nodes:
            node_id = str(node.get("id", "")).strip()
            if not node_id or node_id in seen:
                continue
            seen.add(node_id)

            node_type = str(node.get("type") or self.node_types.get(node_id) or "function")
            file_path = str(node.get("file") or node_id.split("::", 1)[0])
            line = int(node.get("line") or 1)
            body_hash = str(node.get("body_hash") or "")

            graph0_nodes.append(
                Graph0Node(
                    id=node_id,
                    body_hash=body_hash,
                    file=file_path,
                    type=node_type,
                    line=line,
                    dependency_hash=node.get("dependency_hash"),
                )
            )

        return Graph0(
            graph_version=int(self.metadata.get("graph_version", 1)),
            format_version=int(self.metadata.get("graph0_format_version", 1)),
            extracted_at=str(self.metadata.get("extracted_at", "")),
            source_files=list(self.metadata.get("source_files", [])),
            nodes=graph0_nodes,
        )

    def _to_graph1(self) -> Graph1:
        graph1_nodes: List[Graph1Node] = []
        for node in self.nodes:
            node_id = str(node.get("id", "")).strip()
            if not node_id:
                continue
            graph1_nodes.append(
                Graph1Node(
                    id=node_id,
                    intent=str(node.get("intent", "")),
                    layer=int(node.get("layer", 3)),
                    arch_layer=node.get("arch_layer"),
                    intent_author=str(node.get("intent_author", "")),
                    intent_version=int(node.get("intent_version", 1)),
                    intent_timestamp=str(node.get("intent_timestamp", "")),
                    tags=list(node.get("tags") or []),
                    intent_body_hash=str(node.get("intent_body_hash", "")),
                    intent_history=list(node.get("intent_history") or []),
                )
            )
        return Graph1(
            format_version=int(self.metadata.get("graph1_format_version", 1)),
            nodes=graph1_nodes,
        )

    def _to_workflow(self) -> Workflow:
        workflow_edges: List[WorkflowEdge] = []
        for edge in self.edges:
            source = str(edge.get("source", "")).strip()
            target = str(edge.get("target", "")).strip()
            if not source or not target:
                continue
            workflow_edges.append(
                WorkflowEdge(
                    source=source,
                    target=target,
                    edge_type=str(edge.get("edge_type", "call")),
                    confidence=str(edge.get("confidence", "static")),
                    source_detail=str(edge.get("source_detail", "")),
                    conditional=bool(edge.get("conditional", False)),
                )
            )

        return Workflow(
            format_version=int(self.metadata.get("workflow_format_version", 1)),
            built_at=str(self.metadata.get("workflow_built_at", "")),
            level=str(self.metadata.get("workflow_level", "function")),
            edges=workflow_edges,
            metadata=dict(self.metadata.get("workflow_metadata") or {}),
        )
