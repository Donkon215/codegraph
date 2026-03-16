from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from codegraph.architecture_graph import ArchitectureGraph
from codegraph.architecture_refactor_planner import top_refactor_suggestions
from codegraph.architecture_smells import detect_architecture_smells
from codegraph.subsystem_extractor import extract_subsystem

MAX_SUBSYSTEM_CONTEXT_BYTES = 50 * 1024


@dataclass
class SubsystemContext:
    subsystem_root: str
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]
    boundary_nodes: List[str]
    smells: List[Dict[str, Any]]
    refactor_suggestions: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "subsystem_root": self.subsystem_root,
            "nodes": self.nodes,
            "edges": self.edges,
            "boundary_nodes": self.boundary_nodes,
            "smells": self.smells,
            "refactor_suggestions": self.refactor_suggestions,
        }


def build_subsystem_context(
    project_root: Path,
    root_node: str,
    *,
    depth: int = 2,
    max_nodes: int = 200,
) -> SubsystemContext:
    arch = ArchitectureGraph.load(project_root)
    subsystem = extract_subsystem(
        arch,
        root_node,
        depth=depth,
        max_nodes=max_nodes,
        project_root=project_root,
    )

    smells_index = detect_architecture_smells(arch, project_root)
    subsystem_node_ids = {str(node.get("id", "")) for node in subsystem.nodes}
    smells = [
        smell.to_dict()
        for smell in smells_index.smells
        if (smell.node and smell.node in subsystem_node_ids) or (not smell.node)
    ][:30]

    refactors = [
        suggestion
        for suggestion in top_refactor_suggestions(project_root, limit=10)
        if suggestion.get("component", "") in subsystem_node_ids
        or not suggestion.get("component")
    ]

    context = SubsystemContext(
        subsystem_root=root_node,
        nodes=subsystem.nodes,
        edges=subsystem.edges,
        boundary_nodes=subsystem.boundary_nodes,
        smells=smells,
        refactor_suggestions=refactors,
    )

    return _cap_context_size(context)


def save_subsystem_context(project_root: Path, context: SubsystemContext) -> Path:
    out = project_root / ".codegraph" / "context" / "subsystem_context.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(context.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def _cap_context_size(context: SubsystemContext) -> SubsystemContext:
    payload = context.to_dict()
    size = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    if size <= MAX_SUBSYSTEM_CONTEXT_BYTES:
        return context

    nodes = list(context.nodes)
    edges = list(context.edges)
    smells = list(context.smells)
    refactors = list(context.refactor_suggestions)

    while size > MAX_SUBSYSTEM_CONTEXT_BYTES and len(nodes) > 20:
        nodes = nodes[: max(20, len(nodes) // 2)]
        allowed = {str(node.get("id", "")) for node in nodes}
        edges = [edge for edge in edges if str(edge.get("source", "")) in allowed and str(edge.get("target", "")) in allowed]
        payload = {
            "subsystem_root": context.subsystem_root,
            "nodes": nodes,
            "edges": edges,
            "boundary_nodes": [node for node in context.boundary_nodes if node in allowed],
            "smells": smells[:10],
            "refactor_suggestions": refactors[:5],
        }
        size = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    return SubsystemContext(
        subsystem_root=context.subsystem_root,
        nodes=payload["nodes"],
        edges=payload["edges"],
        boundary_nodes=payload["boundary_nodes"],
        smells=payload["smells"],
        refactor_suggestions=payload["refactor_suggestions"],
    )
