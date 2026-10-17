"""codegraph.architecture_metrics — Standing structural metrics of the extracted graph.

Computes advisory, inspectable structural metrics from the canonical
``ArchitectureGraph``: per-module coupling, strongly connected components
(cycles), hub nodes, and bridge edges. Every number is shipped together with the
node ids and edges that produced it, so a reviewer can recompute any number by
hand and get the same answer.

These metrics are advisory: they never gate a build, an apply, or a simulation
verdict, and they do not replace the simulator's sandboxed cycle/score checks on
proposed changes. This module computes the standing structural picture of the
current graph only.

Metric definitions
------------------

Coupling (module level)
    A module is the part of a node id before the first ``::``. For each module
    ``m`` let ``members(m)`` be the set of node ids in that module and let
    ``crossing(m)`` be the set of edges ``(s -> t)`` where exactly one of s, t
    is in ``members(m)``. Then::

        coupling(m) = |crossing(m)| / max(1, |members(m)|)

    Normalising by module size means a small, tightly boundaried module is not
    confused with a large, loosely coupled one. The crossing edges themselves
    are stored as evidence.

Cycles
    The strongly connected components (SCCs) of the directed graph that contain
    more than one node. Each component is reported with its sorted member node
    ids and the edges between those members as evidence. Computed with an
    iterative Kosaraju pass; self-loops alone do not form a reported cycle.

Hubs
    For each node n::

        score(n) = in_degree(n) + out_degree(n) + bounded_reach(n)

    where in_degree/out_degree are direct edge counts and ``bounded_reach(n)``
    is the number of distinct nodes reachable from n following out-edges within
    ``REACH_DEPTH`` edges (default 3). The traversal is deliberately bounded so
    transitive reach stays cheap on large graphs: reach is bounded, not run
    behind an opt-in flag.

    The top band is the top ``HUB_BAND`` fraction of nodes (default 10%), with
    every node tied at the cutoff score included. Isolated nodes (score 0) are
    never hubs. Tie-breaking is explicit: higher score first, then node id
    ascending, so equal scores produce a stable, sorted result. Each hub reports
    its direct callers (in-neighbors) as evidence; every listed caller has a
    direct edge to the hub.

Bridges
    An edge whose removal increases the number of weakly connected components,
    computed on the undirected view of the graph with an iterative Tarjan
    bridge pass. Each bridge reports the edge and the two components (sorted
    node id lists) it joins, found by removing the edge and searching both
    sides.

Determinism
-----------
All output collections are sorted, floats are rounded to six decimals, and no
timestamps are emitted, so two builds of an unchanged repository produce
byte-identical metric output (verify with
``json.dumps(report.to_dict(), sort_keys=True)``).

Written definition: ``docs/architecture-metrics.md``.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from codegraph.architecture_graph import ArchitectureGraph
from codegraph.logging_config import get_logger

logger = get_logger("architecture_metrics")

REPORT_PATH = Path(".codegraph") / "architecture_metrics.json"

# Documented bound on the transitive traversal used for hub reach. Stated here
# so the cost trade-off is visible: reach is bounded, not opt-in.
REACH_DEPTH = 3
# Top band fraction for hub selection.
HUB_BAND = 0.10


def _module_of(node_id: str) -> str:
    return node_id.split("::", 1)[0] if "::" in node_id else node_id


def _all_node_ids(graph: ArchitectureGraph) -> List[str]:
    ids: Set[str] = set()
    for node in graph.nodes:
        nid = str(node.get("id", "")).strip()
        if nid:
            ids.add(nid)
    for edge in graph.edges:
        for end in (
            str(edge.get("source", "")).strip(),
            str(edge.get("target", "")).strip(),
        ):
            if end:
                ids.add(end)
    return sorted(ids)


# ═════════════════════════════════════════════════════════════════════════════
# Coupling
# ═════════════════════════════════════════════════════════════════════════════


@dataclass
class ModuleCoupling:
    module: str
    node_count: int
    crossing_edges: int
    coupling: float
    edges: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "module": self.module,
            "node_count": self.node_count,
            "crossing_edges": self.crossing_edges,
            "coupling": round(self.coupling, 6),
            "edges": self.edges,
        }


def compute_coupling(graph: ArchitectureGraph) -> List[ModuleCoupling]:
    """Per-module boundary coupling.

    ``coupling(module) = |edges crossing the module boundary| /
    max(1, |nodes in module|). An edge crosses the boundary when exactly one
    endpoint belongs to the module. Returns modules sorted by module id with
    edges sorted for deterministic output.
    """
    modules: Dict[str, Set[str]] = defaultdict(set)
    for node in graph.nodes:
        nid = str(node.get("id", "")).strip()
        if nid:
            modules[_module_of(nid)].add(nid)
    for edge in graph.edges:
        source = str(edge.get("source", "")).strip()
        target = str(edge.get("target", "")).strip()
        if source:
            modules[_module_of(source)].add(source)
        if target:
            modules[_module_of(target)].add(target)

    result: List[ModuleCoupling] = []
    for module in sorted(modules):
        members = modules[module]
        crossing: List[Dict[str, Any]] = []
        for edge in graph.edges:
            source = str(edge.get("source", "")).strip()
            target = str(edge.get("target", "")).strip()
            edge_type = str(edge.get("edge_type", "call"))
            if not source or not target:
                continue
            source_in = source in members
            target_in = target in members
            if source_in == target_in:
                continue  # both inside or both outside: does not cross boundary
            # Preserve the actual original edge record (including source_detail
            # and any other distinguishing attrs) so the count is manually
            # reproducible from graph.edges. Parallel and reverse-direction
            # records are kept separate; nothing is merged or lost.
            record = dict(edge)
            record["source"] = source
            record["target"] = target
            record.setdefault("edge_type", edge_type)
            crossing.append(record)
        crossing.sort(key=lambda e: (e["source"], e["target"], e.get("edge_type", "")))
        coupling = len(crossing) / max(1, len(members))
        result.append(
            ModuleCoupling(
                module=module,
                node_count=len(members),
                crossing_edges=len(crossing),
                coupling=coupling,
                edges=crossing,
            )
        )
    return result


# ═════════════════════════════════════════════════════════════════════════════
# Cycles (strongly connected components > 1 node)
# ═════════════════════════════════════════════════════════════════════════════


@dataclass
class CycleComponent:
    nodes: List[str]
    size: int
    edges: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nodes": self.nodes,
            "size": self.size,
            "edges": self.edges,
        }


def _strongly_connected_components(
    nodes: List[str], adj_out: Dict[str, Set[str]]
) -> List[List[str]]:
    """Iterative Kosaraju SCC pass. Returns components with sorted members,
    components ordered by their smallest member. Deterministic."""
    visited: Set[str] = set()
    order: List[str] = []

    for start in nodes:
        if start in visited:
            continue
        stack: List[Tuple[str, bool]] = [(start, False)]
        while stack:
            node, processed = stack.pop()
            if processed:
                order.append(node)
                continue
            if node in visited:
                continue
            visited.add(node)
            stack.append((node, True))
            for nbr in sorted(adj_out.get(node, ()), reverse=True):
                if nbr not in visited:
                    stack.append((nbr, False))

    adj_in: Dict[str, Set[str]] = defaultdict(set)
    for source, targets in adj_out.items():
        for target in targets:
            adj_in[target].add(source)

    components: List[List[str]] = []
    visited2: Set[str] = set()
    for start in reversed(order):
        if start in visited2:
            continue
        component: Set[str] = set()
        stack = [start]
        while stack:
            node = stack.pop()
            if node in visited2:
                continue
            visited2.add(node)
            component.add(node)
            stack.extend(sorted(adj_in.get(node, ()), reverse=True))
        components.append(sorted(component))

    components.sort(key=lambda comp: comp[0] if comp else "")
    return components


def compute_cycles(graph: ArchitectureGraph) -> List[CycleComponent]:
    """Strongly connected components larger than one node.

    Each component lists its member node ids and the edges between members as
    evidence. Self-loops alone do not form a reported cycle. This is a standing
    structural metric of the extracted graph, not the simulator's sandboxed
    cycle check on proposed changes.
    """
    nodes = _all_node_ids(graph)
    adj_out = {nid: set(graph.adj_out.get(nid, set())) for nid in nodes}
    components = _strongly_connected_components(nodes, adj_out)

    node_set = set(nodes)
    result: List[CycleComponent] = []
    for component in components:
        if len(component) <= 1:
            continue
        members = set(component)
        edges: List[Dict[str, Any]] = []
        for edge in graph.edges:
            source = str(edge.get("source", "")).strip()
            target = str(edge.get("target", "")).strip()
            edge_type = str(edge.get("edge_type", "call"))
            if not source or not target:
                continue
            if source in members and target in members:
                # Preserve every original edge record: parallel same-type edges
                # can carry distinct source_detail/call sites, so no dedup.
                record = dict(edge)
                record["source"] = source
                record["target"] = target
                record.setdefault("edge_type", edge_type)
                edges.append(record)
        # Stable deterministic order: full-record JSON key keeps parallel
        # records distinguishable while remaining reproducible.
        edges.sort(key=lambda edge: json.dumps(edge, sort_keys=True))
        result.append(
            CycleComponent(nodes=component, size=len(component), edges=edges)
        )
    return result


# ═════════════════════════════════════════════════════════════════════════════
# Hubs
# ═════════════════════════════════════════════════════════════════════════════


@dataclass
class HubMetric:
    node_id: str
    score: float
    in_degree: int
    out_degree: int
    reach: int
    callers: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "score": round(self.score, 6),
            "in_degree": self.in_degree,
            "out_degree": self.out_degree,
            "reach": self.reach,
            "callers": self.callers,
        }


def _bounded_reach(start: str, adj_out: Dict[str, Set[str]], depth: int) -> int:
    """Number of distinct nodes reachable from ``start`` within ``depth``
    out-edge steps (excluding ``start`` itself). Traversal is bounded."""
    if depth <= 0:
        return 0
    seen: Set[str] = set()
    queue: deque[Tuple[str, int]] = deque([(start, 0)])
    while queue:
        node, dist = queue.popleft()
        if dist >= depth:
            continue
        for nbr in adj_out.get(node, ()):
            if nbr == start or nbr in seen:
                continue
            seen.add(nbr)
            queue.append((nbr, dist + 1))
    return len(seen)


def compute_hubs(
    graph: ArchitectureGraph,
    *,
    hub_band: float = HUB_BAND,
    reach_depth: int = REACH_DEPTH,
) -> List[HubMetric]:
    """Hub nodes in the top band of centrality.

    ``score(n) = in_degree(n) + out_degree(n) + bounded_reach(n)``. The top
    band is the top ``hub_band`` fraction of nodes, ties at the cutoff included,
    ordered by descending score then ascending node id. Each hub reports its
    direct callers (in-neighbors) as evidence.
    """
    nodes = _all_node_ids(graph)
    adj_out = {nid: set(graph.adj_out.get(nid, set())) for nid in nodes}
    adj_in = {nid: set(graph.adj_in.get(nid, set())) for nid in nodes}

    # Degree counts edge records (matching codegraph's fan_in/fan_out convention),
    # so parallel records each count toward a node's centrality. Reach counts
    # distinct nodes, not records, so the set-based adjacency stays correct there.
    in_degree: Dict[str, int] = {nid: 0 for nid in nodes}
    out_degree: Dict[str, int] = {nid: 0 for nid in nodes}
    for edge in graph.edges:
        source = str(edge.get("source", "")).strip()
        target = str(edge.get("target", "")).strip()
        if source:
            out_degree[source] = out_degree.get(source, 0) + 1
        if target:
            in_degree[target] = in_degree.get(target, 0) + 1
    reach = {nid: _bounded_reach(nid, adj_out, reach_depth) for nid in nodes}
    score = {
        nid: in_degree[nid] + out_degree[nid] + reach[nid] for nid in nodes
    }

    ranked = sorted(nodes, key=lambda nid: (-score[nid], nid))
    count = len(nodes)
    band_size = max(1, math.ceil(hub_band * count)) if count else 0
    if band_size >= count:
        cutoff_score = None
    else:
        cutoff_score = score[ranked[band_size - 1]]

    hubs: List[HubMetric] = []
    for nid in ranked:
        if score[nid] <= 0:
            continue  # isolated nodes are never hubs
        if cutoff_score is not None and score[nid] < cutoff_score:
            continue
        hubs.append(
            HubMetric(
                node_id=nid,
                score=float(score[nid]),
                in_degree=in_degree[nid],
                out_degree=out_degree[nid],
                reach=reach[nid],
                callers=sorted(adj_in.get(nid, set())),
            )
        )
    return hubs


# ═════════════════════════════════════════════════════════════════════════════
# Bridges
# ═════════════════════════════════════════════════════════════════════════════


@dataclass
class BridgeMetric:
    source: str
    target: str
    component_a: List[str]
    component_b: List[str]
    edge: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "component_a": self.component_a,
            "component_b": self.component_b,
            "edge": dict(self.edge),
        }


def _undirected_pair_count(
    graph: ArchitectureGraph,
) -> Tuple[Dict[str, Set[str]], Dict[Tuple[str, str], int]]:
    """Undirected adjacency plus per-pair multiplicity over edge records.

    Every edge record (in either direction) counts toward its undirected pair
    ``{source, target}``; self-loops are ignored. Parallel and reverse-direction
    records raise the multiplicity above one, so removing a single record never
    disconnects a pair joined by more than one record.
    """
    nodes = _all_node_ids(graph)
    adj: Dict[str, Set[str]] = {nid: set() for nid in nodes}
    pair_count: Dict[Tuple[str, str], int] = defaultdict(int)
    for edge in graph.edges:
        source = str(edge.get("source", "")).strip()
        target = str(edge.get("target", "")).strip()
        if not source or not target or source == target:
            continue
        pair = tuple(sorted((source, target)))
        pair_count[pair] += 1
        adj.setdefault(source, set()).add(target)
        adj.setdefault(target, set()).add(source)
    return adj, dict(pair_count)


def _bfs_component_excluding(
    start: str, adj: Dict[str, Set[str]], blocked_pair: Tuple[str, str]
) -> Set[str]:
    """Nodes reachable from ``start`` without traversing ``blocked_pair``."""
    seen: Set[str] = {start}
    queue: deque[str] = deque([start])
    while queue:
        node = queue.popleft()
        for nbr in adj.get(node, ()):
            if tuple(sorted((node, nbr))) == blocked_pair:
                continue
            if nbr not in seen:
                seen.add(nbr)
                queue.append(nbr)
    return seen


def _tarjan_bridge_candidates(
    nodes: List[str], adj: Dict[str, Set[str]]
) -> List[Tuple[str, str]]:
    """Iterative Tarjan pass on the simple undirected graph.

    Returns tree edges ``(parent, node)`` where ``low[node] > discovery[parent]``.
    In a multigraph these are only candidate bridges: a pair whose multiplicity
    is greater than one keeps a parallel/reverse record after removal, so it is
    filtered out by the caller.
    """
    discovery: Dict[str, int] = {}
    low: Dict[str, int] = {}
    timer = 0
    candidates: List[Tuple[str, str]] = []

    for start in nodes:
        if start in discovery:
            continue
        discovery[start] = low[start] = timer
        timer += 1
        # frame: [node, parent, neighbor iterator]
        stack: List[List[Any]] = [
            [start, None, iter(sorted(adj.get(start, ())))]
        ]
        while stack:
            frame = stack[-1]
            node, parent, it = frame[0], frame[1], frame[2]
            pushed = False
            for nbr in it:
                if nbr == parent:
                    continue
                if nbr not in discovery:
                    discovery[nbr] = low[nbr] = timer
                    timer += 1
                    stack.append([nbr, node, iter(sorted(adj.get(nbr, ())))])
                    pushed = True
                    break
                # back edge
                low[node] = min(low[node], discovery[nbr])
            if pushed:
                continue
            stack.pop()
            if stack:
                parent_node = stack[-1][0]
                low[parent_node] = min(low[parent_node], low[node])
                if low[node] > discovery[parent_node]:
                    candidates.append((parent_node, node))
    # Deterministic, de-duplicated candidate list.
    return sorted(set(candidates))


def compute_bridges(graph: ArchitectureGraph) -> List[BridgeMetric]:
    """Bridge edge records whose removal increases weak component count.

    Multigraph-aware: parallel or reverse-direction records between the same
    node pair mean removing one record leaves the other, so that record is not
    a bridge. Only pairs joined by a single record can be bridges, and Tarjan's
    low-link condition confirms there is no alternate path. Evidence preserves
    the actual edge record orientation (source/target) and the two sorted
    components it joins.
    """
    nodes = _all_node_ids(graph)
    adj, pair_count = _undirected_pair_count(graph)
    candidates = _tarjan_bridge_candidates(nodes, adj)

    result: List[BridgeMetric] = []
    for parent, node in candidates:
        pair = tuple(sorted((parent, node)))
        if pair_count.get(pair, 0) != 1:
            continue  # parallel/reverse records keep the pair connected
        # Locate the single edge record and preserve its actual orientation.
        record: Optional[Dict[str, Any]] = None
        for edge in graph.edges:
            source = str(edge.get("source", "")).strip()
            target = str(edge.get("target", "")).strip()
            if not source or not target or source == target:
                continue
            if tuple(sorted((source, target))) == pair:
                record = edge
                break
        if record is None:
            continue
        source = str(record.get("source", "")).strip()
        target = str(record.get("target", "")).strip()
        blocked = tuple(sorted((source, target)))
        component_a = sorted(_bfs_component_excluding(source, adj, blocked))
        component_b = sorted(_bfs_component_excluding(target, adj, blocked))
        # Preserve the actual original edge record (including source_detail and
        # any other distinguishing attrs) as the bridge's evidence.
        bridge_record = dict(record)
        bridge_record["source"] = source
        bridge_record["target"] = target
        bridge_record.setdefault("edge_type", str(record.get("edge_type", "call")))
        result.append(
            BridgeMetric(
                source=source,
                target=target,
                component_a=component_a,
                component_b=component_b,
                edge=bridge_record,
            )
        )
    result.sort(key=lambda b: (b.source, b.target))
    return result


# ═════════════════════════════════════════════════════════════════════════════
# Combined report
# ═════════════════════════════════════════════════════════════════════════════


@dataclass
class ArchitectureMetricsReport:
    coupling: List[ModuleCoupling] = field(default_factory=list)
    cycles: List[CycleComponent] = field(default_factory=list)
    hubs: List[HubMetric] = field(default_factory=list)
    bridges: List[BridgeMetric] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "coupling": [c.to_dict() for c in self.coupling],
            "cycles": [c.to_dict() for c in self.cycles],
            "hubs": [h.to_dict() for h in self.hubs],
            "bridges": [b.to_dict() for b in self.bridges],
            "metadata": dict(self.metadata),
        }


def compute_architecture_metrics(
    graph: ArchitectureGraph,
    *,
    hub_band: float = HUB_BAND,
    reach_depth: int = REACH_DEPTH,
) -> ArchitectureMetricsReport:
    """Compute all standing structural metrics for ``graph``.

    Advisory only: nothing here gates a build, apply, or simulation verdict.
    Output is deterministic and inspectable (see module docstring).
    """
    nodes = _all_node_ids(graph)
    coupling = compute_coupling(graph)
    cycles = compute_cycles(graph)
    hubs = compute_hubs(graph, hub_band=hub_band, reach_depth=reach_depth)
    bridges = compute_bridges(graph)

    report = ArchitectureMetricsReport(
        coupling=coupling,
        cycles=cycles,
        hubs=hubs,
        bridges=bridges,
        metadata={
            "node_count": len(nodes),
            "edge_count": len(graph.edges),
            "module_count": len({c.module for c in coupling}),
            "cycle_component_count": len(cycles),
            "hub_count": len(hubs),
            "bridge_count": len(bridges),
            "reach_depth": reach_depth,
            "hub_band": hub_band,
        },
    )
    logger.info(
        "Architecture metrics: %s modules, %s cycle components, %s hubs, %s bridges",
        report.metadata["module_count"],
        report.metadata["cycle_component_count"],
        report.metadata["hub_count"],
        report.metadata["bridge_count"],
    )
    return report


def save_report(
    project_root: Path, report: ArchitectureMetricsReport
) -> Path:
    """Persist the metrics report as JSON (advisory output only).

    Written with ``sort_keys=True`` and no timestamps so output is byte-identical
    across builds of an unchanged repository.
    """
    path = project_root / REPORT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report.to_dict(), indent=2, sort_keys=True, ensure_ascii=False)
    path.write_text(payload + "\n", encoding="utf-8")
    logger.info("Saved architecture metrics report -> %s", path)
    return path


def load_report(project_root: Path) -> Optional[ArchitectureMetricsReport]:
    """Load a previously saved metrics report, if present."""
    path = project_root / REPORT_PATH
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return ArchitectureMetricsReport(
        coupling=[
            ModuleCoupling(**item) for item in data.get("coupling", [])
        ],
        cycles=[CycleComponent(**item) for item in data.get("cycles", [])],
        hubs=[HubMetric(**item) for item in data.get("hubs", [])],
        bridges=[BridgeMetric(**item) for item in data.get("bridges", [])],
        metadata=dict(data.get("metadata", {})),
    )
