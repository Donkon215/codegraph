"""codegraph.architecture_decay — Architecture decay and dead subsystem detection."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from codegraph.index import IndexStore
from codegraph.models.graph0 import Graph0
from codegraph.subsystem import SubsystemReport, detect_subsystems


def _module_of(node_id: str) -> str:
    return node_id.split("::")[0] if "::" in node_id else node_id


@dataclass
class GodModuleWarning:
    module: str
    fan_in: int
    fan_out: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "GodModuleWarning",
            "module": self.module,
            "fan_in": self.fan_in,
            "fan_out": self.fan_out,
        }


@dataclass
class CycleCluster:
    modules: List[str] = field(default_factory=list)
    size: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "CycleCluster",
            "modules": self.modules,
            "size": self.size,
        }


@dataclass
class DeadSubsystem:
    name: str
    modules: List[str] = field(default_factory=list)
    fan_in: int = 0
    test_links: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "DeadSubsystem",
            "name": self.name,
            "modules": self.modules,
            "fan_in": self.fan_in,
            "test_links": self.test_links,
        }


@dataclass
class ExtractableSubsystem:
    name: str
    modules: List[str] = field(default_factory=list)
    internal_edges: int = 0
    external_edges: int = 0
    confidence: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "ExtractableSubsystem",
            "name": self.name,
            "modules": self.modules,
            "internal_edges": self.internal_edges,
            "external_edges": self.external_edges,
            "confidence": round(self.confidence, 3),
        }


@dataclass
class ArchitectureDecayReport:
    god_modules: List[GodModuleWarning] = field(default_factory=list)
    cyclic_subsystems: List[CycleCluster] = field(default_factory=list)
    dead_subsystems: List[DeadSubsystem] = field(default_factory=list)
    extractable_subsystems: List[ExtractableSubsystem] = field(default_factory=list)
    subsystem_count: int = 0
    coupling_index: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "god_modules": [warning.to_dict() for warning in self.god_modules],
            "cyclic_subsystems": [cluster.to_dict() for cluster in self.cyclic_subsystems],
            "dead_subsystems": [subsystem.to_dict() for subsystem in self.dead_subsystems],
            "extractable_subsystems": [subsystem.to_dict() for subsystem in self.extractable_subsystems],
            "subsystem_count": self.subsystem_count,
            "coupling_index": round(self.coupling_index, 4),
            "decay_signals": (
                len(self.god_modules)
                + len(self.cyclic_subsystems)
                + len(self.dead_subsystems)
            ),
        }


def _build_module_adjacency(index: IndexStore) -> Dict[str, Set[str]]:
    adjacency: Dict[str, Set[str]] = {}
    conn = index._get_conn()
    for source, target in conn.execute("SELECT node_id, callee_id FROM callees").fetchall():
        source_module = _module_of(source)
        target_module = _module_of(target)
        if source_module == target_module:
            continue
        adjacency.setdefault(source_module, set()).add(target_module)
        adjacency.setdefault(target_module, set())
    return adjacency


def _tarjan_scc(adjacency: Dict[str, Set[str]]) -> List[List[str]]:
    index_counter = [0]
    stack: List[str] = []
    on_stack: Set[str] = set()
    index_map: Dict[str, int] = {}
    low_link: Dict[str, int] = {}
    components: List[List[str]] = []

    def strong_connect(node: str) -> None:
        index_map[node] = index_counter[0]
        low_link[node] = index_counter[0]
        index_counter[0] += 1
        stack.append(node)
        on_stack.add(node)

        for neighbor in adjacency.get(node, set()):
            if neighbor not in index_map:
                strong_connect(neighbor)
                low_link[node] = min(low_link[node], low_link[neighbor])
            elif neighbor in on_stack:
                low_link[node] = min(low_link[node], index_map[neighbor])

        if low_link[node] == index_map[node]:
            component: List[str] = []
            while stack:
                top = stack.pop()
                on_stack.remove(top)
                component.append(top)
                if top == node:
                    break
            components.append(component)

    for node in adjacency:
        if node not in index_map:
            strong_connect(node)

    return components


def _module_test_links(index: IndexStore) -> Dict[str, int]:
    links: Dict[str, int] = {}
    conn = index._get_conn()
    try:
        rows = conn.execute("SELECT test_id, node_id FROM tests").fetchall()
    except Exception:
        return links

    for _, node_id in rows:
        module = _module_of(node_id)
        links[module] = links.get(module, 0) + 1
    return links


def _compute_coupling_index(adjacency: Dict[str, Set[str]]) -> float:
    total_edges = sum(len(targets) for targets in adjacency.values())
    modules = len(adjacency)
    if total_edges == 0 or modules == 0:
        return 0.0
    return total_edges / modules


def _detect_dead_subsystems(
    subsystem_report: SubsystemReport,
    adjacency: Dict[str, Set[str]],
    test_links: Dict[str, int],
) -> List[DeadSubsystem]:
    incoming: Dict[str, int] = {}
    for source, targets in adjacency.items():
        for target in targets:
            incoming[target] = incoming.get(target, 0) + 1
        incoming.setdefault(source, incoming.get(source, 0))

    dead: List[DeadSubsystem] = []
    for subsystem in subsystem_report.subsystems:
        modules = subsystem.files
        fan_in = sum(incoming.get(module, 0) for module in modules)
        subsystem_test_links = sum(test_links.get(module, 0) for module in modules)
        if fan_in == 0 and subsystem_test_links == 0:
            dead.append(
                DeadSubsystem(
                    name=subsystem.name,
                    modules=modules,
                    fan_in=fan_in,
                    test_links=subsystem_test_links,
                )
            )
    return dead


def _detect_extractable_subsystems(subsystem_report: SubsystemReport) -> List[ExtractableSubsystem]:
    candidates: List[ExtractableSubsystem] = []
    for subsystem in subsystem_report.subsystems:
        if len(subsystem.files) < 2:
            continue
        if subsystem.internal_edges <= 0:
            continue
        if subsystem.cohesion < 0.4:
            continue
        external_ratio = subsystem.external_edges / max(1, subsystem.internal_edges)
        if external_ratio > 1.0:
            continue

        confidence = min(1.0, subsystem.cohesion * 0.6 + (1.0 - min(1.0, external_ratio)) * 0.4)
        candidates.append(
            ExtractableSubsystem(
                name=subsystem.name,
                modules=subsystem.files,
                internal_edges=subsystem.internal_edges,
                external_edges=subsystem.external_edges,
                confidence=confidence,
            )
        )
    return candidates


def detect_architecture_decay(
    graph: Graph0,
    index: IndexStore,
    *,
    fan_in_threshold: int = 20,
    fan_out_threshold: int = 20,
) -> ArchitectureDecayReport:
    """Detect architecture decay signals (god modules, cycles, dead clusters)."""
    adjacency = _build_module_adjacency(index)
    report = ArchitectureDecayReport()

    # God modules (module-level fan-in/fan-out)
    module_fan_in: Dict[str, int] = {}
    module_fan_out: Dict[str, int] = {}
    for source, targets in adjacency.items():
        module_fan_out[source] = len(targets)
        module_fan_in.setdefault(source, module_fan_in.get(source, 0))
        for target in targets:
            module_fan_in[target] = module_fan_in.get(target, 0) + 1

    for module in sorted(set(module_fan_in) | set(module_fan_out)):
        fan_in = module_fan_in.get(module, 0)
        fan_out = module_fan_out.get(module, 0)
        if fan_in > fan_in_threshold or fan_out > fan_out_threshold:
            report.god_modules.append(
                GodModuleWarning(module=module, fan_in=fan_in, fan_out=fan_out)
            )

    # Cyclic subsystems using Tarjan SCC
    components = _tarjan_scc(adjacency)
    for component in components:
        if len(component) > 3:
            report.cyclic_subsystems.append(
                CycleCluster(modules=sorted(component), size=len(component))
            )

    # Subsystem-based dead/extractable detection
    subsystem_report = detect_subsystems(graph, index)
    report.subsystem_count = len(subsystem_report.subsystems)
    report.coupling_index = _compute_coupling_index(adjacency)
    test_links = _module_test_links(index)

    report.dead_subsystems = _detect_dead_subsystems(subsystem_report, adjacency, test_links)
    report.extractable_subsystems = _detect_extractable_subsystems(subsystem_report)
    return report


def record_architecture_history(
    project_root: Path,
    decay_report: ArchitectureDecayReport,
    *,
    layer_violations: int = 0,
) -> Path:
    """Append architecture drift metrics to .codegraph/architecture/architecture_history.json."""
    history_path = project_root / ".codegraph" / "architecture" / "architecture_history.json"
    history_path.parent.mkdir(parents=True, exist_ok=True)

    if history_path.exists():
        try:
            history = json.loads(history_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            history = {"entries": []}
    else:
        history = {"entries": []}

    entries = history.setdefault("entries", [])
    entries.append(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cycles_count": len(decay_report.cyclic_subsystems),
            "layer_violations": layer_violations,
            "coupling_index": round(decay_report.coupling_index, 4),
            "subsystem_count": decay_report.subsystem_count,
        }
    )
    history_path.write_text(json.dumps(history, indent=2), encoding="utf-8")
    return history_path
