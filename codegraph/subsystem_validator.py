from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Set, Tuple

from codegraph.architecture_graph import ArchitectureGraph
from codegraph.subsystem_graph import SubsystemGraph


@dataclass
class ValidationResult:
    valid: bool
    violations: List[Dict[str, Any]]


def validate_subsystem_patch(
    architecture_graph: ArchitectureGraph,
    subsystem_graph: SubsystemGraph,
    patch: Dict[str, Any],
) -> ValidationResult:
    violations: List[Dict[str, Any]] = []

    remove_edges = {(edge[0], edge[1]) for edge in patch.get("remove_edge", []) if len(edge) >= 2}
    add_edges = {(edge[0], edge[1]) for edge in patch.get("add_edge", []) if len(edge) >= 2}

    boundary_nodes = set(subsystem_graph.boundary_nodes)
    external_links = _external_links(subsystem_graph.external_edges)

    for source, target in remove_edges:
        if (source, target) in external_links and source in boundary_nodes:
            violations.append({
                "violation": "external_dependency_breakage",
                "source": source,
                "target": target,
                "reason": "boundary node loses external dependency",
                "recommended_fix": "preserve or rewire dependency before removal",
            })

    for source, target in add_edges:
        if _layer_violation(architecture_graph, source, target):
            violations.append({
                "violation": "layer_boundary",
                "source": source,
                "target": target,
                "reason": "new edge violates layer boundary",
                "recommended_fix": "introduce service layer",
            })

    existing_edges = {(str(edge.get("source", "")), str(edge.get("target", ""))) for edge in architecture_graph.edges}
    for source, target in add_edges:
        if (target, source) in existing_edges:
            violations.append({
                "violation": "cross_subsystem_cycle",
                "source": source,
                "target": target,
                "reason": "new edge closes cycle with existing external edge",
                "recommended_fix": "introduce event-based boundary or dependency inversion",
            })

    subsystem_nodes = {str(node.get("id", "")) for node in subsystem_graph.nodes}
    for boundary in boundary_nodes:
        if boundary not in subsystem_nodes:
            violations.append({
                "violation": "api_contract_breakage",
                "source": boundary,
                "target": "external",
                "reason": "boundary contract node removed from subsystem patch",
                "recommended_fix": "retain boundary API contract node",
            })

    return ValidationResult(valid=len(violations) == 0, violations=violations)


def _external_links(edges: List[Dict[str, Any]]) -> Set[Tuple[str, str]]:
    links: Set[Tuple[str, str]] = set()
    for edge in edges:
        links.add((str(edge.get("source", "")), str(edge.get("target", ""))))
    return links


def _layer_violation(architecture_graph: ArchitectureGraph, source: str, target: str) -> bool:
    layer_map: Dict[str, int] = {}
    for node in architecture_graph.nodes:
        node_id = str(node.get("id", ""))
        layer_map[node_id] = int(node.get("layer", 3))

    if source not in layer_map or target not in layer_map:
        return False
    return layer_map[source] < layer_map[target]
