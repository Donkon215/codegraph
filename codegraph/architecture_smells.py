from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from codegraph.architecture_graph import ArchitectureGraph


@dataclass
class ArchitectureSmell:
    smell_type: str
    severity: str
    description: str
    node: str = ""
    metric_value: float = 0.0
    threshold: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "smell_type": self.smell_type,
            "severity": self.severity,
            "description": self.description,
            "node": self.node,
            "metric_value": round(self.metric_value, 4),
            "threshold": round(self.threshold, 4),
        }


@dataclass
class ArchitectureSmellIndex:
    smells: List[ArchitectureSmell] = field(default_factory=list)

    @property
    def smell_count(self) -> int:
        return len(self.smells)

    @property
    def critical_smell_count(self) -> int:
        return len([s for s in self.smells if s.severity == "error"])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "smell_count": self.smell_count,
            "critical_smell_count": self.critical_smell_count,
            "smells": [s.to_dict() for s in self.smells],
        }


def _node_module(node_id: str) -> str:
    return node_id.split("::", 1)[0] if "::" in node_id else node_id


def _load_rules(project_root: Path) -> List[Dict[str, Any]]:
    path = project_root / ".codegraph" / "workflow" / "suggested_workflow.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("rules", [])
    except Exception:
        return []


def detect_architecture_smells(
    architecture_graph: ArchitectureGraph,
    project_root: Path,
    *,
    god_module_threshold: int = 30,
    fan_in_threshold: int = 30,
) -> ArchitectureSmellIndex:
    nodes = architecture_graph.structure_graph.nodes
    edges = architecture_graph.workflow_graph.edges
    graph1 = architecture_graph.intent_graph

    module_size: Dict[str, int] = {}
    fan_in: Dict[str, int] = {}
    fan_out: Dict[str, int] = {}

    for node in nodes:
        module_size[node.file] = module_size.get(node.file, 0) + 1

    for edge in edges:
        fan_out[edge.source] = fan_out.get(edge.source, 0) + 1
        fan_in[edge.target] = fan_in.get(edge.target, 0) + 1

    smells: List[ArchitectureSmell] = []

    for mod, size in module_size.items():
        if size > god_module_threshold:
            smells.append(ArchitectureSmell(
                smell_type="god_module",
                severity="warning",
                description=f"{mod} has {size} nodes (> {god_module_threshold})",
                node=mod,
                metric_value=float(size),
                threshold=float(god_module_threshold),
            ))

    for node_id, fin in fan_in.items():
        if fin >= fan_in_threshold:
            severity = "error" if fin >= fan_in_threshold * 1.5 else "warning"
            smells.append(ArchitectureSmell(
                smell_type="fan_in_hotspot",
                severity=severity,
                description=f"{node_id} fan-in={fin} (>= {fan_in_threshold})",
                node=node_id,
                metric_value=float(fin),
                threshold=float(fan_in_threshold),
            ))

    layer_violations = 0
    for edge in edges:
        src = graph1.get_node(edge.source)
        tgt = graph1.get_node(edge.target)
        if src and tgt and src.layer < tgt.layer:
            layer_violations += 1
    if layer_violations > 0:
        smells.append(ArchitectureSmell(
            smell_type="cross_layer_dependencies",
            severity="error",
            description=f"Detected {layer_violations} upward layer dependencies",
            metric_value=float(layer_violations),
            threshold=0.0,
        ))

    node_ids = {n.id for n in nodes}
    orphan_services = 0
    for node in nodes:
        is_service = node.id.endswith("Service") or (
            "::" in node.id and node.id.split("::")[-1].endswith("Service")
        )
        if not is_service:
            continue
        if fan_in.get(node.id, 0) == 0 and fan_out.get(node.id, 0) == 0:
            orphan_services += 1
    if orphan_services > 0:
        smells.append(ArchitectureSmell(
            smell_type="orphan_services",
            severity="warning",
            description=f"Detected {orphan_services} orphan services",
            metric_value=float(orphan_services),
            threshold=0.0,
        ))

    rules = _load_rules(project_root)
    forbidden_hits = 0
    for rule in rules:
        if rule.get("type") != "forbidden_call":
            continue
        src_pat = rule.get("source", "")
        tgt_pat = rule.get("target", "")
        for edge in edges:
            if fnmatch.fnmatch(edge.source, src_pat) and fnmatch.fnmatch(edge.target, tgt_pat):
                forbidden_hits += 1
    if forbidden_hits > 0:
        smells.append(ArchitectureSmell(
            smell_type="forbidden_dependencies",
            severity="error",
            description=f"Detected {forbidden_hits} forbidden dependencies",
            metric_value=float(forbidden_hits),
            threshold=0.0,
        ))

    # Simple dependency-cycle smell on module graph
    module_adj: Dict[str, set[str]] = {}
    for edge in edges:
        src_mod = _node_module(edge.source)
        tgt_mod = _node_module(edge.target)
        if src_mod == tgt_mod:
            continue
        module_adj.setdefault(src_mod, set()).add(tgt_mod)

    visited: set[str] = set()
    stack: set[str] = set()
    cycles = 0

    def _dfs(m: str) -> None:
        nonlocal cycles
        visited.add(m)
        stack.add(m)
        for nxt in module_adj.get(m, set()):
            if nxt not in visited:
                _dfs(nxt)
            elif nxt in stack:
                cycles += 1
        stack.remove(m)

    for mod in list(module_adj.keys()):
        if mod not in visited:
            _dfs(mod)

    if cycles > 0:
        smells.append(ArchitectureSmell(
            smell_type="dependency_cycles",
            severity="error",
            description=f"Detected {cycles} dependency cycles",
            metric_value=float(cycles),
            threshold=0.0,
        ))

    return ArchitectureSmellIndex(smells=smells)
