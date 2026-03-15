from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from codegraph.architecture_graph import ArchitectureGraph


@dataclass
class ModuleNode:
    id: str
    node_type: str  # module, package, service, component

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "node_type": self.node_type}


@dataclass
class ModuleEdge:
    source: str
    target: str
    edge_type: str  # import, dependency, service_usage

    def to_dict(self) -> Dict[str, Any]:
        return {"source": self.source, "target": self.target, "edge_type": self.edge_type}


@dataclass
class GraphModule:
    nodes: List[ModuleNode] = field(default_factory=list)
    edges: List[ModuleEdge] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "metadata": self.metadata,
        }

    def save(self, project_root: Path) -> Path:
        out = project_root / ".codegraph" / "graphs" / "graph_module.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return out

    def detect_layer_violations(self, layer_order: Dict[str, int]) -> List[Dict[str, Any]]:
        violations: List[Dict[str, Any]] = []
        for edge in self.edges:
            src_layer = layer_order.get(_layer_hint(edge.source), 0)
            tgt_layer = layer_order.get(_layer_hint(edge.target), 0)
            if src_layer < tgt_layer:
                violations.append({
                    "source": edge.source,
                    "target": edge.target,
                    "reason": "upward_dependency",
                })
        return violations

    def subsystem_dependencies(self) -> Dict[str, Set[str]]:
        deps: Dict[str, Set[str]] = {}
        for edge in self.edges:
            src = edge.source.split("/", 1)[0]
            tgt = edge.target.split("/", 1)[0]
            if src == tgt:
                continue
            deps.setdefault(src, set()).add(tgt)
        return deps

    def detect_service_boundaries(self) -> List[Dict[str, Any]]:
        boundaries: List[Dict[str, Any]] = []
        service_nodes = [n.id for n in self.nodes if n.node_type == "service"]
        by_service = {s: 0 for s in service_nodes}
        for edge in self.edges:
            if edge.source in by_service:
                by_service[edge.source] += 1
            if edge.target in by_service:
                by_service[edge.target] += 1
        for service, degree in sorted(by_service.items(), key=lambda x: -x[1]):
            boundaries.append({"service": service, "interaction_degree": degree})
        return boundaries


def _layer_hint(module_path: str) -> str:
    low = module_path.lower()
    if "/cli/" in low or "api" in low or "controller" in low:
        return "API"
    if "service" in low:
        return "Service"
    if "repo" in low or "model" in low or "data" in low:
        return "Data"
    if "infra" in low or "storage" in low:
        return "Infrastructure"
    return "Service"


def _classify_module_type(module_path: str) -> str:
    low = module_path.lower()
    if "/services/" in low or low.endswith("service.py"):
        return "service"
    if "/models/" in low:
        return "component"
    if low.endswith("/__init__.py"):
        return "package"
    return "module"


def build_module_graph(project_root: Path) -> GraphModule:
    arch = ArchitectureGraph.load(project_root)

    modules: Dict[str, ModuleNode] = {}
    edge_keys: Set[Tuple[str, str, str]] = set()
    edges: List[ModuleEdge] = []

    for node in arch.structure_graph.nodes:
        mod = node.file
        if mod and mod not in modules:
            modules[mod] = ModuleNode(id=mod, node_type=_classify_module_type(mod))

    for edge in arch.workflow_graph.edges:
        src = edge.source.split("::", 1)[0]
        tgt = edge.target.split("::", 1)[0]
        if not src or not tgt or src == tgt:
            continue
        if src not in modules:
            modules[src] = ModuleNode(id=src, node_type=_classify_module_type(src))
        if tgt not in modules:
            modules[tgt] = ModuleNode(id=tgt, node_type=_classify_module_type(tgt))
        edge_type = "service_usage" if ("service" in src.lower() or "service" in tgt.lower()) else "dependency"
        key = (src, tgt, edge_type)
        if key in edge_keys:
            continue
        edge_keys.add(key)
        edges.append(ModuleEdge(source=src, target=tgt, edge_type=edge_type))

    graph = GraphModule(
        nodes=sorted(modules.values(), key=lambda n: n.id),
        edges=edges,
        metadata={
            "total_nodes": len(modules),
            "total_edges": len(edges),
        },
    )
    return graph
