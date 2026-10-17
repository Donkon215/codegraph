"""codegraph.architecture_overview — Explainable structural architecture overview.

Computes a deterministic, evidence-based overview of an ArchitectureGraph:

* detected communities (structural clusters from graph topology, via
  :func:`codegraph.graph_partitioning.build_partitions`), summarized per
  community; and
* cross-community dependency/coupling evidence (edges that cross the
  community cut), with per-link edge counts, boundary nodes and a heuristic
  coupling score.

Detected structure (graph topology) is reported separately from declared
policy/intent (``system.json`` subsystems/constraints, node ``subsystem``
tags, graph1 intents and layers). Every metric is heuristic evidence only:
there are no thresholds, no pass/fail fields, and nothing here is a hard
reject. Callers must not treat a coupling score or community shape as a
governance decision.

This module is the implementation side of the written metric definitions in
``docs/architecture-metrics.md`` (detected communities, cross-community links
and aggregate structural metrics). It can also persist a stable community
artifact via :func:`save_overview` / :func:`emit_build_artifacts`, which the
build command calls so the detected partition is recorded without recomputing
it.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from codegraph.architecture_graph import ArchitectureGraph
from codegraph.graph_partitioning import GraphPartitions, build_partitions, save_partitions

# Bound the per-link edge sample so output stays small and deterministic.
_MAX_LINK_EDGES = 8

# Stable location for the build-emitted community overview artifact.
OVERVIEW_PATH = Path(".codegraph") / "architecture" / "community_overview.json"


@dataclass
class CommunitySummary:
    """One detected community: a structural cluster, not a declared subsystem.

    ``declared_subsystem`` is populated only when every node in the community
    carries the same ``subsystem`` attribute (declared policy/intent); it is
    ``None`` for mixed or undeclared communities, so detected communities are
    never silently treated as declared subsystems.

    ``files`` and ``directories`` are the distinct file paths and directories
    referenced by the community's nodes. ``boundary_edges`` are the actual
    workflow edge records incident to the community that cross its boundary
    (exactly one endpoint in the community), preserved as evidence.
    """

    community_id: str
    node_ids: List[str] = field(default_factory=list)
    size: int = 0
    internal_edge_count: int = 0
    boundary_nodes: List[str] = field(default_factory=list)
    declared_subsystem: Optional[str] = None
    node_type_counts: Dict[str, int] = field(default_factory=dict)
    files: List[str] = field(default_factory=list)
    directories: List[str] = field(default_factory=list)
    boundary_edges: List[Dict[str, Any]] = field(default_factory=list)
    analysis: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "community_id": self.community_id,
            "size": self.size,
            "node_ids": list(self.node_ids),
            "internal_edge_count": self.internal_edge_count,
            "boundary_nodes": list(self.boundary_nodes),
            "declared_subsystem": self.declared_subsystem,
            "node_type_counts": dict(self.node_type_counts),
            "files": list(self.files),
            "directories": list(self.directories),
            "boundary_edges": [dict(edge) for edge in self.boundary_edges],
            "analysis": self.analysis,
        }


@dataclass
class CrossCommunityLink:
    """One directional dependency between two detected communities.

    ``coupling_score`` is a descriptive heuristic (cross edges over all edges
    touching the two communities), never a rejection criterion.
    """

    source_community: str
    target_community: str
    edge_count: int = 0
    edges: List[Dict[str, Any]] = field(default_factory=list)
    source_nodes: List[str] = field(default_factory=list)
    target_nodes: List[str] = field(default_factory=list)
    coupling_score: float = 0.0
    evidence: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_community": self.source_community,
            "target_community": self.target_community,
            "edge_count": self.edge_count,
            "edges": [dict(edge) for edge in self.edges],
            "source_nodes": sorted(self.source_nodes),
            "target_nodes": sorted(self.target_nodes),
            "coupling_score": round(self.coupling_score, 4),
            "evidence": self.evidence,
        }


@dataclass
class ArchitectureOverview:
    """Explainable structural overview: detected communities plus coupling."""

    communities: List[CommunitySummary] = field(default_factory=list)
    cross_community_links: List[CrossCommunityLink] = field(default_factory=list)
    metrics: Dict[str, float] = field(default_factory=dict)
    declared_subsystems: List[str] = field(default_factory=list)
    method: str = ""
    analysis: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "communities": [community.to_dict() for community in self.communities],
            "cross_community_links": [link.to_dict() for link in self.cross_community_links],
            "metrics": {k: round(v, 4) for k, v in self.metrics.items()},
            "declared_subsystems": sorted(self.declared_subsystems),
            "method": self.method,
            "analysis": self.analysis,
        }


def _edge_sort_key(edge: Dict[str, Any]) -> tuple:
    return (
        str(edge.get("source", "")),
        str(edge.get("target", "")),
        str(edge.get("edge_type", "")),
        str(edge.get("source_detail", "")),
    )


def _module_of(node_id: str) -> str:
    return node_id.split("::", 1)[0] if "::" in node_id else node_id


def _file_of(node: Dict[str, Any], node_id: str) -> str:
    file_path = str(node.get("file") or "").strip()
    if file_path:
        return file_path
    return _module_of(node_id)


def _directory_of(file_path: str) -> str:
    directory = str(Path(file_path).parent).replace("\\", "/")
    return directory if directory not in ("", ".") else "."


def build_architecture_overview(
    graph: ArchitectureGraph,
    *,
    partitions: Optional[GraphPartitions] = None,
    max_link_edges: int = _MAX_LINK_EDGES,
) -> ArchitectureOverview:
    """Build an explainable structural overview of *graph*.

    Communities come from :func:`build_partitions` (detected structure).
    Declared subsystems come only from graph metadata (system.json policy/
    intent) and are reported alongside, never merged into the communities.
    """
    if partitions is None:
        partitions = build_partitions(graph)

    node_by_id: Dict[str, Dict[str, Any]] = {}
    for node in graph.nodes:
        node_id = str(node.get("id", "")).strip()
        if node_id:
            node_by_id[node_id] = node

    declared_subsystems: List[str] = [
        str(item)
        for item in graph.metadata.get("subsystems", [])
        if isinstance(item, str) and item
    ]

    # ── Community summaries (detected structure) ──────────────────────
    communities: List[CommunitySummary] = []
    for pid in sorted(partitions.partitions):
        partition = partitions.partitions[pid]
        node_ids = sorted(partition.nodes)
        node_type_counts: Dict[str, int] = dict(
            Counter(
                str(node_by_id.get(nid, {}).get("type")
                    or graph.node_types.get(nid, "function"))
                for nid in node_ids
            )
        )
        files: List[str] = sorted(
            {_file_of(node_by_id.get(nid, {}), nid) for nid in node_ids}
        )
        directories: List[str] = sorted({_directory_of(file_path) for file_path in files})

        subsystem_values = [
            str(node.get("subsystem", "")).strip()
            for nid in node_ids
            if (node := node_by_id.get(nid)) and node.get("subsystem")
        ]
        subsystems = set(subsystem_values)
        # A declared subsystem only when every node carries one and they agree;
        # undeclared or mixed communities stay None (detected != declared).
        declared_subsystem = (
            sorted(subsystems)[0]
            if len(subsystems) == 1 and len(subsystem_values) == len(node_ids)
            else None
        )

        community_node_set = set(node_ids)
        boundary_edges: List[Dict[str, Any]] = []
        for edge in graph.edges:
            source = str(edge.get("source", "")).strip()
            target = str(edge.get("target", "")).strip()
            if not source or not target:
                continue
            source_in = source in community_node_set
            target_in = target in community_node_set
            if source_in == target_in:
                continue  # internal edge or unrelated edge
            boundary_edges.append(dict(edge))
        boundary_edges.sort(key=_edge_sort_key)

        boundary = sorted(partition.boundary_nodes)
        analysis = (
            f"Detected community '{pid}': {len(node_ids)} node(s), "
            f"{len(partition.internal_edges)} internal edge(s), "
            f"{len(boundary)} boundary node(s)"
        )
        if declared_subsystem:
            analysis += f"; all nodes share declared subsystem '{declared_subsystem}'."
        else:
            analysis += "; no single declared subsystem (mixed or undeclared)."

        communities.append(
            CommunitySummary(
                community_id=pid,
                node_ids=node_ids,
                size=len(node_ids),
                internal_edge_count=len(partition.internal_edges),
                boundary_nodes=boundary,
                declared_subsystem=declared_subsystem,
                node_type_counts=node_type_counts,
                files=files,
                directories=directories,
                boundary_edges=boundary_edges,
                analysis=analysis,
            )
        )

    # ── Cross-community dependency/coupling evidence (detected structure) ──
    link_edges: Dict[tuple, List[Dict[str, Any]]] = defaultdict(list)
    for edge in graph.edges:
        source = str(edge.get("source", "")).strip()
        target = str(edge.get("target", "")).strip()
        if not source or not target:
            continue
        source_pid = partitions.node_to_partition.get(source)
        target_pid = partitions.node_to_partition.get(target)
        if not source_pid or not target_pid or source_pid == target_pid:
            continue
        link_edges[(source_pid, target_pid)].append(dict(edge))

    links: List[CrossCommunityLink] = []
    for (source_pid, target_pid), edges in sorted(link_edges.items()):
        edges_sorted = sorted(edges, key=_edge_sort_key)
        sample = edges_sorted[:max_link_edges]

        source_partition = partitions.partitions[source_pid]
        target_partition = partitions.partitions[target_pid]
        internal_count = len(source_partition.internal_edges) + len(target_partition.internal_edges)
        denominator = internal_count + len(edges_sorted)
        coupling_score = len(edges_sorted) / denominator if denominator else 0.0

        source_nodes = sorted({edge.get("source", "") for edge in edges_sorted})
        target_nodes = sorted({edge.get("target", "") for edge in edges_sorted})
        evidence = (
            f"{len(edges_sorted)} edge(s) cross from '{source_pid}' to '{target_pid}' "
            f"involving {len(source_nodes)} source and {len(target_nodes)} target "
            f"boundary node(s); heuristic coupling {coupling_score:.2f}."
        )

        links.append(
            CrossCommunityLink(
                source_community=source_pid,
                target_community=target_pid,
                edge_count=len(edges_sorted),
                edges=sample,
                source_nodes=source_nodes,
                target_nodes=target_nodes,
                coupling_score=coupling_score,
                evidence=evidence,
            )
        )

    # ── Aggregate metrics (heuristic evidence, never a hard reject) ────
    internal_edges = sum(len(p.internal_edges) for p in partitions.partitions.values())
    cross_edges = sum(len(edges) for edges in link_edges.values())
    total_edges = internal_edges + cross_edges
    sizes = [community.size for community in communities]
    max_coupling = max((link.coupling_score for link in links), default=0.0)

    metrics: Dict[str, float] = {
        "community_count": float(len(communities)),
        "node_count": float(len(node_by_id)),
        "edge_count": float(len(graph.edges)),
        "internal_edges": float(internal_edges),
        "cross_edges": float(cross_edges),
        "internal_edge_ratio": (internal_edges / total_edges) if total_edges else 0.0,
        "mean_community_size": (sum(sizes) / len(sizes)) if sizes else 0.0,
        "max_coupling_score": max_coupling,
    }

    declared_note = (
        f"declared subsystems: {', '.join(declared_subsystems) if declared_subsystems else 'none'}"
    )
    analysis = (
        f"Detected {len(communities)} communities from graph structure using "
        f"'{partitions.metadata.get('method', 'label_propagation')}' partitioning; "
        f"{len(links)} cross-community dependency link(s) ({cross_edges} edge(s) crossing cuts). "
        f"{declared_note}. Coupling scores are heuristic evidence only, not acceptance criteria."
    )

    return ArchitectureOverview(
        communities=communities,
        cross_community_links=links,
        metrics=metrics,
        declared_subsystems=declared_subsystems,
        method=str(partitions.metadata.get("method", "")),
        analysis=analysis,
    )


def save_overview(project_root: Path, overview: ArchitectureOverview) -> Path:
    """Persist the overview as a deterministic JSON artifact.

    Written with ``sort_keys=True`` and no timestamps so output is byte-identical
    across builds of an unchanged repository.
    """
    path = project_root / OVERVIEW_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(overview.to_dict(), indent=2, sort_keys=True, ensure_ascii=False)
    path.write_text(payload + "\n", encoding="utf-8")
    return path


def emit_build_artifacts(project_root: Path) -> None:
    """Emit the stable community artifact during build.

    Builds partitions once (production default ``min_size=4``), saves them
    through the existing partition lifecycle, then saves the community
    overview. Partitions are computed a single time and reused for both
    artifacts so there is no needless duplicate costly work. All output is
    deterministic.
    """
    graph = ArchitectureGraph.load(project_root)
    partitions = build_partitions(graph)
    save_partitions(project_root, partitions)
    overview = build_architecture_overview(graph, partitions=partitions)
    save_overview(project_root, overview)
