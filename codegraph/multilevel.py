"""codegraph.multilevel — Multi-level architecture graph analysis.

Operates on three levels of the dependency graph:
  Level 1: Function graph (individual functions/methods)
  Level 2: Module graph  (file-level aggregation)
  Level 3: Subsystem graph (subsystem-level aggregation)

Detects issues at each level: god functions, god modules, god subsystems.
Enables architecture reasoning at the appropriate abstraction level.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from codegraph.index import IndexStore
from codegraph.logging_config import get_logger
from codegraph.models.graph0 import Graph0

logger = get_logger("multilevel")


# ── Level 2: Module Graph ─────────────────────────────────────────────


@dataclass
class ModuleNode:
    """A node in the module-level graph."""

    file: str
    function_count: int = 0
    class_count: int = 0
    fan_in: int = 0  # modules importing this module
    fan_out: int = 0  # modules this module imports
    functions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file": self.file,
            "function_count": self.function_count,
            "class_count": self.class_count,
            "fan_in": self.fan_in,
            "fan_out": self.fan_out,
        }


@dataclass
class ModuleEdge:
    """An edge in the module-level graph."""

    source_file: str
    target_file: str
    call_count: int = 0  # number of function-level calls
    functions: List[Tuple[str, str]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source_file,
            "target": self.target_file,
            "call_count": self.call_count,
        }


@dataclass
class ModuleGraph:
    """Module-level architecture graph (Level 2)."""

    nodes: List[ModuleNode] = field(default_factory=list)
    edges: List[ModuleEdge] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": 2,
            "type": "module_graph",
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "summary": {
                "total_modules": len(self.nodes),
                "total_edges": len(self.edges),
                "avg_functions": (
                    sum(n.function_count for n in self.nodes) / len(self.nodes)
                    if self.nodes else 0
                ),
            },
        }

    def format(self) -> str:
        lines = [f"Module Graph ({len(self.nodes)} modules, {len(self.edges)} edges)"]
        top_by_fanout = sorted(self.nodes, key=lambda n: n.fan_out, reverse=True)
        if top_by_fanout:
            lines.append("\nTop modules by fan-out:")
            for m in top_by_fanout[:10]:
                lines.append(f"  {m.file}: out={m.fan_out} in={m.fan_in} funcs={m.function_count}")
        return "\n".join(lines)


# ── Level 3: Subsystem Graph ──────────────────────────────────────────


@dataclass
class SubsystemNode:
    """A node in the subsystem-level graph."""

    name: str
    module_count: int = 0
    function_count: int = 0
    internal_edges: int = 0
    external_edges_in: int = 0
    external_edges_out: int = 0
    cohesion: float = 0.0
    modules: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "module_count": self.module_count,
            "function_count": self.function_count,
            "internal_edges": self.internal_edges,
            "external_edges_in": self.external_edges_in,
            "external_edges_out": self.external_edges_out,
            "cohesion": round(self.cohesion, 3),
            "modules": self.modules,
        }


@dataclass
class SubsystemEdge:
    """An edge in the subsystem-level graph."""

    source: str
    target: str
    edge_count: int = 0
    coupling: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "edge_count": self.edge_count,
            "coupling": round(self.coupling, 3),
        }


@dataclass
class SubsystemGraph:
    """Subsystem-level architecture graph (Level 3)."""

    nodes: List[SubsystemNode] = field(default_factory=list)
    edges: List[SubsystemEdge] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": 3,
            "type": "subsystem_graph",
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "summary": {
                "total_subsystems": len(self.nodes),
                "total_edges": len(self.edges),
            },
        }

    def format(self) -> str:
        lines = [f"Subsystem Graph ({len(self.nodes)} subsystems, {len(self.edges)} edges)"]
        for n in sorted(self.nodes, key=lambda x: x.function_count, reverse=True):
            lines.append(
                f"  {n.name}: {n.module_count} modules, {n.function_count} funcs, "
                f"cohesion={n.cohesion:.2f}"
            )
        if self.edges:
            lines.append("\nCross-subsystem edges:")
            for e in sorted(self.edges, key=lambda x: x.edge_count, reverse=True)[:10]:
                lines.append(f"  {e.source} → {e.target}: {e.edge_count} calls")
        return "\n".join(lines)


# ── Multi-Level Issue Detection ────────────────────────────────────────


@dataclass
class MultiLevelSmell:
    """An architecture smell detected at a specific level."""

    level: int  # 1=function, 2=module, 3=subsystem
    smell_type: str
    severity: str = "warning"
    description: str = ""
    entity: str = ""
    metric_value: float = 0.0
    threshold: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level,
            "level_name": {1: "function", 2: "module", 3: "subsystem"}.get(self.level, "?"),
            "smell_type": self.smell_type,
            "severity": self.severity,
            "description": self.description,
            "entity": self.entity,
            "metric_value": round(self.metric_value, 3),
            "threshold": round(self.threshold, 3),
        }


@dataclass
class MultiLevelReport:
    """Multi-level architecture analysis report."""

    module_graph: ModuleGraph = field(default_factory=ModuleGraph)
    subsystem_graph: SubsystemGraph = field(default_factory=SubsystemGraph)
    smells: List[MultiLevelSmell] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        by_level: Dict[int, List[Dict]] = {1: [], 2: [], 3: []}
        for s in self.smells:
            by_level[s.level].append(s.to_dict())
        return {
            "module_graph": self.module_graph.to_dict(),
            "subsystem_graph": self.subsystem_graph.to_dict(),
            "smells": {
                "function_level": by_level[1],
                "module_level": by_level[2],
                "subsystem_level": by_level[3],
            },
            "summary": {
                "total_smells": len(self.smells),
                "by_level": {
                    "function": len(by_level[1]),
                    "module": len(by_level[2]),
                    "subsystem": len(by_level[3]),
                },
            },
        }

    def format(self) -> str:
        lines = ["Multi-Level Architecture Analysis"]
        by_level: Dict[int, List[MultiLevelSmell]] = {1: [], 2: [], 3: []}
        for s in self.smells:
            by_level[s.level].append(s)

        for level, name in [(1, "Function"), (2, "Module"), (3, "Subsystem")]:
            smells = by_level[level]
            lines.append(f"\n{name} Level ({len(smells)} smells):")
            for s in smells[:10]:
                lines.append(f"  [{s.severity}] {s.description}")
        return "\n".join(lines)


# ── Graph Construction ─────────────────────────────────────────────────


def build_module_graph(graph0: Graph0, index: IndexStore) -> ModuleGraph:
    """Build Level 2 module graph from function-level data."""
    mg = ModuleGraph()

    # Group nodes by file
    file_nodes: Dict[str, List[str]] = defaultdict(list)
    file_classes: Dict[str, Set[str]] = defaultdict(set)
    for node in graph0.nodes:
        file_nodes[node.file].append(node.id)
        if node.type == "class":
            file_classes[node.file].add(node.id)

    # Get function-level edges
    conn = index._get_conn()
    callee_rows = conn.execute("SELECT node_id, callee_id FROM callees").fetchall()

    # Map node → file
    node_to_file: Dict[str, str] = {n.id: n.file for n in graph0.nodes}

    # Build module edges
    module_edge_map: Dict[Tuple[str, str], List[Tuple[str, str]]] = defaultdict(list)
    for row in callee_rows:
        src_file = node_to_file.get(row[0], "")
        tgt_file = node_to_file.get(row[1], "")
        if src_file and tgt_file and src_file != tgt_file:
            module_edge_map[(src_file, tgt_file)].append((row[0], row[1]))

    # Compute fan-in/fan-out at module level
    module_fan_in: Dict[str, Set[str]] = defaultdict(set)
    module_fan_out: Dict[str, Set[str]] = defaultdict(set)
    for (sf, tf) in module_edge_map:
        module_fan_out[sf].add(tf)
        module_fan_in[tf].add(sf)

    # Build module nodes
    for f, nodes in file_nodes.items():
        mn = ModuleNode(
            file=f,
            function_count=len(nodes),
            class_count=len(file_classes.get(f, set())),
            fan_in=len(module_fan_in.get(f, set())),
            fan_out=len(module_fan_out.get(f, set())),
            functions=nodes[:50],
        )
        mg.nodes.append(mn)

    # Build module edges
    for (sf, tf), calls in module_edge_map.items():
        me = ModuleEdge(
            source_file=sf,
            target_file=tf,
            call_count=len(calls),
            functions=calls[:20],
        )
        mg.edges.append(me)

    return mg


def build_subsystem_graph(
    graph0: Graph0,
    index: IndexStore,
    subsystem_mapping: Dict[str, str],
) -> SubsystemGraph:
    """Build Level 3 subsystem graph.

    Args:
        subsystem_mapping: Maps file path → subsystem name.
    """
    sg = SubsystemGraph()

    # Group by subsystem
    subsys_files: Dict[str, Set[str]] = defaultdict(set)
    subsys_funcs: Dict[str, List[str]] = defaultdict(list)
    for node in graph0.nodes:
        ss = subsystem_mapping.get(node.file, "unknown")
        subsys_files[ss].add(node.file)
        subsys_funcs[ss].append(node.id)

    # Get edges
    conn = index._get_conn()
    callee_rows = conn.execute("SELECT node_id, callee_id FROM callees").fetchall()
    node_to_file: Dict[str, str] = {n.id: n.file for n in graph0.nodes}

    # Count internal/external edges per subsystem pair
    internal_edges: Dict[str, int] = defaultdict(int)
    cross_edges: Dict[Tuple[str, str], int] = defaultdict(int)

    for row in callee_rows:
        src_file = node_to_file.get(row[0], "")
        tgt_file = node_to_file.get(row[1], "")
        if not src_file or not tgt_file:
            continue
        src_ss = subsystem_mapping.get(src_file, "unknown")
        tgt_ss = subsystem_mapping.get(tgt_file, "unknown")
        if src_ss == tgt_ss:
            internal_edges[src_ss] += 1
        else:
            cross_edges[(src_ss, tgt_ss)] += 1

    # Build subsystem nodes
    for ss_name in sorted(set(list(subsys_files.keys()))):
        total_ext_in = sum(v for (_, t), v in cross_edges.items() if t == ss_name)
        total_ext_out = sum(v for (s, _), v in cross_edges.items() if s == ss_name)
        int_e = internal_edges.get(ss_name, 0)
        total_e = int_e + total_ext_in + total_ext_out
        cohesion = int_e / total_e if total_e > 0 else 0.0

        sn = SubsystemNode(
            name=ss_name,
            module_count=len(subsys_files.get(ss_name, set())),
            function_count=len(subsys_funcs.get(ss_name, [])),
            internal_edges=int_e,
            external_edges_in=total_ext_in,
            external_edges_out=total_ext_out,
            cohesion=cohesion,
            modules=sorted(subsys_files.get(ss_name, set())),
        )
        sg.nodes.append(sn)

    # Build subsystem edges
    for (src_ss, tgt_ss), count in sorted(cross_edges.items(), key=lambda x: -x[1]):
        se = SubsystemEdge(
            source=src_ss,
            target=tgt_ss,
            edge_count=count,
        )
        sg.edges.append(se)

    return sg


# ── Multi-Level Analysis ──────────────────────────────────────────────


def analyze_multilevel(
    graph0: Graph0,
    index: IndexStore,
    subsystem_mapping: Optional[Dict[str, str]] = None,
    *,
    god_function_threshold: int = 20,
    god_module_threshold: int = 30,
    god_subsystem_threshold: int = 300,
    module_fanout_threshold: int = 15,
    subsystem_cohesion_threshold: float = 0.2,
) -> MultiLevelReport:
    """Run architecture analysis at all three levels.

    Args:
        subsystem_mapping: Maps file → subsystem name. If None, inferred.
        god_function_threshold: Max callees for a function before warning.
        god_module_threshold: Max functions in a module before warning.
        god_subsystem_threshold: Max functions in a subsystem before warning.
        module_fanout_threshold: Max module-level fan-out before warning.
        subsystem_cohesion_threshold: Min cohesion before warning.
    """
    report = MultiLevelReport()

    # Build module graph (Level 2)
    report.module_graph = build_module_graph(graph0, index)

    # Build subsystem mapping if not provided
    if subsystem_mapping is None:
        subsystem_mapping = _infer_subsystem_mapping(graph0)

    # Build subsystem graph (Level 3)
    report.subsystem_graph = build_subsystem_graph(graph0, index, subsystem_mapping)

    # ── Level 1: Function smells ──
    conn = index._get_conn()
    callee_rows = conn.execute("SELECT node_id, callee_id FROM callees").fetchall()
    fan_out: Dict[str, int] = defaultdict(int)
    for row in callee_rows:
        fan_out[row[0]] += 1

    for nid, fo in fan_out.items():
        if fo >= god_function_threshold:
            report.smells.append(MultiLevelSmell(
                level=1,
                smell_type="god_function",
                severity="warning",
                description=f"God function: {nid} has {fo} callees",
                entity=nid,
                metric_value=fo,
                threshold=god_function_threshold,
            ))

    # ── Level 2: Module smells ──
    for mn in report.module_graph.nodes:
        if mn.function_count >= god_module_threshold:
            report.smells.append(MultiLevelSmell(
                level=2,
                smell_type="god_module",
                severity="warning",
                description=f"God module: {mn.file} has {mn.function_count} functions",
                entity=mn.file,
                metric_value=mn.function_count,
                threshold=god_module_threshold,
            ))
        if mn.fan_out >= module_fanout_threshold:
            report.smells.append(MultiLevelSmell(
                level=2,
                smell_type="high_fanout",
                severity="warning",
                description=f"High fan-out module: {mn.file} imports {mn.fan_out} modules",
                entity=mn.file,
                metric_value=mn.fan_out,
                threshold=module_fanout_threshold,
            ))

    # ── Level 3: Subsystem smells ──
    for sn in report.subsystem_graph.nodes:
        if sn.function_count >= god_subsystem_threshold:
            report.smells.append(MultiLevelSmell(
                level=3,
                smell_type="god_subsystem",
                severity="warning",
                description=f"God subsystem: {sn.name} has {sn.function_count} functions",
                entity=sn.name,
                metric_value=sn.function_count,
                threshold=god_subsystem_threshold,
            ))
        if sn.cohesion < subsystem_cohesion_threshold and (sn.internal_edges + sn.external_edges_in + sn.external_edges_out) > 5:
            report.smells.append(MultiLevelSmell(
                level=3,
                smell_type="low_cohesion",
                severity="info",
                description=f"Low cohesion subsystem: {sn.name} cohesion={sn.cohesion:.2f}",
                entity=sn.name,
                metric_value=sn.cohesion,
                threshold=subsystem_cohesion_threshold,
            ))

    return report


def _infer_subsystem_mapping(graph0: Graph0) -> Dict[str, str]:
    """Infer subsystem mapping from file paths.

    Uses top-level directory as subsystem name.
    """
    mapping: Dict[str, str] = {}
    for node in graph0.nodes:
        parts = node.file.replace("\\", "/").split("/")
        if len(parts) >= 2:
            mapping[node.file] = parts[0]
        else:
            mapping[node.file] = "root"
    return mapping
