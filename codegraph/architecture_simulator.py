"""codegraph.architecture_simulator — Architecture change simulator.

Simulates architecture changes BEFORE implementing them. Predicts
impact on cycles, fan-out, coupling, dependency violations, and
health score without modifying any code.

Unlike the existing simulator.py (which operates on the function-level
call graph), this module operates at the ARCHITECTURE level:

    proposed change → simulate → prediction report → accept/reject

Examples:
  - "Add subsystem trading_engine" → predicts +2 cycles, +15 fan-out
  - "Add edge api → governance" → predicts constraint violation
  - "Split subsystem core_engine" → predicts improved cohesion

The ``structural_effect`` report is documented in ``docs/architecture-metrics.md``.
"""

from __future__ import annotations

import copy
import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from codegraph.arch_schema import (
    ArchComponent,
    ArchConstraint,
    ArchEdge,
    SubsystemDef,
    SystemArchitecture,
)
from codegraph.architecture_metrics import compute_hubs
from codegraph.logging_config import get_logger

logger = get_logger("architecture_simulator")


@dataclass
class GraphMutation:
    node_id: str
    change: str  # add_edge, remove_edge, rewire_edge
    target: str = ""


def _mean_fan(metrics: Dict[str, Any]) -> float:
    """Mean of average fan-in and average fan-out: a simple coupling level."""
    return (float(metrics.get("fan_in_avg", 0.0)) + float(metrics.get("fan_out_avg", 0.0))) / 2.0


_SUPPORTED_CHANGES = ("add_edge", "remove_edge", "rewire_edge")


def _apply_change(sandbox: Any, node: str, change: str, target: str) -> None:
    """Apply one mutation to the sandbox's subsystem graph, in place."""
    if change == "add_edge":
        sandbox.subsystem_graph.edges.append({
            "source": node,
            "target": target,
            "edge_type": "call",
            "confidence": "ai_inferred",
            "source_detail": "simulated",
        })
    elif change == "remove_edge":
        sandbox.subsystem_graph.edges = [
            edge for edge in sandbox.subsystem_graph.edges
            if not (str(edge.get("source", "")) == node and str(edge.get("target", "")) == target)
        ]
    elif change == "rewire_edge":
        for edge in sandbox.subsystem_graph.edges:
            if str(edge.get("source", "")) == node:
                edge["target"] = target
                edge["source_detail"] = "simulated_rewire"


def _verdict(score_delta: float, cycle_delta: int) -> Tuple[str, List[str]]:
    """Map simulated deltas to ACCEPT / REJECT / REVIEW, with the reasons for the decision.

    Only a new cycle is a hard structural rejection. Score drops, coupling
    increases and layer-violation increases are heuristic signals: they are
    reported alongside the verdict but never cause rejection by themselves.
    """
    if cycle_delta > 0:
        return "REJECT", [f"adds {cycle_delta} new cycle(s)"]
    if score_delta > 0:
        return "ACCEPT", [
            f"score improves by {score_delta:.4f}",
            "no new cycles",
            "no new layer violations",
        ]
    return "REVIEW", ["score unchanged"]


