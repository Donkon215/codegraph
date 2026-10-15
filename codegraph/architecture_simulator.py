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
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from codegraph.arch_schema import (
    ArchComponent,
    ArchConstraint,
    ArchEdge,
    SubsystemDef,
    SystemArchitecture,
)
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


def _verdict(score_delta: float, cycle_delta: int, layer_delta: int) -> Tuple[str, List[str]]:
    """Map simulated deltas to ACCEPT / REJECT / REVIEW, with the reasons for the decision."""
    reject_reasons: List[str] = []
    if cycle_delta > 0:
        reject_reasons.append(f"adds {cycle_delta} new cycle(s)")
    if layer_delta > 0:
        reject_reasons.append(f"increases layer violations by {layer_delta}")
    if score_delta < 0:
        reject_reasons.append(f"score drops by {abs(score_delta):.4f}")
    if reject_reasons:
        return "REJECT", reject_reasons
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
        "graph_note": GRAPH_NOTE,
        "changes": changes,
        "verdict": "REVIEW",
        "reasons": [reason],
        "cycle_risk": 0,
        "coupling_delta": 0.0,
        "layer_violations_delta": 0,
        "score_delta": 0.0,
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
    reasons: List[str] = []
    blocking = False
    advisory = False
    for v in result.violations:
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
        outside_reasons: List[str] = []
        for item in changes:
            for nid in (item["node"], item["target"]):
                reason = f"{item['change']} references {nid}, which is outside the sandbox partition"
                if str(nid) not in partition_ids and reason not in outside_reasons:
                    outside_reasons.append(reason)
        for item in changes:
            _apply_change(sandbox, item["node"], item["change"], item["target"])
        after_metrics = sandbox.get_metrics()
    except Exception as exc:
        logger.warning("Architecture simulation failed: %s", exc)
        return _review(f"could not simulate: {type(exc).__name__}: {exc}", changes)

    baseline_subsystem = score_from_metrics(before_metrics)
    predicted_subsystem = score_from_metrics(after_metrics)
    score_delta = round(predicted_subsystem - baseline_subsystem, 4)
    cycle_delta = int(after_metrics.get("cycle_count", 0)) - int(before_metrics.get("cycle_count", 0))
    layer_delta = int(after_metrics.get("layer_violations", 0)) - int(before_metrics.get("layer_violations", 0))
    fuller = _fuller_checks(project_root, changes, partition_ids, graph_ids)
    verdict, reasons = _verdict(score_delta, cycle_delta, layer_delta)
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
        reasons = [f"REVIEW: {note}" for note in review_notes] + reasons
    reasons = outside_reasons + fuller["reasons"] + reasons

    return {
        "status": "simulated" if fuller["available"] else "partially_simulated",
        "simulated": fuller["available"],
        "function_checks_available": fuller["available"],
        "graph_note": GRAPH_NOTE,
        "partition_limited": bool(outside_reasons),
        "changes": changes,
        "verdict": verdict,
        "reasons": reasons,
        "cycle_risk": cycle_delta,
        # Positive means coupling went up (reactive_server warns above 0.05).
        "coupling_delta": round(_mean_fan(after_metrics) - _mean_fan(before_metrics), 4),
        "layer_violations": int(after_metrics.get("layer_violations", 0)),
        "layer_violations_delta": layer_delta,
        "predicted_subsystem_score": round(predicted_subsystem, 4),
        "baseline_subsystem_score": round(baseline_subsystem, 4),
        "score_delta": score_delta,
        "partition": sandbox.subsystem_graph.metadata.get("simulation_partition_id", ""),
        "partition_nodes": sandbox.subsystem_graph.metadata.get("simulation_partition_nodes", 0),
        "partition_boundary_nodes": sandbox.subsystem_graph.metadata.get("simulation_boundary_nodes", 0),
    }


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
