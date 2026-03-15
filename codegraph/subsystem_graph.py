from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Set, Tuple


@dataclass
class SubsystemGraph:
    nodes: List[Dict[str, Any]] = field(default_factory=list)
    edges: List[Dict[str, Any]] = field(default_factory=list)
    boundary_nodes: List[str] = field(default_factory=list)
    external_edges: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_architecture_graph(
        cls,
        architecture_graph: Any,
        node_ids: Set[str],
        edges: List[Dict[str, Any]],
        external_edges: List[Dict[str, Any]],
        *,
        root_node: str,
    ) -> "SubsystemGraph":
        node_map = {str(node.get("id", "")): node for node in architecture_graph.nodes}
        selected_nodes = [node_map[node_id] for node_id in sorted(node_ids) if node_id in node_map]

        boundary: Set[str] = set()
        for edge in external_edges:
            source = str(edge.get("source", ""))
            target = str(edge.get("target", ""))
            if source in node_ids and target not in node_ids:
                boundary.add(source)
                boundary.add(target)
            if target in node_ids and source not in node_ids:
                boundary.add(target)
                boundary.add(source)

        return cls(
            nodes=selected_nodes,
            edges=edges,
            boundary_nodes=sorted(boundary),
            external_edges=external_edges,
            metadata={
                "root_node": root_node,
                "node_count": len(selected_nodes),
                "edge_count": len(edges),
            },
        )

    def to_architecture_patch(self) -> Dict[str, Any]:
        patch = {
            "remove_edge": [],
            "add_edge": [],
            "metadata": {
                "subsystem_root": self.metadata.get("root_node", ""),
                "boundary_nodes": self.boundary_nodes,
            },
        }

        original_edges: Set[Tuple[str, str, str]] = set()
        for edge in self.metadata.get("original_edges", []):
            original_edges.add((
                str(edge.get("source", "")),
                str(edge.get("target", "")),
                str(edge.get("edge_type", "call")),
            ))

        current_edges: Set[Tuple[str, str, str]] = set()
        for edge in self.edges:
            current_edges.add((
                str(edge.get("source", "")),
                str(edge.get("target", "")),
                str(edge.get("edge_type", "call")),
            ))

        for edge in sorted(original_edges - current_edges):
            patch["remove_edge"].append([edge[0], edge[1], edge[2]])
        for edge in sorted(current_edges - original_edges):
            patch["add_edge"].append([edge[0], edge[1], edge[2]])

        return patch

    def visualize(self) -> str:
        lines = ["graph TD"]
        node_ids = {str(node.get("id", "")) for node in self.nodes}
        for edge in self.edges:
            source = str(edge.get("source", ""))
            target = str(edge.get("target", ""))
            if source in node_ids and target in node_ids:
                lines.append(f"    {source.replace('/', '_').replace(':', '_')} --> {target.replace('/', '_').replace(':', '_')}")
        return "\n".join(lines)

    def compute_metrics(self) -> Dict[str, Any]:
        node_ids = {str(node.get("id", "")) for node in self.nodes}
        adjacency: Dict[str, List[str]] = {node_id: [] for node_id in node_ids}
        fan_in: Dict[str, int] = {node_id: 0 for node_id in node_ids}
        fan_out: Dict[str, int] = {node_id: 0 for node_id in node_ids}

        for edge in self.edges:
            source = str(edge.get("source", ""))
            target = str(edge.get("target", ""))
            if source not in node_ids or target not in node_ids:
                continue
            adjacency[source].append(target)
            fan_out[source] += 1
            fan_in[target] += 1

        cycle_count = _count_cycles(adjacency)

        layer_map: Dict[str, int] = {}
        for node in self.nodes:
            node_id = str(node.get("id", ""))
            layer_map[node_id] = int(node.get("layer", 3))

        layer_violations = 0
        for edge in self.edges:
            source = str(edge.get("source", ""))
            target = str(edge.get("target", ""))
            if source in layer_map and target in layer_map:
                if layer_map[source] < layer_map[target]:
                    layer_violations += 1

        return {
            "nodes": len(node_ids),
            "edges": len(self.edges),
            "boundary_nodes": len(self.boundary_nodes),
            "external_dependencies": len(self.external_edges),
            "cycle_count": cycle_count,
            "fan_in_max": max(fan_in.values()) if fan_in else 0,
            "fan_out_max": max(fan_out.values()) if fan_out else 0,
            "fan_in_avg": (sum(fan_in.values()) / len(fan_in)) if fan_in else 0.0,
            "fan_out_avg": (sum(fan_out.values()) / len(fan_out)) if fan_out else 0.0,
            "layer_violations": layer_violations,
        }


def _count_cycles(adjacency: Dict[str, List[str]]) -> int:
    visited: Set[str] = set()
    stack: Set[str] = set()
    cycles = 0

    def dfs(node: str) -> None:
        nonlocal cycles
        visited.add(node)
        stack.add(node)
        for nxt in adjacency.get(node, []):
            if nxt not in visited:
                dfs(nxt)
            elif nxt in stack:
                cycles += 1
        stack.remove(node)

    for node in adjacency:
        if node not in visited:
            dfs(node)

    return cycles