def _review(reason: str, changes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Result for a plan that was empty, unsupported, or could not be simulated.

    simulated is False, so a crash or an empty plan can never be read as a neutral verdict.
    """
    return {
        "status": "simulation_unavailable",
        "simulated": False,
        "function_checks_available": False,
        "graph_note": GRAPH_NOTE,
        "changes": changes,
        "verdict": "REVIEW",
        "reasons": [reason],
        "cycle_risk": 0,
        "coupling_delta": 0.0,
        "layer_violations_delta": 0,
        "score_delta": 0.0,
        "policy_findings": [],
        "heuristic_signals": [],
        "structural_effect": [],
        "checks": [
            {
                "name": "architecture-cycle",
                "status": "skipped",
                "reason": "simulation unavailable",
            },
            {
                "name": "function_level_policy_checks",
                "status": "skipped",
                "reason": reason,
            }
        ],
    }


# A limitation, stated wherever a verdict is shown: the score comes from the subsystem graph,
# but the function-level checks run on the function graph. A shared id string is not a shared graph.
GRAPH_NOTE = (
    "the score comes from the subsystem graph; the cycle, layer and constraint checks run on "
    "the function-level graph. Same id, different graph."
)

# Violation types whose inputs are project-derived (the index and system.json), so they may reject.
# Layer violations come from generic DEFAULT_LAYER_RULES and are advisory only.
_BLOCKING_TYPES = frozenset({"new_cycle", "subsystem_constraint", "forbidden_path", "transitive_forbidden"})


def _id_reasons(index_missing: List[str], sandbox_missing: List[str], graph_ids: Set[str]) -> List[str]:
    """Name the ids that do not resolve, and the id space they belong to.

    graph_ids is the full subsystem graph, not the partition: an id can be real in the
    subsystem graph and still lie outside the sandbox partition.
    """
    reasons: List[str] = []
    if index_missing:
        note = ""
        if set(index_missing) & graph_ids:
            note = " (subsystem-graph ids; the function-level index needs function ids)"
        reasons.append(f"ids not in the function-level index: {', '.join(index_missing)}{note}")
    if sandbox_missing:
        reasons.append(f"ids not in the subsystem sandbox: {', '.join(sandbox_missing)}")
    return reasons


def _fuller_checks(
    project_root: Any,
    changes: List[Dict[str, Any]],
    sandbox_ids: Set[str],
    graph_ids: Set[str],
) -> Dict[str, Any]:
    """Run the function-level checks on the plan, as the proof gate does.

    Covers new cycles, forbidden paths, layer rules, subsystem constraints and blast
    radius, via simulator.simulate_changes on the function-level index. The index is
    opened read-only. A rewire_edge cannot be expressed as function-level changes
    without knowing the node's current targets, so such a plan is reported as not checked.

    LIMITATION: this runs on the function-level graph (IndexStore), while the score in
    simulate_changes comes from the subsystem sandbox. Resolving an id on both sides shows
    the string exists in both spaces; it does not make the two graphs the same. A REJECT here
    is a finding about the function-level graph, not about the graph that was scored.

    Gate 1: every id must resolve in the index and in the sandbox before any check runs.
    Gate 2: a violation is blocking only if its type is in _BLOCKING_TYPES; others are advisory.

    Returns {"available", "blocking", "advisory", "reasons", "blast_radius"}.
    """
    from pathlib import Path

    from codegraph.index import IndexStore
    from codegraph.simulator import DEFAULT_LAYER_RULES, SimulatedChange
    from codegraph.simulator import simulate_changes as function_level_simulate

    unavailable: Dict[str, Any] = {
        "available": False, "blocking": False, "advisory": False, "reasons": [], "blast_radius": 0,
    }

    if any(item["change"] == "rewire_edge" for item in changes):
        return {**unavailable, "reasons": ["rewire_edge is not covered by the function-level checks"]}

    function_changes = [
        SimulatedChange(action=item["change"], source=item["node"], target=item["target"], reason="plan")
        for item in changes
    ]
    ids = sorted({value for item in changes for value in (item["node"], item["target"]) if value})
    root = Path(project_root)
    system_path = root / ".codegraph" / "architecture" / "system.json"
    try:
        with IndexStore(root) as index:
            # Gate 1: an unknown id would be invented as a phantom node by the simulator.
            index_missing = [i for i in ids if index.get_node(i) is None]
            sandbox_missing = [i for i in ids if i not in sandbox_ids]
            if index_missing or sandbox_missing:
                return {**unavailable, "reasons": _id_reasons(index_missing, sandbox_missing, graph_ids)}
            result = function_level_simulate(
                function_changes,
                index,
                layer_rules=DEFAULT_LAYER_RULES,
                system_json_path=system_path if system_path.exists() else None,
            )
    except FileNotFoundError as exc:
        return {**unavailable, "reasons": [f"function-level checks unavailable: {exc}"]}
    except Exception as exc:
        logger.warning("Function-level checks failed: %s", exc)
        return {**unavailable, "reasons": [f"function-level checks failed: {type(exc).__name__}: {exc}"]}

    # Gate 2: severity follows the input each violation type is derived from.
    fuller_violations: List[Dict[str, Any]] = []
    reasons: List[str] = []
    blocking = False
    advisory = False
    for v in result.violations:
        violation = {
            "type": v.violation_type,
            "severity": v.severity,
            "description": v.description,
            "affected_nodes": list(v.affected_nodes),
        }
        fuller_violations.append(violation)
        if v.violation_type in _BLOCKING_TYPES:
            blocking = True
            reasons.append(f"REJECT {v.violation_type}: {v.description}")
        else:
            advisory = True
            reasons.append(f"advisory {v.violation_type}: {v.description}")
    reasons.append(f"blast radius: {result.blast_radius} node(s)")
    return {
        "available": True,
        "blocking": blocking,
        "advisory": advisory,
        "reasons": reasons,
        "blast_radius": result.blast_radius,
        "violations": fuller_violations,
    }


def simulate_changes(project_root: Any, changes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Apply a list of graph mutations together in one sandbox and return a verdict.

    Each change is {"change": add_edge | remove_edge | rewire_edge, "node": ..., "target": ...}.
    The sandbox partition is built around the first change's node. Nothing is written
    to the source graph or to disk.

    Scores come only from the sandbox partition. Baseline and predicted are both
    computed by score_from_metrics on the sandbox before and after the mutations,
    so score_delta isolates them. The disk-based inputs of the full architecture
    index (health report, smells, pattern consistency) are not used.
    """
    from codegraph.architecture_graph import ArchitectureGraph
    from codegraph.subsystem_sandbox import build_partition_sandbox, score_from_metrics

    if not hasattr(project_root, "__truediv__"):
        raise ValueError("project_root must be a Path")

    if not changes:
        return _review("empty plan: nothing to simulate", changes)

    for item in changes:
        if item.get("change") not in _SUPPORTED_CHANGES:
            return _review(f"unsupported change: {item.get('change')!r}", changes)
        if not item.get("node"):
            return _review("change has no node", changes)
        if not item.get("target"):
            return _review(f"{item['change']} has no target", changes)

    try:
        graph = ArchitectureGraph.load(project_root)
        graph_ids = {str(n.get("id", "")) for n in graph.nodes}
        sandbox = build_partition_sandbox(project_root, graph, changes[0]["node"])
        before_metrics = sandbox.get_metrics()
        partition_ids = {str(n.get("id", "")) for n in sandbox.subsystem_graph.nodes}
        before_node_records = [dict(node) for node in sandbox._baseline.nodes]
        before_edge_records = [dict(edge) for edge in sandbox._baseline.edges]
        outside_reasons: List[str] = []
        for item in changes:
            for nid in (item["node"], item["target"]):
                reason = f"{item['change']} references {nid}, which is outside the sandbox partition"
                if str(nid) not in partition_ids and reason not in outside_reasons:
                    outside_reasons.append(reason)
        for item in changes:
            _apply_change(sandbox, item["node"], item["change"], item["target"])
        after_metrics = sandbox.get_metrics()
        after_node_records = [dict(node) for node in sandbox.subsystem_graph.nodes]
        after_edge_records = [dict(edge) for edge in sandbox.subsystem_graph.edges]
    except Exception as exc:
        logger.warning("Architecture simulation failed: %s", exc)
        return _review(f"could not simulate: {type(exc).__name__}: {exc}", changes)

    baseline_subsystem = score_from_metrics(before_metrics)
    predicted_subsystem = score_from_metrics(after_metrics)
    score_delta = round(predicted_subsystem - baseline_subsystem, 4)
    cycle_delta = int(after_metrics.get("cycle_count", 0)) - int(before_metrics.get("cycle_count", 0))
    layer_delta = int(after_metrics.get("layer_violations", 0)) - int(before_metrics.get("layer_violations", 0))
    coupling_delta = round(_mean_fan(after_metrics) - _mean_fan(before_metrics), 4)
    fuller = _fuller_checks(project_root, changes, partition_ids, graph_ids)

    before_edge_set = {
        (str(edge.get("source", "")), str(edge.get("target", ""))) for edge in before_edge_records
    }
    after_edge_set = {
        (str(edge.get("source", "")), str(edge.get("target", ""))) for edge in after_edge_records
    }

    # Reachability on the predicted (after) graph, used to name the edges that
    # create a cycle and to compute the transitively affected node set.
    adjacency_after: Dict[str, List[str]] = {}
    for edge in after_edge_records:
        adjacency_after.setdefault(str(edge.get("source", "")), []).append(str(edge.get("target", "")))

    def _reachable_from(start: str) -> Set[str]:
        seen: Set[str] = set()
        stack = [start]
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            stack.extend(adjacency_after.get(node, []))
        return seen

    cycle_created_edges: List[Tuple[str, str]] = []
    for source, target in sorted(after_edge_set - before_edge_set):
        if source in _reachable_from(target):
            cycle_created_edges.append((source, target))

    # Hard policy findings name the rule and may block. Heuristic signals
    # (score drops, coupling increases, layer-violation increases) inform the
    # decision and may never cause rejection by themselves.
    policy_findings: List[Dict[str, Any]] = [
        {
            "kind": "policy",
            "rule": v["type"],
            "description": v["description"],
            "details": {
                "severity": v.get("severity", ""),
                "affected_nodes": v.get("affected_nodes", []),
            },
        }
        for v in fuller.get("violations", [])
        if v["type"] in _BLOCKING_TYPES
    ]
    # An architectural cycle created by the change is a hard policy finding
    # named new_cycle, reported even when the function-level checks could not run.
    for source, target in cycle_created_edges:
        policy_findings.append({
            "kind": "policy",
            "rule": "new_cycle",
            "description": f"new cycle via {source} -> {target}",
            "details": {"severity": "error", "affected_nodes": [source, target]},
        })
    if cycle_delta > 0 and not cycle_created_edges:
        policy_findings.append({
            "kind": "policy",
            "rule": "new_cycle",
            "description": "the change deepens an existing cycle",
            "details": {"severity": "error", "affected_nodes": sorted(
                {value for item in changes for value in (item.get("node", ""), item.get("target", "")) if value}
            )},
        })
    heuristic_signals: List[Dict[str, Any]] = []
    if score_delta < 0:
        heuristic_signals.append({
            "kind": "heuristic",
            "signal": "score_drop",
            "description": f"architecture score drops by {abs(score_delta):.4f}",
            "delta": score_delta,
        })
    if coupling_delta > 0:
        heuristic_signals.append({
            "kind": "heuristic",
            "signal": "coupling_increase",
            "description": f"mean fan-in/fan-out rises by {coupling_delta:.4f}",
            "delta": coupling_delta,
        })
    if layer_delta > 0:
        heuristic_signals.append({
            "kind": "heuristic",
            "signal": "layer_violation_increase",
            "description": f"layer violations rise by {layer_delta}",
            "delta": float(layer_delta),
        })

    verdict, base_reasons = _verdict(score_delta, cycle_delta)
    review_notes: List[str] = []
    if outside_reasons:
        # A score over nodes outside the partition does not describe the plan.
        review_notes.append("the score is not meaningful when changes fall outside the partition")
    if not fuller["available"]:
        review_notes.append("the function-level checks did not run")
    if fuller["advisory"]:
        review_notes.append("generic advisory checks flagged the plan (layer rules are not project-specific)")
    if fuller["blocking"]:
        verdict = "REJECT"
    elif verdict != "REJECT" and review_notes:
        # A REJECT is never softened to REVIEW; only an ACCEPT is held back.
        verdict = "REVIEW"
        base_reasons = [f"REVIEW: {note}" for note in review_notes] + base_reasons
    reasons = outside_reasons + fuller["reasons"] + base_reasons

    # The architecture-cycle check is computed on the sandbox, which ran whenever
    # we reach this point, so it is reported even when the function-level checks
    # could not run. The function-level check follows its own availability.
    checks: List[Dict[str, Any]] = [
        {
            "name": "architecture-cycle",
            "status": "failed" if cycle_delta > 0 else "passed",
        }
    ]
    if fuller["available"]:
        checks.append({
            "name": "function_level_policy_checks",
            "status": "failed" if fuller["blocking"] else "passed",
        })
    else:
        skip_reason = "; ".join(fuller["reasons"]) or "function-level checks could not run"
        checks.append({
            "name": "function_level_policy_checks",
            "status": "skipped",
            "reason": skip_reason,
        })

    # Hub evidence from the production compute_hubs() definition, before/after.
    before_graph = ArchitectureGraph(nodes=before_node_records, edges=before_edge_records)
    after_graph = ArchitectureGraph(nodes=after_node_records, edges=after_edge_records)
    before_hubs = {hub.node_id: hub for hub in compute_hubs(before_graph)}
    after_hubs = {hub.node_id: hub for hub in compute_hubs(after_graph)}

    structural_effect = _structural_effect(
        changes,
        before_edge_records,
        after_edge_records,
        partition_ids,
        cycle_delta,
        cycle_created_edges=cycle_created_edges,
        before_hubs=before_hubs,
        after_hubs=after_hubs,
    )

    return {
        "status": "simulated" if fuller["available"] else "partially_simulated",
        "simulated": fuller["available"],
        "function_checks_available": fuller["available"],
        "graph_note": GRAPH_NOTE,
        "partition_limited": bool(outside_reasons),
        "changes": changes,
        "verdict": verdict,
        "reasons": reasons,
        "policy_findings": policy_findings,
        "heuristic_signals": heuristic_signals,
        "structural_effect": structural_effect,
        "checks": checks,
        "cycle_risk": cycle_delta,
        "coupling_delta": coupling_delta,
        "layer_violations": int(after_metrics.get("layer_violations", 0)),
        "layer_violations_delta": layer_delta,
        "predicted_subsystem_score": round(predicted_subsystem, 4),
        "baseline_subsystem_score": round(baseline_subsystem, 4),
        "score_delta": score_delta,
        "partition": sandbox.subsystem_graph.metadata.get("simulation_partition_id", ""),
        "partition_nodes": sandbox.subsystem_graph.metadata.get("simulation_partition_nodes", 0),
        "partition_boundary_nodes": sandbox.subsystem_graph.metadata.get("simulation_boundary_nodes", 0),
    }


def _weak_components(node_ids: Set[str], edges: Iterable[Tuple[str, str]]) -> List[Set[str]]:
    """Undirected connected components; membership and order are deterministic."""
    adjacency: Dict[str, Set[str]] = {nid: set() for nid in node_ids}
    for source, target in edges:
        if source in adjacency and target in adjacency:
            adjacency[source].add(target)
            adjacency[target].add(source)
    seen: Set[str] = set()
    components: List[Set[str]] = []
    for start in sorted(node_ids):
        if start in seen:
            continue
        stack = [start]
        component: Set[str] = set()
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            component.add(node)
            stack.extend(sorted(adjacency[node] - seen))
        components.append(component)
    return components


def _edge_key(edge: Dict[str, Any]) -> str:
    """Canonical key for an edge record over its full contents.

    Parallel or reverse records with the same endpoints but different
    attributes (e.g. source_detail) stay distinct by full-record multiplicity,
    so the diff reports the actual changed record rather than pairing by
    endpoints alone. Keys are deterministic (sorted keys, stable separators)
    and fall back to stringifying any non-JSON-serializable value.
    """

    def _clean(value: Any) -> Any:
        if isinstance(value, dict):
            return {str(k): _clean(v) for k, v in sorted(value.items())}
        if isinstance(value, (list, tuple, set)):
            return [_clean(v) for v in value]
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        return str(value)

    try:
        return json.dumps(_clean(edge), sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return json.dumps(
            _clean({str(k): str(v) for k, v in edge.items()}),
            sort_keys=True,
            separators=(",", ":"),
        )


def _edge_pair(edge: Dict[str, Any]) -> Tuple[str, str]:
    return (str(edge.get("source", "")).strip(), str(edge.get("target", "")).strip())


def _hub_evidence(hub: Any) -> Dict[str, Any]:
    return {
        "node_id": hub.node_id,
        "score": round(float(hub.score), 6),
        "in_degree": hub.in_degree,
        "out_degree": hub.out_degree,
        "reach": hub.reach,
        "callers": list(hub.callers),
    }


def _structural_effect(
    changes: List[Dict[str, Any]],
    before_edge_records: List[Dict[str, Any]],
    after_edge_records: List[Dict[str, Any]],
    partition_ids: Set[str],
    cycle_delta: int,
    *,
    cycle_created_edges: Optional[List[Tuple[str, str]]] = None,
    before_hubs: Optional[Dict[str, Any]] = None,
    after_hubs: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Describe what the change does to the structure of the predicted graph.

    Every consequence is deterministic for a fixed predicted graph and carries
    the node and edge ids that produced it. The edge diff is multigraph-aware:
    parallel edge records are distinguished by multiplicity, so adding or
    removing one of several parallel records is still reported. Consequences
    describe the change; they never influence the verdict.
    """
    before_counts = Counter(_edge_key(edge) for edge in before_edge_records)
    after_counts = Counter(_edge_key(edge) for edge in after_edge_records)

    # Multigraph-aware diff: preserve full edge records as evidence and keep
    # parallel records distinct by their multiplicity.
    added: List[Dict[str, Any]] = []
    after_remaining = dict(after_counts)
    for edge in after_edge_records:
        key = _edge_key(edge)
        if after_remaining.get(key, 0) > before_counts.get(key, 0):
            added.append(dict(edge))
            after_remaining[key] = after_remaining.get(key, 0) - 1
    removed: List[Dict[str, Any]] = []
    before_remaining = dict(before_counts)
    for edge in before_edge_records:
        key = _edge_key(edge)
        if before_remaining.get(key, 0) > after_counts.get(key, 0):
            removed.append(dict(edge))
            before_remaining[key] = before_remaining.get(key, 0) - 1
    added.sort(key=_edge_key)
    removed.sort(key=_edge_key)

    added_pairs = [_edge_pair(edge) for edge in added]
    removed_pairs = [_edge_pair(edge) for edge in removed]

    adjacency: Dict[str, List[str]] = {}
    for edge in after_edge_records:
        adjacency.setdefault(_edge_pair(edge)[0], []).append(_edge_pair(edge)[1])

    def reachable_from(start: str) -> Set[str]:
        seen: Set[str] = set()
        stack = [start]
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            stack.extend(adjacency.get(node, []))
        return seen

    touched = sorted(
        {value for item in changes for value in (item.get("node", ""), item.get("target", "")) if value}
    )
    affected_set: Set[str] = set()
    for node in touched:
        affected_set |= reachable_from(node)
    affected = sorted(affected_set)

    if cycle_created_edges is None:
        cycle_created_edges = [
            (source, target)
            for source, target in added_pairs
            if source in reachable_from(target)
        ]

    consequences: List[Dict[str, Any]] = []

    for edge in added:
        source, target = _edge_pair(edge)
        consequences.append({
            "kind": "connection_added",
            "description": f"new connection {source} -> {target}",
            "nodes": [source, target],
            "edges": [edge],
        })
    for edge in removed:
        source, target = _edge_pair(edge)
        consequences.append({
            "kind": "connection_removed",
            "description": f"connection removed {source} -> {target}",
            "nodes": [source, target],
            "edges": [edge],
        })

    for source, target in cycle_created_edges:
        consequences.append({
            "kind": "cycle_created",
            "description": f"new cycle via {source} -> {target}",
            "nodes": [source, target],
            "edges": [{"source": source, "target": target}],
        })
    if cycle_delta > 0 and not cycle_created_edges:
        consequences.append({
            "kind": "cycle_extended",
            "description": "the change deepens an existing cycle",
            "nodes": touched,
            "edges": [
                {"source": item.get("node", ""), "target": item.get("target", "")}
                for item in changes
                if item.get("change") == "add_edge"
            ],
        })

    for edge in added:
        source, target = _edge_pair(edge)
        if (source in partition_ids) != (target in partition_ids):
            consequences.append({
                "kind": "boundary_crossed",
                "description": f"new connection crosses the sandbox boundary: {source} -> {target}",
                "nodes": [source, target],
                "edges": [edge],
            })

    internal_before = [
        edge for edge in before_edge_records
        if _edge_pair(edge)[0] in partition_ids and _edge_pair(edge)[1] in partition_ids
    ]
    component_of: Dict[str, int] = {}
    for index, component in enumerate(_weak_components(set(partition_ids), [_edge_pair(e) for e in internal_before])):
        for node in component:
            component_of[node] = index
    for edge in added:
        source, target = _edge_pair(edge)
        if source in partition_ids and target in partition_ids:
            source_component = component_of.get(source)
            target_component = component_of.get(target)
            if source_component is not None and target_component is not None and source_component != target_component:
                consequences.append({
                    "kind": "region_newly_connected",
                    "description": f"regions newly connected: {source} -> {target}",
                    "nodes": [source, target],
                    "edges": [edge],
                })

    before_hubs = before_hubs or {}
    after_hubs = after_hubs or {}
    for node in touched:
        hub = after_hubs.get(node) or before_hubs.get(node)
        if hub is None:
            continue
        consequences.append({
            "kind": "hub_touched",
            "description": (
                f"hub touched: {node} (score {hub.score:.6f}, callers {', '.join(hub.callers)})"
            ),
            "nodes": [node],
            "edges": [{"source": caller, "target": node} for caller in hub.callers],
            "evidence": {
                "before": _hub_evidence(before_hubs[node]) if node in before_hubs else None,
                "after": _hub_evidence(after_hubs[node]) if node in after_hubs else None,
            },
        })

    if affected:
        consequences.append({
            "kind": "affected_nodes",
            "description": f"{len(affected)} node(s) transitively affected by the change",
            "nodes": affected,
        })

    return consequences


def revise_rejected_changes(
    project_root: Any, changes: List[Dict[str, Any]], *, max_rounds: int = 3,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    """Drop the changes the simulation gate rejects and keep the rest (#37).

    Attribution is done by re-simulation, never by parsing reason text: each
    change is simulated on its own.  A REJECT that no single change reproduces
    is a combination failure and is left in place — cutting a specific edge
    would be a guess.  The returned result carries ``unattributed_reject``
    when that happens, so a caller can surface it instead of proceeding.

    Returns ``(remaining_changes, dropped, final_result)``.
    """
    remaining = [dict(change) for change in changes]
    dropped: List[Dict[str, Any]] = []
    result = simulate_changes(project_root, remaining)

    for _ in range(max_rounds):
        if result.get("verdict") != "REJECT" or not remaining:
            break
        offenders: List[Tuple[Dict[str, Any], List[str]]] = []
        for change in remaining:
            single = simulate_changes(project_root, [change])
            if single.get("verdict") == "REJECT":
                offenders.append((change, list(single.get("reasons", []))))
        if not offenders:
            result = {**result, "unattributed_reject": True}
            break
        for change, reasons in offenders:
            dropped.append({"change": change, "reasons": reasons})
            remaining.remove(change)
        result = simulate_changes(project_root, remaining)

    return remaining, dropped, result


def simulate_change(project_root: Any, node: str, change: str, target: str = "") -> Dict[str, Any]:
    """Single-mutation form of simulate_changes, kept for existing callers."""
    result = simulate_changes(project_root, [{"change": change, "node": node, "target": target}])
    result.update({"node": node, "change": change, "target": target})
    return result


# ── Simulated Architecture Change ──────────────────────────────────────


@dataclass
class ArchChange:
    """A proposed architecture change to simulate."""

    action: str  # "add_subsystem", "add_edge", "remove_edge",
    #              "add_component", "add_constraint",
    #              "split_subsystem", "merge_subsystems"
    subsystem: str = ""
    target_subsystem: str = ""
    component_name: str = ""
    module_path: str = ""
    constraint_type: str = ""
    reason: str = ""
    # For splits: list of components to move
    components: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"action": self.action}
        for attr in ("subsystem", "target_subsystem", "component_name",
                      "module_path", "constraint_type", "reason"):
            val = getattr(self, attr)
            if val:
                d[attr] = val
        if self.components:
            d["components"] = self.components
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> ArchChange:
        return cls(
            action=d["action"],
            subsystem=d.get("subsystem", ""),
            target_subsystem=d.get("target_subsystem", ""),
            component_name=d.get("component_name", ""),
            module_path=d.get("module_path", ""),
            constraint_type=d.get("constraint_type", ""),
            reason=d.get("reason", ""),
            components=d.get("components", []),
        )


# ── Prediction ─────────────────────────────────────────────────────────


@dataclass
class ArchPrediction:
    """A predicted impact of a simulated change."""

    metric: str  # "cycles", "fan_out", "coupling", "constraint_violation",
    #              "subsystem_count", "cohesion", "health_score"
    current_value: float = 0.0
    predicted_value: float = 0.0
    delta: float = 0.0
    severity: str = "info"  # "info", "warning", "error"
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metric": self.metric,
            "current": self.current_value,
            "predicted": self.predicted_value,
            "delta": round(self.delta, 3),
            "severity": self.severity,
            "description": self.description,
        }


# ── Simulation Result ──────────────────────────────────────────────────


@dataclass
class ArchSimulationResult:
    """Result of simulating architecture changes."""

    changes: List[ArchChange] = field(default_factory=list)
    predictions: List[ArchPrediction] = field(default_factory=list)
    safe: bool = True
    recommendation: str = "accept"  # "accept", "review", "reject"
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "safe": self.safe,
            "recommendation": self.recommendation,
            "changes": [c.to_dict() for c in self.changes],
            "predictions": [p.to_dict() for p in self.predictions],
            "reasons": self.reasons,
        }

    def format(self) -> str:
        status = "SAFE" if self.safe else "UNSAFE"
        lines = [f"Architecture Simulation: {status}"]
        lines.append(f"  Recommendation: {self.recommendation}")
        lines.append(f"  Changes: {len(self.changes)}")
        lines.append(f"  Predictions: {len(self.predictions)}")
        if self.predictions:
            lines.append("\nPredicted Impact:")
            for p in self.predictions:
                sign = "+" if p.delta > 0 else ""
                lines.append(
                    f"  [{p.severity}] {p.metric}: "
                    f"{p.current_value} → {p.predicted_value} "
                    f"({sign}{p.delta:.1f})"
                )
                if p.description:
                    lines.append(f"         {p.description}")
        if self.reasons:
            lines.append("\nReasons:")
            for r in self.reasons:
                lines.append(f"  • {r}")
        return "\n".join(lines)


# ── Simulation Engine ──────────────────────────────────────────────────


def simulate_architecture_changes(
    changes: List[ArchChange],
    architecture: SystemArchitecture,
) -> ArchSimulationResult:
    """Simulate architecture changes and predict their impact.

    Creates a deep copy of the architecture, applies changes, and
    compares metrics before and after to produce predictions.
    """
    result = ArchSimulationResult(changes=changes)

    # Snapshot current metrics
    before = _compute_arch_metrics(architecture)

    # Deep copy and apply changes
    simulated = copy.deepcopy(architecture)
    violations = _apply_changes(simulated, changes)

    # Compute metrics after changes
    after = _compute_arch_metrics(simulated)

    # Generate predictions by comparing metrics
    _generate_predictions(result, before, after)

    # Check constraint violations
    if violations:
        for v in violations:
            result.predictions.append(ArchPrediction(
                metric="constraint_violation",
                severity="error",
                description=v,
            ))

    # Check for new constraints violated
    constraint_violations = _check_constraints(simulated)
    for cv in constraint_violations:
        result.predictions.append(ArchPrediction(
            metric="constraint_violation",
            severity="error",
            description=cv,
        ))

    # Determine recommendation
    _determine_recommendation(result)

    return result


def simulate_subsystem_addition(
    subsystem_name: str,
    dependencies: List[str],
    architecture: SystemArchitecture,
) -> ArchSimulationResult:
    """Simulate adding a new subsystem with given dependencies."""
    changes = [ArchChange(
        action="add_subsystem",
        subsystem=subsystem_name,
        reason=f"Add subsystem {subsystem_name}",
    )]
    for dep in dependencies:
        changes.append(ArchChange(
            action="add_edge",
            subsystem=subsystem_name,
            target_subsystem=dep,
            reason=f"{subsystem_name} → {dep}",
        ))
    return simulate_architecture_changes(changes, architecture)


# ── Metrics Computation ───────────────────────────────────────────────


def _compute_arch_metrics(
    arch: SystemArchitecture,
) -> Dict[str, float]:
    """Compute architecture-level metrics."""
    metrics: Dict[str, float] = {}

    metrics["subsystem_count"] = len(arch.subsystems)
    metrics["edge_count"] = len(arch.edges)
    metrics["constraint_count"] = len(arch.constraints)

    # Total components
    total_components = sum(len(s.components) for s in arch.subsystems)
    metrics["component_count"] = total_components

    # Max fan-out (subsystem level)
    fan_out: Dict[str, int] = {}
    for edge in arch.edges:
        fan_out[edge.source] = fan_out.get(edge.source, 0) + 1
    metrics["max_fan_out"] = max(fan_out.values()) if fan_out else 0

    # Max fan-in
    fan_in: Dict[str, int] = {}
    for edge in arch.edges:
        fan_in[edge.target] = fan_in.get(edge.target, 0) + 1
    metrics["max_fan_in"] = max(fan_in.values()) if fan_in else 0

    # Cycle count (subsystem level)
    adj: Dict[str, Set[str]] = {}
    for edge in arch.edges:
        adj.setdefault(edge.source, set()).add(edge.target)
    metrics["cycles"] = _count_subsystem_cycles(adj)

    # Average coupling (edges per subsystem pair possible)
    n = len(arch.subsystems)
    max_edges = n * (n - 1) if n > 1 else 1
    metrics["coupling"] = len(arch.edges) / max_edges if max_edges > 0 else 0

    # Cohesion (internal edges per subsystem)
    internal_edges = sum(len(s.edges) for s in arch.subsystems)
    metrics["internal_edges"] = internal_edges

    return metrics


def _count_subsystem_cycles(adj: Dict[str, Set[str]]) -> int:
    """Count cycles in subsystem dependency graph using Tarjan."""
    index_counter = [0]
    stack: List[str] = []
    on_stack: Set[str] = set()
    indices: Dict[str, int] = {}
    lowlinks: Dict[str, int] = {}
    cycle_count = 0

    all_nodes = set(adj.keys())
    for targets in adj.values():
        all_nodes.update(targets)

    def strongconnect(v: str) -> None:
        nonlocal cycle_count
        indices[v] = index_counter[0]
        lowlinks[v] = index_counter[0]
        index_counter[0] += 1
        stack.append(v)
        on_stack.add(v)

        for w in sorted(adj.get(v, set())):
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
                cycle_count += 1

    for node in sorted(all_nodes):
        if node not in indices:
            strongconnect(node)

    return cycle_count


# ── Change Application ─────────────────────────────────────────────────


def _apply_changes(
    arch: SystemArchitecture,
    changes: List[ArchChange],
) -> List[str]:
    """Apply changes to a simulated architecture. Returns violations."""
    violations: List[str] = []

    for change in changes:
        if change.action == "add_subsystem":
            if not arch.get_subsystem(change.subsystem):
                arch.subsystems.append(SubsystemDef(
                    name=change.subsystem,
                    description=change.reason,
                ))

        elif change.action == "remove_subsystem":
            arch.subsystems = [s for s in arch.subsystems
                               if s.name != change.subsystem]

        elif change.action == "add_edge":
            src = change.subsystem
            tgt = change.target_subsystem
            # Check if this would violate a constraint
            for c in arch.constraints:
                if (c.constraint_type == "forbidden"
                        and c.source == src and c.target == tgt):
                    violations.append(
                        f"Edge {src} → {tgt} violates constraint: {c.reason}"
                    )
            existing = {(e.source, e.target) for e in arch.edges}
            if (src, tgt) not in existing:
                arch.edges.append(ArchEdge(source=src, target=tgt))

        elif change.action == "remove_edge":
            arch.edges = [
                e for e in arch.edges
                if not (e.source == change.subsystem
                        and e.target == change.target_subsystem)
            ]

        elif change.action == "add_component":
            sub = arch.get_subsystem(change.subsystem)
            if sub:
                existing = {c.name for c in sub.components}
                if change.component_name not in existing:
                    sub.components.append(ArchComponent(
                        name=change.component_name,
                        module=change.module_path,
                    ))

        elif change.action == "remove_component":
            sub = arch.get_subsystem(change.subsystem)
            if sub:
                name = change.component_name
                mod = change.module_path
                sub.components = [c for c in sub.components
                                  if not (c.name == name or (mod and c.module == mod))]

        elif change.action == "add_constraint":
            arch.constraints.append(ArchConstraint(
                constraint_type=change.constraint_type,
                source=change.subsystem,
                target=change.target_subsystem,
                reason=change.reason,
            ))

        elif change.action == "remove_constraint":
            src = change.subsystem
            tgt = change.target_subsystem
            ct = change.constraint_type
            arch.constraints = [c for c in arch.constraints
                                if not (c.constraint_type == ct
                                        and c.source == src and c.target == tgt)]

        elif change.action == "split_subsystem":
            # Simulate splitting a subsystem
            src_sub = arch.get_subsystem(change.subsystem)
            if src_sub:
                new_sub = SubsystemDef(
                    name=change.target_subsystem,
                    description=f"Split from {change.subsystem}",
                )
                move_set = set(change.components)
                to_move = [c for c in src_sub.components
                           if c.name in move_set]
                src_sub.components = [c for c in src_sub.components
                                      if c.name not in move_set]
                new_sub.components = to_move
                arch.subsystems.append(new_sub)

        elif change.action == "merge_subsystems":
            sub_a = arch.get_subsystem(change.subsystem)
            sub_b = arch.get_subsystem(change.target_subsystem)
            if sub_a and sub_b:
                sub_a.components.extend(sub_b.components)
                arch.subsystems = [
                    s for s in arch.subsystems
                    if s.name != change.target_subsystem
                ]
                # Update edges referencing the merged subsystem
                for edge in arch.edges:
                    if edge.source == change.target_subsystem:
                        edge.source = change.subsystem
                    if edge.target == change.target_subsystem:
                        edge.target = change.subsystem
                # Remove self-edges
                arch.edges = [e for e in arch.edges
                              if e.source != e.target]

    return violations


def _check_constraints(arch: SystemArchitecture) -> List[str]:
    """Check if current edges violate any constraints."""
    violations: List[str] = []
    for c in arch.constraints:
        if c.constraint_type == "forbidden":
            for edge in arch.edges:
                if edge.source == c.source and edge.target == c.target:
                    violations.append(
                        f"Edge {edge.source} → {edge.target} "
                        f"violates forbidden constraint: {c.reason}"
                    )
    return violations


# ── Prediction Generation ──────────────────────────────────────────────


def _generate_predictions(
    result: ArchSimulationResult,
    before: Dict[str, float],
    after: Dict[str, float],
) -> None:
    """Compare before/after metrics and generate predictions."""
    metric_configs = [
        ("subsystem_count", "warning", 10, "Many subsystems increase complexity"),
        ("cycles", "error", 0, "Cycles break dependency order"),
        ("max_fan_out", "warning", 5, "High fan-out indicates poor encapsulation"),
        ("max_fan_in", "warning", 5, "High fan-in creates critical bottlenecks"),
        ("coupling", "warning", 0.5, "High coupling reduces modularity"),
    ]

    for metric, severity, threshold, desc in metric_configs:
        cur = before.get(metric, 0)
        pred = after.get(metric, 0)
        delta = pred - cur

        if abs(delta) < 0.001:
            continue

        # Determine actual severity based on direction
        actual_severity = "info"
        if metric == "cycles" and delta > 0:
            actual_severity = "error"
        elif metric in ("max_fan_out", "max_fan_in", "coupling") and delta > 0:
            actual_severity = "warning"
        elif metric in ("max_fan_out", "max_fan_in", "coupling") and delta < 0:
            actual_severity = "info"  # improvement

        result.predictions.append(ArchPrediction(
            metric=metric,
            current_value=cur,
            predicted_value=pred,
            delta=delta,
            severity=actual_severity,
            description=desc if delta > 0 else f"Improvement: {desc.lower()}",
        ))


def _determine_recommendation(result: ArchSimulationResult) -> None:
    """Determine accept/review/reject based on predictions."""
    errors = sum(1 for p in result.predictions if p.severity == "error")
    warnings = sum(1 for p in result.predictions if p.severity == "warning")

    if errors >= 2:
        result.safe = False
        result.recommendation = "reject"
        result.reasons.append(f"{errors} error-level predictions")
    elif errors >= 1:
        result.safe = False
        result.recommendation = "review"
        result.reasons.append(f"{errors} error-level prediction(s) need review")
    elif warnings >= 3:
        result.recommendation = "review"
        result.reasons.append(f"{warnings} warnings suggest caution")
    else:
        result.recommendation = "accept"
        result.reasons.append("No significant issues predicted")


# ── ArchitectureChange boundary ─────────────────────────────────────────

def simulate(
    change: "ArchitectureChange",
    architecture: SystemArchitecture,
) -> ArchSimulationResult:
    """Simulate a canonical ArchitectureChange using the existing engine.

    Single public boundary: validate the IR, convert it ONCE to the legacy
    ArchChange list via the reverse adapter, then run the existing
    simulate_architecture_changes. The IR is description-only; the simulator
    deep-copies the architecture, so persistent state is never mutated here.
    """
    from codegraph.architecture_change_adapters import architecture_change_to_arch_changes

    change.validate()
    arch_changes = architecture_change_to_arch_changes(change, architecture)
    return simulate_architecture_changes(arch_changes, architecture)
