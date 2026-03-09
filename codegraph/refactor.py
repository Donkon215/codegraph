"""codegraph.refactor — Refactoring suggestions engine.

Detects structural issues and suggests refactorings:
- Cycle detection (Tarjan SCC)
- God module detection (modules with too many nodes)
- High coupling detection
- Refactoring recommendations
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from codegraph.index import IndexStore
from codegraph.logging_config import get_logger
from codegraph.models.graph0 import Graph0

logger = get_logger("refactor")


@dataclass
class CycleInfo:
    """A strongly connected component (cycle) in the call graph."""

    nodes: List[str]
    size: int = 0
    files_involved: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.size = len(self.nodes)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nodes": self.nodes,
            "size": self.size,
            "files_involved": self.files_involved,
        }


@dataclass
class GodModule:
    """A module with an excessive number of nodes."""

    file: str
    node_count: int
    node_ids: List[str] = field(default_factory=list)
    suggestion: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file": self.file,
            "node_count": self.node_count,
            "suggestion": self.suggestion,
        }


@dataclass
class CouplingPair:
    """A pair of modules with high coupling."""

    module_a: str
    module_b: str
    shared_edges: int = 0
    coupling_strength: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "module_a": self.module_a,
            "module_b": self.module_b,
            "shared_edges": self.shared_edges,
            "coupling_strength": round(self.coupling_strength, 3),
        }


@dataclass
class RefactorSuggestion:
    """A single refactoring recommendation."""

    category: str  # "cycle", "god_module", "high_coupling", "dead_code"
    severity: str = "info"  # "info", "warning", "error"
    description: str = ""
    affected_nodes: List[str] = field(default_factory=list)
    action: str = ""  # "split_module", "extract_interface", "break_cycle", "remove"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "severity": self.severity,
            "description": self.description,
            "affected_nodes": self.affected_nodes[:10],
            "action": self.action,
        }


@dataclass
class RefactorReport:
    """Complete refactoring analysis report."""

    cycles: List[CycleInfo] = field(default_factory=list)
    god_modules: List[GodModule] = field(default_factory=list)
    coupling_pairs: List[CouplingPair] = field(default_factory=list)
    suggestions: List[RefactorSuggestion] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cycles": [c.to_dict() for c in self.cycles],
            "god_modules": [g.to_dict() for g in self.god_modules],
            "coupling_pairs": [c.to_dict() for c in self.coupling_pairs],
            "suggestions": [s.to_dict() for s in self.suggestions],
            "summary": {
                "total_cycles": len(self.cycles),
                "total_god_modules": len(self.god_modules),
                "total_coupling_issues": len(self.coupling_pairs),
                "total_suggestions": len(self.suggestions),
            },
        }

    def format(self) -> str:
        lines = ["Refactoring Analysis"]
        lines.append(f"  Cycles: {len(self.cycles)}")
        lines.append(f"  God modules: {len(self.god_modules)}")
        lines.append(f"  High coupling pairs: {len(self.coupling_pairs)}")
        lines.append(f"  Suggestions: {len(self.suggestions)}")

        if self.cycles:
            lines.append(f"\nCycles ({len(self.cycles)}):")
            for i, c in enumerate(self.cycles[:5]):
                lines.append(f"  {i + 1}. {c.size} nodes across {len(c.files_involved)} file(s)")
                for n in c.nodes[:3]:
                    lines.append(f"      {n}")
                if c.size > 3:
                    lines.append(f"      … and {c.size - 3} more")

        if self.god_modules:
            lines.append(f"\nGod modules ({len(self.god_modules)}):")
            for g in self.god_modules[:5]:
                lines.append(f"  {g.file}: {g.node_count} nodes — {g.suggestion}")

        if self.coupling_pairs:
            lines.append(f"\nHigh coupling ({len(self.coupling_pairs)}):")
            for c in self.coupling_pairs[:5]:
                lines.append(
                    f"  {c.module_a} <-> {c.module_b}: "
                    f"{c.shared_edges} edges (strength={c.coupling_strength:.2f})"
                )

        if self.suggestions:
            lines.append(f"\nSuggestions ({len(self.suggestions)}):")
            for s in self.suggestions:
                lines.append(f"  [{s.severity}] {s.description}")
                if s.action:
                    lines.append(f"    Action: {s.action}")

        return "\n".join(lines)


def analyze_refactoring(
    index: IndexStore,
    graph0: Graph0,
    *,
    god_module_threshold: int = 30,
    coupling_threshold: int = 10,
) -> RefactorReport:
    """Run full refactoring analysis."""
    report = RefactorReport()

    # 1. Detect cycles
    report.cycles = detect_cycles(index)
    for cycle in report.cycles:
        if cycle.size >= 5:
            report.suggestions.append(RefactorSuggestion(
                category="cycle",
                severity="warning",
                description=f"Cycle of {cycle.size} nodes across {len(cycle.files_involved)} file(s)",
                affected_nodes=cycle.nodes,
                action="break_cycle",
            ))

    # 2. Detect god modules
    report.god_modules = detect_god_modules(graph0, threshold=god_module_threshold)
    for gm in report.god_modules:
        report.suggestions.append(RefactorSuggestion(
            category="god_module",
            severity="warning",
            description=f"{gm.file} has {gm.node_count} nodes",
            affected_nodes=gm.node_ids[:5],
            action="split_module",
        ))

    # 3. Detect high coupling
    report.coupling_pairs = detect_coupling(index, threshold=coupling_threshold)
    for cp in report.coupling_pairs:
        report.suggestions.append(RefactorSuggestion(
            category="high_coupling",
            severity="info",
            description=f"High coupling between {cp.module_a} and {cp.module_b} ({cp.shared_edges} edges)",
            action="extract_interface",
        ))

    return report


def detect_cycles(index: IndexStore) -> List[CycleInfo]:
    """Detect all non-trivial strongly connected components using Tarjan's algorithm."""
    conn = index._conn
    callee_rows = conn.execute("SELECT node_id, callee_id FROM callees").fetchall()

    adj: Dict[str, List[str]] = defaultdict(list)
    all_nodes: Set[str] = set()
    for row in callee_rows:
        adj[row[0]].append(row[1])
        all_nodes.add(row[0])
        all_nodes.add(row[1])

    # Tarjan's SCC
    index_counter = [0]
    stack: List[str] = []
    on_stack: Set[str] = set()
    indices: Dict[str, int] = {}
    lowlinks: Dict[str, int] = {}
    sccs: List[List[str]] = []

    def strongconnect(v: str) -> None:
        indices[v] = index_counter[0]
        lowlinks[v] = index_counter[0]
        index_counter[0] += 1
        stack.append(v)
        on_stack.add(v)

        for w in adj.get(v, []):
            if w not in indices:
                strongconnect(w)
                lowlinks[v] = min(lowlinks[v], lowlinks[w])
            elif w in on_stack:
                lowlinks[v] = min(lowlinks[v], indices[w])

        if lowlinks[v] == indices[v]:
            scc: List[str] = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                scc.append(w)
                if w == v:
                    break
            if len(scc) > 1:
                sccs.append(scc)

    # Use iterative approach to avoid recursion limit
    import sys
    old_limit = sys.getrecursionlimit()
    sys.setrecursionlimit(max(old_limit, len(all_nodes) + 1000))
    try:
        for node in all_nodes:
            if node not in indices:
                strongconnect(node)
    finally:
        sys.setrecursionlimit(old_limit)

    # Convert to CycleInfo
    cycles: List[CycleInfo] = []
    for scc in sccs:
        files = list(set(n.split("::")[0] for n in scc))
        cycles.append(CycleInfo(nodes=sorted(scc), files_involved=sorted(files)))

    cycles.sort(key=lambda c: c.size, reverse=True)
    return cycles


