"""Compare a saved predicted graph with the rebuilt actual architecture graph."""

from __future__ import annotations

from typing import Any, Dict, Set, Tuple

from codegraph.architecture_graph import ArchitectureGraph


def reconcile_graphs(predicted: ArchitectureGraph, actual: ArchitectureGraph) -> Dict[str, Any]:
    """Return a deterministic node, edge, and constraint drift report."""
    predicted_nodes = {str(node.get("id", "")) for node in predicted.nodes if node.get("id")}
    actual_nodes = {str(node.get("id", "")) for node in actual.nodes if node.get("id")}

    def edge_set(graph: ArchitectureGraph) -> Set[Tuple[str, str, str]]:
        return {
            (str(edge.get("source", "")), str(edge.get("target", "")),
             str(edge.get("edge_type", "call")))
            for edge in graph.edges
        }

    def constraint_set(graph: ArchitectureGraph) -> Set[Tuple[str, str, str]]:
        return {
            (str(item.get("constraint_type", "")), str(item.get("source", "")),
             str(item.get("target", "")))
            for item in graph.metadata.get("constraints", []) if isinstance(item, dict)
        }

    pn, an = edge_set(predicted), edge_set(actual)
    pc, ac = constraint_set(predicted), constraint_set(actual)
    return {
        "matches": predicted_nodes == actual_nodes and pn == an and pc == ac,
        "predicted_only_nodes": sorted(predicted_nodes - actual_nodes),
        "actual_only_nodes": sorted(actual_nodes - predicted_nodes),
        "predicted_only_edges": [list(item) for item in sorted(pn - an)],
        "actual_only_edges": [list(item) for item in sorted(an - pn)],
        "predicted_only_constraints": [list(item) for item in sorted(pc - ac)],
        "actual_only_constraints": [list(item) for item in sorted(ac - pc)],
        "predicted_node_count": len(predicted_nodes),
        "actual_node_count": len(actual_nodes),
    }


def reconcile_project(project_root: Any) -> Dict[str, Any]:
    """Load the saved prediction and current rebuilt graph, then compare them."""
    from pathlib import Path

    root = Path(project_root)
    predicted = ArchitectureGraph.load_predicted(root / ".codegraph" / "predicted_graph.json")
    actual = ArchitectureGraph.load(root)
    return reconcile_graphs(predicted, actual)
