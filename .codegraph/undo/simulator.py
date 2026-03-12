"""codegraph.simulator — Architecture simulation engine.

Simulates proposed changes on the dependency graph before applying
them to real code. Checks for:
  - New cycles (Tarjan SCC)
  - Forbidden path violations
  - Layer violations (e.g., UI → database)
  - Subsystem constraint violations (from system.json)
  - Transitive forbidden paths (multi-hop chains)
  - Coupling increases
  - Blast radius (how many nodes affected)

Classifies results as: SAFE, LOW_RISK, MEDIUM_RISK, HIGH_RISK, BLOCKED.
Supports comparing multiple architecture candidates.
"""


from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

import fnmatch
import json
from pathlib import Path

from codegraph.index import IndexStore
from codegraph.logging_config import get_logger

logger = get_logger("simulator")

# Risk classification levels
RISK_SAFE = "SAFE"
RISK_LOW = "LOW_RISK"
RISK_MEDIUM = "MEDIUM_RISK"
RISK_HIGH = "HIGH_RISK"
RISK_BLOCKED = "BLOCKED"


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
    risk_level: str = RISK_SAFE
    blast_radius: int = 0
    improvements: List[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "safe": self.safe,
            "risk_level": self.risk_level,
            "changes": [c.to_dict() for c in self.changes],
            "violations": [v.to_dict() for v in self.violations],
            "new_cycle_count": self.new_cycle_count,
            "coupling_delta": round(self.coupling_delta, 4),
            "blast_radius": self.blast_radius,
            "improvements": self.improvements,
            "summary": self.summary,
        }

    def format(self) -> str:
        lines = [f"Simulation: {self.risk_level}"]
        lines.append(f"  Changes: {len(self.changes)}")
        lines.append(f"  Violations: {len(self.violations)}")
        lines.append(f"  Blast radius: {self.blast_radius} nodes")
        if self.new_cycle_count:
            lines.append(f"  New cycles: {self.new_cycle_count}")
        if self.improvements:
            lines.append("\nImprovements:")
            for imp in self.improvements:
                lines.append(f"  + {imp}")
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
    check_layers: bool = True,
    check_subsystems: bool = True,
    forbidden_patterns: Optional[List[Tuple[str, str]]] = None,
    layer_rules: Optional[List[Tuple[str, str]]] = None,
    system_json_path: Optional[Path] = None,
) -> SimulationResult:
    """Simulate proposed changes on the dependency graph.

    Builds a virtual copy of the adjacency graph, applies the changes,
    and checks for new violations without modifying real data.

    Args:
        changes: List of proposed changes to simulate.
        check_cycles: Whether to check for newly introduced cycles.
        check_forbidden: Whether to check forbidden path patterns.
        check_layers: Whether to check layer boundary violations.
        check_subsystems: Whether to validate subsystem constraints.
        forbidden_patterns: List of (source_pattern, target_pattern) pairs.
        layer_rules: List of (forbidden_source_layer, forbidden_target_layer).
        system_json_path: Path to system.json for subsystem constraint checks.
    """
    result = SimulationResult(changes=changes)

    # Build current adjacency from index
    conn = index._get_conn()
    adj: Dict[str, Set[str]] = defaultdict(set)
    reverse_adj: Dict[str, Set[str]] = defaultdict(set)
    all_nodes: Set[str] = set()

    for row in conn.execute("SELECT node_id, callee_id FROM callees").fetchall():
        adj[row[0]].add(row[1])
        reverse_adj[row[1]].add(row[0])
        all_nodes.add(row[0])
        all_nodes.add(row[1])

    for row in conn.execute("SELECT id FROM nodes").fetchall():
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
                result.violations.append(
                    SimViolation(
                        violation_type="new_cycle",
                        severity="error",
                        description=f"New cycle introduced: {' -> '.join(cycle_nodes[:4])}...",
                        affected_nodes=cycle_nodes[:10],
                    )
                )

    # Check forbidden paths
    if check_forbidden and forbidden_patterns:
        for src_pat, tgt_pat in forbidden_patterns:
            for change in changes:
                if change.action == "add_edge":
                    if fnmatch.fnmatch(change.source, src_pat) and fnmatch.fnmatch(
                        change.target, tgt_pat
                    ):
                        result.safe = False
                        result.violations.append(
                            SimViolation(
                                violation_type="forbidden_path",
                                severity="error",
                                description=f"Forbidden path: {change.source} -> {change.target} matches {src_pat} -> {tgt_pat}",
                                affected_nodes=[change.source, change.target],
                            )
                        )

    # Check transitive forbidden paths (multi-hop)
    if check_forbidden and forbidden_patterns:
        _check_transitive_forbidden(adj, forbidden_patterns, result)

    # Check layer violations
    if check_layers and layer_rules:
        _check_layer_violations(adj, layer_rules, changes, result)

    # Check subsystem constraint violations
    if check_subsystems and system_json_path:
        _check_subsystem_constraints(adj, system_json_path, changes, result)

    # Check coupling changes
    old_coupling = _compute_module_coupling({k: v for k, v in _original_adj(index).items()})
    new_coupling = _compute_module_coupling(adj)
    result.coupling_delta = new_coupling - old_coupling
    if result.coupling_delta > 0.1:
        result.violations.append(
            SimViolation(
                violation_type="coupling_increase",
                severity="warning",
                description=f"Coupling increased by {result.coupling_delta:.3f}",
            )
        )

    # Detect structural improvements
    _detect_improvements(adj, existing_cycles, result)

    # Compute blast radius
    result.blast_radius = _compute_blast_radius(changes, adj, reverse_adj)

    # Classify risk
    result.risk_level = _classify_risk(result)

    # Summary
    if result.risk_level == RISK_BLOCKED:
        result.summary = f"{len(result.violations)} blocking violation(s) — changes rejected"
    elif result.risk_level == RISK_SAFE:
        result.summary = f"All {len(changes)} change(s) are safe to apply"
    else:
        result.summary = (
            f"{result.risk_level}: {len(result.violations)} issue(s), "
            f"blast radius {result.blast_radius} nodes"
        )

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
            changes.append(
                SimulatedChange(
                    action="add_edge",
                    source=node,
                    target=target,
                    reason=repair.get("reason", ""),
                )
            )
        elif action == "remove_dead_code":
            changes.append(
                SimulatedChange(
                    action="remove_node",
                    node_id=node,
                    reason=repair.get("reason", ""),
                )
            )
        elif action == "add_import":
            changes.append(
                SimulatedChange(
                    action="add_edge",
                    source=node,
                    target=target,
                    reason=repair.get("reason", ""),
                )
            )

    return simulate_changes(
        changes,
        index,
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
    conn = index._get_conn()
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


# ═══════════════════════════════════════════════════════════════════════
# Layer violation detection
# ═══════════════════════════════════════════════════════════════════════

# Default layer rules: (source_layer_pattern, forbidden_target_layer_pattern)
DEFAULT_LAYER_RULES: List[Tuple[str, str]] = [
    ("**/ui/*", "**/database/*"),
    ("**/frontend/*", "**/database/*"),
    ("**/components/*", "**/db/*"),
    ("tests/*", "**/internal/*"),
]


def _node_to_module(node_id: str) -> str:
    """Extract the module path from a node ID."""
    return node_id.split("::")[0] if "::" in node_id else node_id


def _check_layer_violations(
    adj: Dict[str, Set[str]],
    layer_rules: List[Tuple[str, str]],
    changes: List[SimulatedChange],
    result: SimulationResult,
) -> None:
    """Detect layer boundary violations in added edges."""
    for change in changes:
        if change.action != "add_edge":
            continue
        src_mod = _node_to_module(change.source)
        tgt_mod = _node_to_module(change.target)
        for src_pat, tgt_pat in layer_rules:
            if fnmatch.fnmatch(src_mod, src_pat) and fnmatch.fnmatch(tgt_mod, tgt_pat):
                result.safe = False
                result.violations.append(
                    SimViolation(
                        violation_type="layer_violation",
                        severity="error",
                        description=(
                            f"Layer violation: {src_mod} -> {tgt_mod} "
                            f"({src_pat} must not reach {tgt_pat})"
                        ),
                        affected_nodes=[change.source, change.target],
                    )
                )


# ═══════════════════════════════════════════════════════════════════════
# Subsystem constraint validation
# ═══════════════════════════════════════════════════════════════════════


def _load_system_json(path: Path) -> Dict[str, Any]:
    """Load system.json architecture definition."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _build_module_to_subsystem(
    system: Dict[str, Any],
) -> Dict[str, str]:
    """Map module paths to their owning subsystem."""
    mapping: Dict[str, str] = {}
    for sub in system.get("subsystems", []):
        sub_name = sub["name"]
        for comp in sub.get("components", []):
            module = comp.get("module", "")
            if module:
                mapping[module] = sub_name
    return mapping


def _build_forbidden_subsystem_deps(
    system: Dict[str, Any],
) -> Set[Tuple[str, str]]:
    """Extract forbidden subsystem dependencies from constraints."""
    forbidden: Set[Tuple[str, str]] = set()
    for constraint in system.get("constraints", []):
        if constraint.get("type") == "forbidden_dependency":
            forbidden.add((constraint["source"], constraint["target"]))
    return forbidden


def _check_subsystem_constraints(
    adj: Dict[str, Set[str]],
    system_path: Path,
    changes: List[SimulatedChange],
    result: SimulationResult,
) -> None:
    """Validate changes against subsystem constraints from system.json."""
    system = _load_system_json(system_path)
    if not system:
        return

    mod_to_sub = _build_module_to_subsystem(system)
    forbidden = _build_forbidden_subsystem_deps(system)

    for change in changes:
        if change.action != "add_edge":
            continue

        src_mod = _node_to_module(change.source)
        tgt_mod = _node_to_module(change.target)
        src_sub = mod_to_sub.get(src_mod, "")
        tgt_sub = mod_to_sub.get(tgt_mod, "")

        if not src_sub or not tgt_sub:
            continue

        # Check forbidden subsystem deps
        if (src_sub, tgt_sub) in forbidden:
            result.safe = False
            result.violations.append(
                SimViolation(
                    violation_type="subsystem_constraint",
                    severity="error",
                    description=(
                        f"Forbidden subsystem dependency: "
                        f"{src_sub} -> {tgt_sub} ({change.source} -> {change.target})"
                    ),
                    affected_nodes=[change.source, change.target],
                )
            )


# ═══════════════════════════════════════════════════════════════════════
# Transitive forbidden path detection
# ═══════════════════════════════════════════════════════════════════════


def _check_transitive_forbidden(
    adj: Dict[str, Set[str]],
    forbidden_patterns: List[Tuple[str, str]],
    result: SimulationResult,
) -> None:
    """Detect forbidden multi-hop dependency chains.

    For each forbidden pattern (src_pat, tgt_pat), check if there's
    a transitive path from any src-matching node to any tgt-matching
    node in the updated graph (max depth 5 to avoid explosion).
    """
    for src_pat, tgt_pat in forbidden_patterns:
        # Find source nodes matching pattern
        sources = [n for n in adj if fnmatch.fnmatch(n, src_pat)]
        # Find target nodes matching pattern
        all_nodes = set(adj.keys())
        for targets in adj.values():
            all_nodes.update(targets)
        targets = {n for n in all_nodes if fnmatch.fnmatch(n, tgt_pat)}

        if not sources or not targets:
            continue

        for src in sources:
            reachable = _bfs_limited(adj, src, max_depth=5)
            violations = reachable & targets
            if violations:
                tgt_sample = next(iter(violations))
                result.violations.append(
                    SimViolation(
                        violation_type="transitive_forbidden",
                        severity="warning",
                        description=(
                            f"Transitive forbidden path: {src} can reach "
                            f"{tgt_sample} (via {src_pat} -> {tgt_pat})"
                        ),
                        affected_nodes=[src, tgt_sample],
                    )
                )


def _bfs_limited(
    adj: Dict[str, Set[str]],
    start: str,
    max_depth: int,
) -> Set[str]:
    """BFS from start, limited to max_depth hops."""
    visited: Set[str] = set()
    frontier: Set[str] = {start}
    for _ in range(max_depth):
        next_frontier: Set[str] = set()
        for node in frontier:
            for neighbor in adj.get(node, set()):
                if neighbor not in visited:
                    visited.add(neighbor)
                    next_frontier.add(neighbor)
        frontier = next_frontier
        if not frontier:
            break
    return visited


# ═══════════════════════════════════════════════════════════════════════
# Structural improvement detection
# ═══════════════════════════════════════════════════════════════════════


def _detect_improvements(
    adj: Dict[str, Set[str]],
    existing_cycles: Set[frozenset],
    result: SimulationResult,
) -> None:
    """Detect positive structural changes."""
    new_cycles = _find_cycles_in_adj(adj)
    removed_cycles = existing_cycles - new_cycles
    if removed_cycles:
        result.improvements.append(f"Removed {len(removed_cycles)} cycle(s)")

    # Check if coupling decreased
    if result.coupling_delta < -0.05:
        result.improvements.append(f"Coupling reduced by {abs(result.coupling_delta):.3f}")


# ═══════════════════════════════════════════════════════════════════════
# Blast radius analysis
# ═══════════════════════════════════════════════════════════════════════


def _compute_blast_radius(
    changes: List[SimulatedChange],
    adj: Dict[str, Set[str]],
    reverse_adj: Dict[str, Set[str]],
) -> int:
    """Compute how many nodes are directly or transitively affected.

    For added/removed edges or nodes, counts all downstream dependents
    reachable within 3 hops via reverse edges (callers).
    """
    affected: Set[str] = set()

    seed_nodes: Set[str] = set()
    for change in changes:
        if change.node_id:
            seed_nodes.add(change.node_id)
        if change.source:
            seed_nodes.add(change.source)
        if change.target:
            seed_nodes.add(change.target)

    for seed in seed_nodes:
        affected.add(seed)
        affected.update(_bfs_limited(reverse_adj, seed, max_depth=3))

    return len(affected)


# ═══════════════════════════════════════════════════════════════════════
# Risk classification
# ═══════════════════════════════════════════════════════════════════════


def _classify_risk(result: SimulationResult) -> str:
    """Classify the simulation result into a risk level.

    BLOCKED:     Any error-severity violation (cycles, forbidden paths,
                 layer violations, subsystem constraint violations).
    HIGH_RISK:   Coupling increase > 0.1 or blast radius > 50.
    MEDIUM_RISK: Warnings present or blast radius > 20.
    LOW_RISK:    Minor warnings or small blast radius.
    SAFE:        No violations, no warnings.
    """
    errors = [v for v in result.violations if v.severity == "error"]
    warnings = [v for v in result.violations if v.severity == "warning"]

    if errors:
        result.safe = False
        return RISK_BLOCKED

    if result.coupling_delta > 0.1 or result.blast_radius > 50:
        result.safe = False
        return RISK_HIGH

    if warnings or result.blast_radius > 20:
        return RISK_MEDIUM

    if result.blast_radius > 5:
        return RISK_LOW

    return RISK_SAFE


# ═══════════════════════════════════════════════════════════════════════
# Candidate comparison
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class CandidateSimResult:
    """Simulation result for a single architecture candidate."""

    candidate_id: str
    result: SimulationResult
    score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "risk_level": self.result.risk_level,
            "score": round(self.score, 4),
            "violations": len(self.result.violations),
            "blast_radius": self.result.blast_radius,
            "coupling_delta": round(self.result.coupling_delta, 4),
            "improvements": self.result.improvements,
            "safe": self.result.safe,
        }


def compare_candidates(
    candidates: List[Dict[str, Any]],
    index: IndexStore,
    *,
    forbidden_patterns: Optional[List[Tuple[str, str]]] = None,
    layer_rules: Optional[List[Tuple[str, str]]] = None,
    system_json_path: Optional[Path] = None,
) -> List[CandidateSimResult]:
    """Simulate multiple architecture proposals and rank them.

    Each candidate dict must have:
        - candidate_id: str
        - changes: List[dict] with action/source/target/node_id/reason

    Returns candidates sorted by score (highest first).
    """
    results: List[CandidateSimResult] = []

    for cand in candidates:
        cand_id = cand.get("candidate_id", "unknown")
        raw_changes = cand.get("changes", [])
        sim_changes = [
            SimulatedChange(
                action=c.get("action", ""),
                source=c.get("source", ""),
                target=c.get("target", ""),
                node_id=c.get("node_id", ""),
                reason=c.get("reason", ""),
            )
            for c in raw_changes
        ]

        sim_result = simulate_changes(
            sim_changes,
            index,
            forbidden_patterns=forbidden_patterns,
            layer_rules=layer_rules,
            system_json_path=system_json_path,
        )

        # Score: higher is better
        score = _score_candidate(sim_result)

        results.append(
            CandidateSimResult(
                candidate_id=cand_id,
                result=sim_result,
                score=score,
            )
        )

    results.sort(key=lambda c: c.score, reverse=True)
    return results


def _score_candidate(result: SimulationResult) -> float:
    """Score a simulation result. Higher is better.

    Scoring:
        base = 1.0
        - 0.5 per error violation
        - 0.1 per warning violation
        - coupling_delta penalized if positive
        + 0.1 per improvement
        - blast_radius / 100
    """
    score = 1.0
    errors = sum(1 for v in result.violations if v.severity == "error")
    warnings = sum(1 for v in result.violations if v.severity == "warning")
    score -= errors * 0.5
    score -= warnings * 0.1
    score -= max(0.0, result.coupling_delta)
    score += len(result.improvements) * 0.1
    score -= result.blast_radius / 100.0
    return max(0.0, score)
