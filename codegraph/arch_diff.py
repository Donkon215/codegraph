"""codegraph.arch_diff — Architecture diff engine.

Compares two snapshots of the dependency graph to detect structural
changes at the architecture level. Instead of diffing code, diffs the
dependency graph to reveal architectural regressions, new cycles,
coupling changes, and layer violations.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from codegraph.logging_config import get_logger

logger = get_logger("arch_diff")


@dataclass
class EdgeChange:
    """A single edge that was added or removed."""

    source: str
    target: str
    change_type: str  # "added", "removed"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "change": self.change_type,
        }


@dataclass
class NodeChange:
    """A node that was added or removed."""

    node_id: str
    file: str
    change_type: str  # "added", "removed"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "file": self.file,
            "change": self.change_type,
        }


@dataclass
class MetricDelta:
    """Change in an architecture metric."""

    metric: str
    old_value: float
    new_value: float
    delta: float
    regression: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metric": self.metric,
            "old": self.old_value,
            "new": self.new_value,
            "delta": round(self.delta, 4),
            "regression": self.regression,
        }


@dataclass
class ArchDiffReport:
    """Complete architecture diff report."""

    added_nodes: List[NodeChange] = field(default_factory=list)
    removed_nodes: List[NodeChange] = field(default_factory=list)
    added_edges: List[EdgeChange] = field(default_factory=list)
    removed_edges: List[EdgeChange] = field(default_factory=list)
    metric_deltas: List[MetricDelta] = field(default_factory=list)
    new_cycles: List[List[str]] = field(default_factory=list)
    resolved_cycles: List[List[str]] = field(default_factory=list)
    regressions: List[str] = field(default_factory=list)
    improvements: List[str] = field(default_factory=list)

    @property
    def has_regression(self) -> bool:
        return len(self.regressions) > 0

    @property
    def has_changes(self) -> bool:
        return bool(
            self.added_nodes or self.removed_nodes or
            self.added_edges or self.removed_edges
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": {
                "nodes_added": len(self.added_nodes),
                "nodes_removed": len(self.removed_nodes),
                "edges_added": len(self.added_edges),
                "edges_removed": len(self.removed_edges),
                "new_cycles": len(self.new_cycles),
                "resolved_cycles": len(self.resolved_cycles),
                "has_regression": self.has_regression,
            },
            "added_edges": [e.to_dict() for e in self.added_edges[:50]],
            "removed_edges": [e.to_dict() for e in self.removed_edges[:50]],
            "added_nodes": [n.to_dict() for n in self.added_nodes[:50]],
            "removed_nodes": [n.to_dict() for n in self.removed_nodes[:50]],
            "metric_deltas": [m.to_dict() for m in self.metric_deltas],
            "new_cycles": [c[:10] for c in self.new_cycles[:5]],
            "regressions": self.regressions,
            "improvements": self.improvements,
        }

    def format(self) -> str:
        lines = ["Architecture Diff"]
        lines.append(f"  Nodes: +{len(self.added_nodes)} -{len(self.removed_nodes)}")
        lines.append(f"  Edges: +{len(self.added_edges)} -{len(self.removed_edges)}")

        if self.new_cycles:
            lines.append(f"  New cycles: {len(self.new_cycles)}")
        if self.resolved_cycles:
            lines.append(f"  Resolved cycles: {len(self.resolved_cycles)}")

        if self.metric_deltas:
            lines.append("\nMetric changes:")
            for md in self.metric_deltas:
                direction = "+" if md.delta > 0 else ""
                flag = " REGRESSION" if md.regression else ""
                lines.append(
                    f"  {md.metric}: {md.old_value:.1f} -> {md.new_value:.1f} "
                    f"({direction}{md.delta:.1f}){flag}"
                )

        if self.regressions:
            lines.append("\nRegressions:")
            for r in self.regressions:
                lines.append(f"  - {r}")

        if self.improvements:
            lines.append("\nImprovements:")
            for imp in self.improvements:
                lines.append(f"  + {imp}")

        if self.added_edges:
            lines.append(f"\nNew edges ({len(self.added_edges)}):")
            for e in self.added_edges[:10]:
                lines.append(f"  {e.source} -> {e.target}")

        if self.removed_edges:
            lines.append(f"\nRemoved edges ({len(self.removed_edges)}):")
            for e in self.removed_edges[:10]:
                lines.append(f"  {e.source} -> {e.target}")

        return "\n".join(lines)


def diff_graphs(
    old_graph: Dict[str, Any],
    new_graph: Dict[str, Any],
    old_workflow: Dict[str, Any],
    new_workflow: Dict[str, Any],
) -> ArchDiffReport:
    """Compute architecture diff between two graph snapshots.

    Args:
        old_graph: Previous graph0.json data.
        new_graph: Current graph0.json data.
        old_workflow: Previous workflow.json data.
        new_workflow: Current workflow.json data.
    """
    report = ArchDiffReport()

    # Node diff
    old_nodes = {n["id"]: n for n in old_graph.get("nodes", [])}
    new_nodes = {n["id"]: n for n in new_graph.get("nodes", [])}

    old_ids = set(old_nodes.keys())
    new_ids = set(new_nodes.keys())

    for nid in new_ids - old_ids:
        n = new_nodes[nid]
        report.added_nodes.append(NodeChange(
            node_id=nid,
            file=n.get("file", ""),
            change_type="added",
        ))

    for nid in old_ids - new_ids:
        n = old_nodes[nid]
        report.removed_nodes.append(NodeChange(
            node_id=nid,
            file=n.get("file", ""),
            change_type="removed",
        ))

    # Edge diff
    old_edges = set()
    for e in old_workflow.get("edges", []):
        old_edges.add((e.get("source", ""), e.get("target", "")))

    new_edges = set()
    for e in new_workflow.get("edges", []):
        new_edges.add((e.get("source", ""), e.get("target", "")))

    for src, tgt in new_edges - old_edges:
        report.added_edges.append(EdgeChange(src, tgt, "added"))

    for src, tgt in old_edges - new_edges:
        report.removed_edges.append(EdgeChange(src, tgt, "removed"))

    # Metric deltas
    old_node_count = len(old_nodes)
    new_node_count = len(new_nodes)
    old_edge_count = len(old_edges)
    new_edge_count = len(new_edges)

    report.metric_deltas.append(MetricDelta(
        metric="node_count",
        old_value=old_node_count,
        new_value=new_node_count,
        delta=new_node_count - old_node_count,
    ))
    report.metric_deltas.append(MetricDelta(
        metric="edge_count",
        old_value=old_edge_count,
        new_value=new_edge_count,
        delta=new_edge_count - old_edge_count,
    ))

    # Edge density (edges / nodes)
    old_density = old_edge_count / old_node_count if old_node_count > 0 else 0
    new_density = new_edge_count / new_node_count if new_node_count > 0 else 0
    density_delta = new_density - old_density
    report.metric_deltas.append(MetricDelta(
        metric="edge_density",
        old_value=round(old_density, 3),
        new_value=round(new_density, 3),
        delta=round(density_delta, 4),
        regression=density_delta > 0.2,
    ))

    # Cycle diff
    old_adj = _build_adj(old_workflow)
    new_adj = _build_adj(new_workflow)
    old_cycles = _find_sccs(old_adj)
    new_cycles = _find_sccs(new_adj)

    # Find new and resolved cycles
    old_cycle_sets = {frozenset(c) for c in old_cycles}
    new_cycle_sets = {frozenset(c) for c in new_cycles}

    for c in new_cycle_sets - old_cycle_sets:
        report.new_cycles.append(sorted(c))
    for c in old_cycle_sets - new_cycle_sets:
        report.resolved_cycles.append(sorted(c))

    # Fan-in/fan-out changes
    old_max_fan_in = _max_fan_in(old_workflow)
    new_max_fan_in = _max_fan_in(new_workflow)
    fi_delta = new_max_fan_in - old_max_fan_in
    report.metric_deltas.append(MetricDelta(
        metric="max_fan_in",
        old_value=old_max_fan_in,
        new_value=new_max_fan_in,
        delta=fi_delta,
        regression=fi_delta > 10,
    ))

    old_max_fan_out = _max_fan_out(old_workflow)
    new_max_fan_out = _max_fan_out(new_workflow)
    fo_delta = new_max_fan_out - old_max_fan_out
    report.metric_deltas.append(MetricDelta(
        metric="max_fan_out",
        old_value=old_max_fan_out,
        new_value=new_max_fan_out,
        delta=fo_delta,
        regression=fo_delta > 10,
    ))

    # Classify regressions and improvements
    if report.new_cycles:
        report.regressions.append(
            f"{len(report.new_cycles)} new dependency cycle(s) introduced"
        )
    if report.resolved_cycles:
        report.improvements.append(
            f"{len(report.resolved_cycles)} dependency cycle(s) resolved"
        )
    if density_delta > 0.2:
        report.regressions.append(
            f"Edge density increased significantly ({old_density:.2f} -> {new_density:.2f})"
        )
    if len(report.added_edges) > 50:
        report.regressions.append(
            f"Large number of new edges ({len(report.added_edges)}) — possible coupling increase"
        )
    if fi_delta > 10:
        report.regressions.append(
            f"Max fan-in increased from {old_max_fan_in} to {new_max_fan_in}"
        )
    if len(report.removed_nodes) > len(report.added_nodes) * 0.5 and report.removed_nodes:
        report.improvements.append(
            f"Dead code cleanup: {len(report.removed_nodes)} nodes removed"
        )

    return report


def diff_from_files(
    old_graph_path: Path,
    new_graph_path: Path,
    old_workflow_path: Path,
    new_workflow_path: Path,
) -> ArchDiffReport:
    """Compute architecture diff from file paths."""
    old_graph = json.loads(old_graph_path.read_text(encoding="utf-8"))
    new_graph = json.loads(new_graph_path.read_text(encoding="utf-8"))
    old_workflow = json.loads(old_workflow_path.read_text(encoding="utf-8"))
    new_workflow = json.loads(new_workflow_path.read_text(encoding="utf-8"))
    return diff_graphs(old_graph, new_graph, old_workflow, new_workflow)


def save_snapshot(project_root: Path, label: str = "current") -> Path:
    """Save current graph and workflow as a named snapshot for future diffing."""
    graphs_dir = project_root / ".codegraph" / "graphs"
    workflow_dir = project_root / ".codegraph" / "workflow"
    snapshot_dir = project_root / ".codegraph" / "snapshots" / label
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    import shutil
    g0 = graphs_dir / "graph0.json"
    wf = workflow_dir / "workflow.json"

    if g0.exists():
        shutil.copy2(g0, snapshot_dir / "graph0.json")
    if wf.exists():
        shutil.copy2(wf, snapshot_dir / "workflow.json")

    return snapshot_dir


def diff_snapshots(project_root: Path, old_label: str, new_label: str = "current") -> ArchDiffReport:
    """Diff two named snapshots."""
    old_dir = project_root / ".codegraph" / "snapshots" / old_label

    if new_label == "current":
        new_graph = project_root / ".codegraph" / "graphs" / "graph0.json"
        new_wf = project_root / ".codegraph" / "workflow" / "workflow.json"
    else:
        new_dir = project_root / ".codegraph" / "snapshots" / new_label
        new_graph = new_dir / "graph0.json"
        new_wf = new_dir / "workflow.json"

    return diff_from_files(
        old_dir / "graph0.json",
        new_graph,
        old_dir / "workflow.json",
        new_wf,
    )


def _build_adj(workflow_data: Dict[str, Any]) -> Dict[str, Set[str]]:
    """Build adjacency from workflow JSON data."""
    adj: Dict[str, Set[str]] = defaultdict(set)
    for e in workflow_data.get("edges", []):
        adj[e.get("source", "")].add(e.get("target", ""))
    return adj


def _find_sccs(adj: Dict[str, Set[str]]) -> List[List[str]]:
    """Find non-trivial SCCs using iterative Tarjan."""
    index_counter = [0]
    stack: List[str] = []
    on_stack: Set[str] = set()
    indices: Dict[str, int] = {}
    lowlinks: Dict[str, int] = {}
    sccs: List[List[str]] = []

    all_nodes: Set[str] = set(adj.keys())
    for targets in adj.values():
        all_nodes.update(targets)

    def strongconnect(v: str) -> None:
        work: List[tuple] = [(v, 0, False)]
        while work:
            node, ni, ret = work[-1]
            if not ret:
                indices[node] = index_counter[0]
                lowlinks[node] = index_counter[0]
                index_counter[0] += 1
                stack.append(node)
                on_stack.add(node)

            neighbors = sorted(adj.get(node, set()))
            found = False
            for i in range(ni, len(neighbors)):
                w = neighbors[i]
                if w not in indices:
                    work[-1] = (node, i + 1, True)
                    work.append((w, 0, False))
                    found = True
                    break
                elif w in on_stack:
                    lowlinks[node] = min(lowlinks[node], indices[w])
            if not found:
                if lowlinks[node] == indices[node]:
                    scc: List[str] = []
                    while True:
                        w = stack.pop()
                        on_stack.discard(w)
                        scc.append(w)
                        if w == node:
                            break
                    if len(scc) > 1:
                        sccs.append(sorted(scc))
                work.pop()
                if work:
                    parent = work[-1][0]
                    lowlinks[parent] = min(lowlinks[parent], lowlinks[node])

    for node in all_nodes:
        if node not in indices:
            strongconnect(node)

    return sccs


def _max_fan_in(workflow_data: Dict[str, Any]) -> int:
    """Compute max fan-in from workflow edges."""
    fan_in: Dict[str, int] = defaultdict(int)
    for e in workflow_data.get("edges", []):
        fan_in[e.get("target", "")] += 1
    return max(fan_in.values()) if fan_in else 0


def _max_fan_out(workflow_data: Dict[str, Any]) -> int:
    """Compute max fan-out from workflow edges."""
    fan_out: Dict[str, int] = defaultdict(int)
    for e in workflow_data.get("edges", []):
        fan_out[e.get("source", "")] += 1
    return max(fan_out.values()) if fan_out else 0
