from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Set

from codegraph.architecture_graph import ArchitectureGraph


@dataclass
class DiscoveredSubsystem:
    name: str
    nodes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "nodes": self.nodes, "size": len(self.nodes)}


def discover_subsystems(
    architecture_graph: ArchitectureGraph,
    *,
    method: str = "label_propagation",
    min_size: int = 3,
) -> List[DiscoveredSubsystem]:
    adjacency = _build_adjacency(architecture_graph)
    node_ids = sorted(adjacency.keys())
    if not node_ids:
        return []

    method = method.lower()
    if method == "louvain":
        labels = _louvain_like_labels(node_ids, adjacency)
    else:
        labels = _label_propagation(node_ids, adjacency)

    clusters: Dict[str, List[str]] = defaultdict(list)
    for node in node_ids:
        clusters[labels[node]].append(node)

    subsystems: List[DiscoveredSubsystem] = []
    for label, nodes in sorted(clusters.items(), key=lambda x: -len(x[1])):
        if len(nodes) < min_size:
            continue
        subsystems.append(DiscoveredSubsystem(name=f"{label}_cluster", nodes=sorted(nodes)))

    return subsystems


def _build_adjacency(architecture_graph: ArchitectureGraph) -> Dict[str, Set[str]]:
    adjacency: Dict[str, Set[str]] = defaultdict(set)
    node_ids = [str(node.get("id", "")) for node in architecture_graph.nodes]
    for node_id in node_ids:
        adjacency[node_id]

    for edge in architecture_graph.edges:
        source = str(edge.get("source", ""))
        target = str(edge.get("target", ""))
        if source and target:
            adjacency[source].add(target)
            adjacency[target].add(source)

    return adjacency


def _label_propagation(node_ids: List[str], adjacency: Dict[str, Set[str]], iterations: int = 10) -> Dict[str, str]:
    labels: Dict[str, str] = {node: node for node in node_ids}

    for _ in range(iterations):
        changed = False
        for node in node_ids:
            neighbors = adjacency.get(node, set())
            if not neighbors:
                continue
            counts = Counter(labels[neighbor] for neighbor in neighbors)
            best_label = counts.most_common(1)[0][0]
            if labels[node] != best_label:
                labels[node] = best_label
                changed = True
        if not changed:
            break

    return labels


def _louvain_like_labels(node_ids: List[str], adjacency: Dict[str, Set[str]], iterations: int = 5) -> Dict[str, str]:
    labels: Dict[str, str] = {node: node for node in node_ids}

    for _ in range(iterations):
        changed = False
        for node in node_ids:
            neighbor_labels = Counter(labels[neighbor] for neighbor in adjacency.get(node, set()))
            if not neighbor_labels:
                continue
            best_label, _ = neighbor_labels.most_common(1)[0]
            if labels[node] != best_label:
                labels[node] = best_label
                changed = True
        if not changed:
            break

    return labels
