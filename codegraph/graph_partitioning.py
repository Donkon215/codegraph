from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from codegraph.architecture_graph import ArchitectureGraph


PARTITIONS_DIR = Path(".codegraph") / "partitions"


@dataclass
class Partition:
    id: str
    nodes: Set[str] = field(default_factory=set)
    internal_edges: List[Dict[str, Any]] = field(default_factory=list)
    boundary_nodes: Set[str] = field(default_factory=set)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "partition_id": self.id,
            "nodes": sorted(self.nodes),
            "boundary_nodes": sorted(self.boundary_nodes),
            "size": len(self.nodes),
            "internal_edges": [dict(edge) for edge in self.internal_edges],
        }


@dataclass
class GraphPartitions:
    partitions: Dict[str, Partition] = field(default_factory=dict)
    node_to_partition: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "partitions": {pid: part.to_dict() for pid, part in sorted(self.partitions.items())},
            "node_to_partition": dict(self.node_to_partition),
            "metadata": dict(self.metadata),
        }

    def partition_for_node(self, node_id: str) -> Optional[Partition]:
        pid = self.node_to_partition.get(node_id)
        if not pid:
            return None
        return self.partitions.get(pid)


def _module_of(node_id: str) -> str:
    return node_id.split("::", 1)[0] if "::" in node_id else node_id


def _partition_id(seed: str) -> str:
    module = _module_of(seed).replace("/", "_").replace(".", "_")
    if not module:
        module = "partition"
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:8]
    return f"{module}_{digest}"


def _label_propagation_communities(
    nodes: Set[str],
    adjacency: Dict[str, Set[str]],
    *,
    max_iterations: int = 20,
) -> Dict[str, str]:
    # Initialize labels by module to encourage module-level cohesion
    labels: Dict[str, str] = {node: _module_of(node) for node in nodes}
    if not nodes:
        return labels

    for _ in range(max_iterations):
        changed = False
        for node in sorted(nodes):
            neighbors = adjacency.get(node, set())
            if not neighbors:
                continue
            counts: Dict[str, int] = defaultdict(int)
            for nbr in neighbors:
                counts[labels.get(nbr, nbr)] += 1
            best = max(sorted(counts.items()), key=lambda item: (item[1], item[0]))[0]
            if labels[node] != best:
                labels[node] = best
                changed = True
        if not changed:
            break
    return labels


def build_partitions(
    graph: ArchitectureGraph,
    *,
    min_size: int = 4,
    method: str = "label_propagation",
) -> GraphPartitions:
    node_ids: Set[str] = {
        str(node.get("id", "")).strip()
        for node in graph.nodes
        if str(node.get("id", "")).strip()
    }
    adjacency: Dict[str, Set[str]] = {nid: set() for nid in node_ids}

    for source, targets in graph.adj_out.items():
        if source not in adjacency:
            adjacency[source] = set()
        for target in targets:
            adjacency[source].add(target)
            adjacency.setdefault(target, set()).add(source)

    if method not in {"label_propagation", "louvain"}:
        raise ValueError("method must be 'label_propagation' or 'louvain'")

    labels = _label_propagation_communities(node_ids, adjacency)

    grouped: Dict[str, Set[str]] = defaultdict(set)
    for node_id, label in labels.items():
        grouped[label].add(node_id)

    partitions = GraphPartitions()
    large_partitions: List[Set[str]] = [members for members in grouped.values() if len(members) >= min_size]

    # Keep small isolated nodes near module locality to avoid giant catch-all partitions.
    if not large_partitions:
        large_partitions = list(grouped.values())

    for members in large_partitions:
        seed = sorted(members)[0]
        pid = _partition_id(seed)
        partitions.partitions[pid] = Partition(id=pid, nodes=set(members))
        for node_id in members:
            partitions.node_to_partition[node_id] = pid

    # Attach any unmapped nodes to the closest mapped module partition.
    unmapped = [node for node in node_ids if node not in partitions.node_to_partition]
    for node in unmapped:
        module = _module_of(node)
        attached = False
        for pid, partition in partitions.partitions.items():
            if any(_module_of(existing) == module for existing in partition.nodes):
                partition.nodes.add(node)
                partitions.node_to_partition[node] = pid
                attached = True
                break
        if not attached:
            pid = _partition_id(node)
            partitions.partitions[pid] = Partition(id=pid, nodes={node})
            partitions.node_to_partition[node] = pid

    for edge in graph.edges:
        source = str(edge.get("source", "")).strip()
        target = str(edge.get("target", "")).strip()
        if not source or not target:
            continue
        src_pid = partitions.node_to_partition.get(source)
        tgt_pid = partitions.node_to_partition.get(target)
        if not src_pid or not tgt_pid:
            continue
        if src_pid == tgt_pid:
            partitions.partitions[src_pid].internal_edges.append(dict(edge))
        else:
            # Only mark nodes as boundary in the partition they belong to
            partitions.partitions[src_pid].boundary_nodes.add(source)
            partitions.partitions[tgt_pid].boundary_nodes.add(target)

    partitions.metadata = {
        "method": method,
        "partition_count": len(partitions.partitions),
        "node_count": len(node_ids),
        "edge_count": len(graph.edges),
        "min_size": min_size,
    }
    return partitions


def save_partitions(project_root: Path, partitions: GraphPartitions) -> Path:
    base = project_root / PARTITIONS_DIR
    base.mkdir(parents=True, exist_ok=True)

    manifest = {
        "metadata": partitions.metadata,
        "partition_ids": sorted(partitions.partitions.keys()),
    }
    (base / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    for pid, partition in partitions.partitions.items():
        payload = partition.to_dict()
        (base / f"partition_{pid}.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    mapping_path = base / "node_partition_map.json"
    mapping_path.write_text(
        json.dumps(partitions.node_to_partition, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return base


def load_partitions(project_root: Path) -> Optional[GraphPartitions]:
    base = project_root / PARTITIONS_DIR
    manifest_path = base / "manifest.json"
    mapping_path = base / "node_partition_map.json"
    if not manifest_path.exists() or not mapping_path.exists():
        return None

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        node_map = json.loads(mapping_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    out = GraphPartitions(partitions={}, node_to_partition=dict(node_map), metadata=dict(manifest.get("metadata", {})))
    for pid in manifest.get("partition_ids", []):
        p_path = base / f"partition_{pid}.json"
        if not p_path.exists():
            continue
        try:
            data = json.loads(p_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        out.partitions[pid] = Partition(
            id=str(data.get("partition_id", pid)),
            nodes=set(data.get("nodes", [])),
            boundary_nodes=set(data.get("boundary_nodes", [])),
            internal_edges=list(data.get("internal_edges", [])),
        )
    return out


def load_or_build_partitions(project_root: Path, graph: ArchitectureGraph) -> GraphPartitions:
    existing = load_partitions(project_root)
    if existing is not None and existing.partitions:
        return existing
    partitions = build_partitions(graph)
    save_partitions(project_root, partitions)
    return partitions


def list_partition_files(project_root: Path) -> List[str]:
    base = project_root / PARTITIONS_DIR
    if not base.exists():
        return []
    return sorted(path.name for path in base.glob("partition_*.json"))