def detect_god_modules(
    graph0: Graph0,
    threshold: int = 30,
) -> List[GodModule]:
    """Detect modules with too many nodes."""
    file_counts: Dict[str, List[str]] = defaultdict(list)
    for node in graph0.nodes:
        file_counts[node.file].append(node.id)

    god_modules: List[GodModule] = []
    for filepath, node_ids in file_counts.items():
        if len(node_ids) >= threshold:
            suggestion = f"Consider splitting into smaller modules (has {len(node_ids)} nodes, threshold={threshold})"
            god_modules.append(GodModule(
                file=filepath,
                node_count=len(node_ids),
                node_ids=sorted(node_ids),
                suggestion=suggestion,
            ))

    god_modules.sort(key=lambda g: g.node_count, reverse=True)
    return god_modules


def detect_coupling(
    index: IndexStore,
    threshold: int = 10,
) -> List[CouplingPair]:
    """Detect pairs of modules with high bidirectional coupling."""
    conn = index._conn

    # Count cross-module edges
    callee_rows = conn.execute("SELECT node_id, callee_id FROM callees").fetchall()

    # Map node → module (file path)
    node_rows = conn.execute("SELECT node_id, file FROM nodes").fetchall()
    node_to_file: Dict[str, str] = {r[0]: r[1] for r in node_rows}

    pair_counts: Dict[Tuple[str, str], int] = defaultdict(int)
    for row in callee_rows:
        src_file = node_to_file.get(row[0], "")
        dst_file = node_to_file.get(row[1], "")
        if src_file and dst_file and src_file != dst_file:
            key = tuple(sorted([src_file, dst_file]))
            pair_counts[key] += 1  # type: ignore[arg-type]

    # Get total edges per file for normalization
    file_edge_count: Dict[str, int] = defaultdict(int)
    for row in callee_rows:
        f = node_to_file.get(row[0], "")
        if f:
            file_edge_count[f] += 1

    pairs: List[CouplingPair] = []
    for (mod_a, mod_b), count in pair_counts.items():
        if count >= threshold:
            total = file_edge_count.get(mod_a, 1) + file_edge_count.get(mod_b, 1)
            strength = count / max(total, 1)
            pairs.append(CouplingPair(
                module_a=mod_a,
                module_b=mod_b,
                shared_edges=count,
                coupling_strength=strength,
            ))

    pairs.sort(key=lambda p: p.shared_edges, reverse=True)
    return pairs
