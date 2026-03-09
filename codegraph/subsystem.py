"""codegraph.subsystem — Automatic sub-architecture detection.

Clusters the dependency graph into subsystems using community detection
(Louvain-style modularity optimization). Identifies cohesive groups of
modules that form logical architectural units.
"""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from codegraph.index import IndexStore
from codegraph.logging_config import get_logger
from codegraph.models.graph0 import Graph0
from codegraph.models.graph1 import Graph1

logger = get_logger("subsystem")


@dataclass
class Subsystem:
    """A detected subsystem (community) within the architecture."""

    name: str
    nodes: List[str] = field(default_factory=list)
    files: List[str] = field(default_factory=list)
    internal_edges: int = 0
    external_edges: int = 0
    cohesion: float = 0.0  # ratio of internal to total edges

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "node_count": len(self.nodes),
            "file_count": len(self.files),
            "internal_edges": self.internal_edges,
            "external_edges": self.external_edges,
            "cohesion": round(self.cohesion, 3),
            "files": self.files,
        }


@dataclass
class SubsystemCoupling:
    """Coupling between two subsystems."""

    subsystem_a: str
    subsystem_b: str
    edge_count: int = 0
    coupling_strength: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "subsystem_a": self.subsystem_a,
            "subsystem_b": self.subsystem_b,
            "edge_count": self.edge_count,
            "coupling_strength": round(self.coupling_strength, 3),
        }


@dataclass
class SubsystemReport:
    """Complete subsystem detection report."""

    subsystems: List[Subsystem] = field(default_factory=list)
    couplings: List[SubsystemCoupling] = field(default_factory=list)
    modularity_score: float = 0.0
    total_nodes: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "subsystems": [s.to_dict() for s in self.subsystems],
            "couplings": [c.to_dict() for c in self.couplings],
            "modularity_score": round(self.modularity_score, 4),
            "total_nodes": self.total_nodes,
            "total_subsystems": len(self.subsystems),
        }

    def format(self) -> str:
        lines = [
            f"Subsystem Report ({len(self.subsystems)} subsystems, {self.total_nodes} nodes)",
            f"  Modularity: {self.modularity_score:.3f}",
        ]
        if self.subsystems:
            lines.append("\nSubsystems:")
            for s in self.subsystems:
                lines.append(
                    f"  {s.name}: {len(s.nodes)} nodes, {len(s.files)} files, "
                    f"cohesion={s.cohesion:.2f}"
                )
                for f in s.files[:5]:
                    lines.append(f"    {f}")
                if len(s.files) > 5:
                    lines.append(f"    ... and {len(s.files) - 5} more")
        if self.couplings:
            lines.append("\nInter-subsystem coupling:")
            for c in self.couplings[:10]:
                lines.append(
                    f"  {c.subsystem_a} <-> {c.subsystem_b}: "
                    f"{c.edge_count} edges (strength={c.coupling_strength:.2f})"
                )
        return "\n".join(lines)


