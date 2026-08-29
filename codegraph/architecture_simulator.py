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


def simulate_change(project_root: Any, node: str, change: str, target: str = "") -> Dict[str, Any]:
    """Simulate a graph mutation without changing source files.

    API requested by phase-II evolution task.
    """
    from codegraph.architecture_graph import ArchitectureGraph
    from codegraph.architecture_scoring import compute_architecture_index
    from codegraph.subsystem_sandbox import build_partition_sandbox

    if not hasattr(project_root, "__truediv__"):
        raise ValueError("project_root must be a Path")

    baseline_score = compute_architecture_index(project_root)
    graph = ArchitectureGraph.load(project_root)

    sandbox = build_partition_sandbox(project_root, graph, node)
    before_metrics = sandbox.get_metrics()

    if change == "add_edge" and target:
        sandbox.subsystem_graph.edges.append({
            "source": node,
            "target": target,
            "edge_type": "call",
            "confidence": "ai_inferred",
            "source_detail": "simulated",
        })
    elif change == "remove_edge" and target:
        sandbox.subsystem_graph.edges = [
            edge for edge in sandbox.subsystem_graph.edges
            if not (str(edge.get("source", "")) == node and str(edge.get("target", "")) == target)
        ]
    elif change == "rewire_edge" and target:
        for edge in sandbox.subsystem_graph.edges:
            if str(edge.get("source", "")) == node:
                edge["target"] = target
                edge["source_detail"] = "simulated_rewire"

    after_metrics = sandbox.get_metrics()
    predicted_score = compute_architecture_index(project_root)

    return {
        "node": node,
        "change": change,
        "target": target,
        "cycle_risk": int(after_metrics.get("cycle_count", 0)) - int(before_metrics.get("cycle_count", 0)),
        "coupling_delta": round(
            predicted_score.dimensions.get("coupling_score", 0.0)
            - baseline_score.dimensions.get("coupling_score", 0.0),
            4,
        ),
        "layer_violations": int(after_metrics.get("layer_violations", 0)),
        "predicted_architecture_score": round(predicted_score.score, 4),
        "baseline_architecture_score": round(baseline_score.score, 4),
        "score_delta": round(predicted_score.score - baseline_score.score, 4),
        "partition": sandbox.subsystem_graph.metadata.get("simulation_partition_id", ""),
        "partition_nodes": sandbox.subsystem_graph.metadata.get("simulation_partition_nodes", 0),
        "partition_boundary_nodes": sandbox.subsystem_graph.metadata.get("simulation_boundary_nodes", 0),
    }


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
