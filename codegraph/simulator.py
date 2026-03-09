"""codegraph.simulator — Suggestion simulation engine.

Simulates proposed changes on the dependency graph before applying
them to real code. Checks for architecture violations, new cycles,
forbidden paths, and coupling increases. Rejects unsafe changes.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from codegraph.index import IndexStore
from codegraph.logging_config import get_logger

logger = get_logger("simulator")


@dataclass
class SimulatedChange:
    """A proposed change to simulate."""

    action: str  # "add_edge", "remove_edge", "add_node", "remove_node"
    source: str = ""
    target: str = ""
    node_id: str = ""
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"action": self.action, "reason": self.reason}
        if self.source:
            d["source"] = self.source
        if self.target:
            d["target"] = self.target
        if self.node_id:
            d["node_id"] = self.node_id
        return d


@dataclass
class SimViolation:
    """A violation detected during simulation."""

    violation_type: str  # "new_cycle", "forbidden_path", "layer_bypass", "coupling_increase"
    severity: str = "error"  # "error", "warning"
    description: str = ""
    affected_nodes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.violation_type,
            "severity": self.severity,
            "description": self.description,
            "affected_nodes": self.affected_nodes[:10],
        }


@dataclass
class SimulationResult:
    """Result of simulating a set of changes."""

    changes: List[SimulatedChange] = field(default_factory=list)
    violations: List[SimViolation] = field(default_factory=list)
    safe: bool = True
    new_cycle_count: int = 0
    coupling_delta: float = 0.0
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "safe": self.safe,
            "changes": [c.to_dict() for c in self.changes],
            "violations": [v.to_dict() for v in self.violations],
            "new_cycle_count": self.new_cycle_count,
            "coupling_delta": round(self.coupling_delta, 4),
            "summary": self.summary,
        }

    def format(self) -> str:
        status = "SAFE" if self.safe else "UNSAFE"
        lines = [f"Simulation: {status}"]
        lines.append(f"  Changes: {len(self.changes)}")
        lines.append(f"  Violations: {len(self.violations)}")
        if self.new_cycle_count:
            lines.append(f"  New cycles: {self.new_cycle_count}")
        if self.violations:
            lines.append("\nViolations:")
            for v in self.violations:
                lines.append(f"  [{v.severity}] {v.description}")
        if self.summary:
            lines.append(f"\n{self.summary}")
        return "\n".join(lines)


def simulate_changes(
    changes: List[SimulatedChange],
    index: IndexStore,
    *,
    check_cycles: bool = True,
    check_forbidden: bool = True,
    forbidden_patterns: Optional[List[Tuple[str, str]]] = None,
) -> SimulationResult:
    """Simulate proposed changes on the dependency graph.

    Builds a virtual copy of the adjacency graph, applies the changes,
    and checks for new violations without modifying real data.

    Args:
        changes: List of proposed changes to simulate.
        check_cycles: Whether to check for newly introduced cycles.
        check_forbidden: Whether to check forbidden path patterns.
        forbidden_patterns: List of (source_pattern, target_pattern) pairs.
    """
    result = SimulationResult(changes=changes)

    # Build current adjacency from index
    conn = index._conn
    adj: Dict[str, Set[str]] = defaultdict(set)
    reverse_adj: Dict[str, Set[str]] = defaultdict(set)
    all_nodes: Set[str] = set()

    for row in conn.execute("SELECT node_id, callee_id FROM callees").fetchall():
        adj[row[0]].add(row[1])
        reverse_adj[row[1]].add(row[0])
        all_nodes.add(row[0])
        all_nodes.add(row[1])

    for row in conn.execute("SELECT node_id FROM nodes").fetchall():
        all_nodes.add(row[0])

    # Snapshot: existing cycles (for comparison)
    existing_cycles = _find_cycles_in_adj(adj) if check_cycles else set()

    # Apply changes to virtual graph
    for change in changes:
        if change.action == "add_edge":
            adj[change.source].add(change.target)
            reverse_adj[change.target].add(change.source)
            all_nodes.add(change.source)
            all_nodes.add(change.target)
        elif change.action == "remove_edge":
            adj[change.source].discard(change.target)
            reverse_adj[change.target].discard(change.source)
        elif change.action == "add_node":
            all_nodes.add(change.node_id)
        elif change.action == "remove_node":
            all_nodes.discard(change.node_id)
            adj.pop(change.node_id, None)
            for targets in adj.values():
                targets.discard(change.node_id)
            reverse_adj.pop(change.node_id, None)
            for sources in reverse_adj.values():
                sources.discard(change.node_id)

    # Check for new cycles
    if check_cycles:
        new_cycles = _find_cycles_in_adj(adj)
        introduced = new_cycles - existing_cycles
        if introduced:
            result.new_cycle_count = len(introduced)
            result.safe = False
            for cycle in list(introduced)[:5]:
                cycle_nodes = list(cycle)
                result.violations.append(SimViolation(
                    violation_type="new_cycle",
                    severity="error",
                    description=f"New cycle introduced: {' -> '.join(cycle_nodes[:4])}...",
                    affected_nodes=cycle_nodes[:10],
                ))

    # Check forbidden paths
    if check_forbidden and forbidden_patterns:
        import fnmatch
        for src_pat, tgt_pat in forbidden_patterns:
            # Check if any added edge creates a forbidden path
            for change in changes:
                if change.action == "add_edge":
                    if (fnmatch.fnmatch(change.source, src_pat) and
                            fnmatch.fnmatch(change.target, tgt_pat)):
                        result.safe = False
                        result.violations.append(SimViolation(
                            violation_type="forbidden_path",
                            severity="error",
                            description=f"Forbidden path: {change.source} -> {change.target} matches {src_pat} -> {tgt_pat}",
                            affected_nodes=[change.source, change.target],
                        ))

    # Check coupling changes
    old_coupling = _compute_module_coupling(
        {k: v for k, v in _original_adj(index).items()})
    new_coupling = _compute_module_coupling(adj)
    result.coupling_delta = new_coupling - old_coupling
    if result.coupling_delta > 0.1:
        result.violations.append(SimViolation(
            violation_type="coupling_increase",
            severity="warning",
            description=f"Coupling increased by {result.coupling_delta:.3f}",
        ))

    # Summary
    if result.safe:
        result.summary = f"All {len(changes)} change(s) are safe to apply"
    else:
        result.summary = f"{len(result.violations)} violation(s) detected — changes rejected"

    return result


def simulate_agent_response(
    response_data: Dict[str, Any],
    index: IndexStore,
    *,
    forbidden_patterns: Optional[List[Tuple[str, str]]] = None,
) -> SimulationResult:
    """Simulate an agent_response.json before applying it.

    Converts repairs to simulated changes and checks for violations.
    """
    changes: List[SimulatedChange] = []

    for repair in response_data.get("repairs", []):
        action = repair.get("action", "")
        node = repair.get("node", "")
        target = repair.get("target", "")

        if action == "connect_call":
            changes.append(SimulatedChange(
                action="add_edge",
                source=node,
                target=target,
                reason=repair.get("reason", ""),
            ))
        elif action == "remove_dead_code":
            changes.append(SimulatedChange(
                action="remove_node",
                node_id=node,
                reason=repair.get("reason", ""),
            ))
        elif action == "add_import":
            changes.append(SimulatedChange(
                action="add_edge",
                source=node,
                target=target,
                reason=repair.get("reason", ""),
            ))

    return simulate_changes(
        changes, index,
        forbidden_patterns=forbidden_patterns,
    )


def _find_cycles_in_adj(adj: Dict[str, Set[str]]) -> Set[frozenset]:
    """Find all non-trivial SCCs in adjacency graph using iterative Tarjan."""
    index_counter = [0]
    stack: List[str] = []
    on_stack: Set[str] = set()
    indices: Dict[str, int] = {}
    lowlinks: Dict[str, int] = {}
    sccs: Set[frozenset] = set()

    all_nodes = set(adj.keys())
    for targets in adj.values():
        all_nodes.update(targets)

    def strongconnect(v: str) -> None:
        work_stack: List[Tuple[str, int, bool]] = [(v, 0, False)]
        while work_stack:
            node, neighbor_idx, returning = work_stack[-1]

            if not returning:
                indices[node] = index_counter[0]
                lowlinks[node] = index_counter[0]
                index_counter[0] += 1
                stack.append(node)
                on_stack.add(node)

            neighbors = sorted(adj.get(node, set()))

            found_unvisited = False
            for i in range(neighbor_idx, len(neighbors)):
                w = neighbors[i]
                if w not in indices:
                    work_stack[-1] = (node, i + 1, True)
                    work_stack.append((w, 0, False))
                    found_unvisited = True
                    break
                elif w in on_stack:
                    lowlinks[node] = min(lowlinks[node], indices[w])

            if not found_unvisited:
                if lowlinks[node] == indices[node]:
                    scc: List[str] = []
                    while True:
                        w = stack.pop()
                        on_stack.discard(w)
                        scc.append(w)
                        if w == node:
                            break
                    if len(scc) > 1:
                        sccs.add(frozenset(scc))

                work_stack.pop()
                if work_stack:
                    parent = work_stack[-1][0]
                    lowlinks[parent] = min(lowlinks[parent], lowlinks[node])

    for node in all_nodes:
        if node not in indices:
            strongconnect(node)

    return sccs


def _original_adj(index: IndexStore) -> Dict[str, Set[str]]:
    """Get the original adjacency from the index."""
    adj: Dict[str, Set[str]] = defaultdict(set)
    conn = index._conn
    for row in conn.execute("SELECT node_id, callee_id FROM callees").fetchall():
        adj[row[0]].add(row[1])
    return adj


def _compute_module_coupling(adj: Dict[str, Set[str]]) -> float:
    """Compute average cross-module coupling from adjacency."""
    cross_module = 0
    total = 0
    for src, targets in adj.items():
        src_mod = src.split("::")[0] if "::" in src else src
        for tgt in targets:
            tgt_mod = tgt.split("::")[0] if "::" in tgt else tgt
            total += 1
            if src_mod != tgt_mod:
                cross_module += 1
    return cross_module / total if total > 0 else 0.0