def detect_subsystems(
    graph0: Graph0,
    index: IndexStore,
    *,
    resolution: float = 1.0,
    min_size: int = 2,
) -> SubsystemReport:
    """Detect subsystems using module-level community detection.

    Uses a simplified Louvain algorithm operating at file (module) level.
    Each file starts as its own community, then communities are merged
    greedily to maximize modularity.

    Args:
        resolution: Higher values produce more, smaller communities.
        min_size: Minimum number of nodes for a subsystem to be reported.
    """
    report = SubsystemReport()

    # Build module-level adjacency from workflow edges
    conn = index._conn
    callee_rows = conn.execute("SELECT node_id, callee_id FROM callees").fetchall()

    # Map nodes to files
    node_to_file: Dict[str, str] = {}
    for node in graph0.nodes:
        node_to_file[node.id] = node.file

    # Build file-level edge weights
    file_edges: Dict[Tuple[str, str], int] = defaultdict(int)
    total_edges = 0
    for row in callee_rows:
        src_file = node_to_file.get(row[0], "")
        tgt_file = node_to_file.get(row[1], "")
        if src_file and tgt_file and src_file != tgt_file:
            key = (min(src_file, tgt_file), max(src_file, tgt_file))
            file_edges[key] += 1
            total_edges += 1

    all_files = list(set(n.file for n in graph0.nodes))
    report.total_nodes = len(graph0.nodes)

    if total_edges == 0:
        # No cross-file edges; each file is its own subsystem
        for f in all_files:
            nodes = [n.id for n in graph0.nodes if n.file == f]
            if len(nodes) >= min_size:
                report.subsystems.append(Subsystem(
                    name=_derive_name(f),
                    nodes=nodes,
                    files=[f],
                    cohesion=1.0,
                ))
        return report

    # Simplified Louvain: assign each file to a community
    community: Dict[str, int] = {}
    for i, f in enumerate(all_files):
        community[f] = i

    # Degree of each file (sum of edge weights)
    degree: Dict[str, int] = defaultdict(int)
    for (a, b), w in file_edges.items():
        degree[a] += w
        degree[b] += w

    m2 = 2 * total_edges  # 2m for modularity formula

    # Greedy merge pass
    improved = True
    max_iterations = 50
    iteration = 0
    while improved and iteration < max_iterations:
        improved = False
        iteration += 1
        for f in all_files:
            current_comm = community[f]
            # Compute delta modularity for moving f to each neighbor community
            neighbor_comms: Dict[int, int] = defaultdict(int)  # comm -> edge weight
            for (a, b), w in file_edges.items():
                if a == f:
                    neighbor_comms[community[b]] += w
                elif b == f:
                    neighbor_comms[community[a]] += w

            best_comm = current_comm
            best_delta = 0.0

            ki = degree.get(f, 0)

            for comm, ki_in in neighbor_comms.items():
                if comm == current_comm:
                    continue
                # Sum of degrees in target community
                sum_tot = sum(degree.get(ff, 0) for ff in all_files if community[ff] == comm)
                # Modularity gain
                delta = resolution * (ki_in / total_edges - (sum_tot * ki) / (m2 * total_edges))
                if delta > best_delta:
                    best_delta = delta
                    best_comm = comm

            if best_comm != current_comm:
                community[f] = best_comm
                improved = True

    # Collect communities
    comm_files: Dict[int, List[str]] = defaultdict(list)
    for f, c in community.items():
        comm_files[c].append(f)

    # Build subsystems
    file_nodes: Dict[str, List[str]] = defaultdict(list)
    for node in graph0.nodes:
        file_nodes[node.file].append(node.id)

    subsystems: List[Subsystem] = []
    comm_map: Dict[str, str] = {}  # file -> subsystem name

    for comm_id, files in sorted(comm_files.items(), key=lambda x: -len(x[1])):
        nodes: List[str] = []
        for f in files:
            nodes.extend(file_nodes.get(f, []))
        if len(nodes) < min_size:
            continue

        name = _derive_subsystem_name(files)
        s = Subsystem(name=name, nodes=sorted(nodes), files=sorted(files))

        # Compute cohesion
        file_set = set(files)
        internal = 0
        external = 0
        for (a, b), w in file_edges.items():
            a_in = a in file_set
            b_in = b in file_set
            if a_in and b_in:
                internal += w
            elif a_in or b_in:
                external += w
        s.internal_edges = internal
        s.external_edges = external
        total = internal + external
        s.cohesion = internal / total if total > 0 else 1.0

        for f in files:
            comm_map[f] = name

        subsystems.append(s)

    report.subsystems = subsystems

    # Compute inter-subsystem coupling
    coupling_map: Dict[Tuple[str, str], int] = defaultdict(int)
    for (a, b), w in file_edges.items():
        sa = comm_map.get(a, "")
        sb = comm_map.get(b, "")
        if sa and sb and sa != sb:
            key = (min(sa, sb), max(sa, sb))
            coupling_map[key] += w

    couplings: List[SubsystemCoupling] = []
    for (sa, sb), w in coupling_map.items():
        # Coupling strength relative to total edges
        couplings.append(SubsystemCoupling(
            subsystem_a=sa,
            subsystem_b=sb,
            edge_count=w,
            coupling_strength=w / total_edges if total_edges > 0 else 0,
        ))
    couplings.sort(key=lambda c: c.edge_count, reverse=True)
    report.couplings = couplings

    # Compute modularity score (Q)
    q = 0.0
    for s in subsystems:
        file_set = set(s.files)
        lc = sum(w for (a, b), w in file_edges.items() if a in file_set and b in file_set)
        dc = sum(degree.get(f, 0) for f in s.files)
        q += (lc / total_edges) - resolution * (dc / m2) ** 2
    report.modularity_score = q

    return report


def _derive_name(filepath: str) -> str:
    """Derive a short name from a file path."""
    parts = filepath.replace("\\", "/").rsplit("/", 1)
    name = parts[-1].replace(".py", "")
    return name


def _derive_subsystem_name(files: List[str]) -> str:
    """Derive a subsystem name from its constituent files."""
    if not files:
        return "unknown"

    # Find common prefix
    normalized = [f.replace("\\", "/") for f in files]
    parts_list = [f.split("/") for f in normalized]

    if len(parts_list) == 1:
        return _derive_name(files[0])

    # Find common directory prefix
    common: List[str] = []
    for parts in zip(*parts_list):
        if len(set(parts)) == 1:
            common.append(parts[0])
        else:
            break

    if common:
        name = "/".join(common)
        if name.endswith(".py"):
            name = name[:-3]
        return name

    # Fallback: use most common directory
    dirs = ["/".join(p[:-1]) if len(p) > 1 else p[0] for p in parts_list]
    from collections import Counter
    most_common = Counter(dirs).most_common(1)
    return most_common[0][0] if most_common else "misc"
