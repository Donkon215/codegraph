"""codegraph.cas — Content Addressed Store (CAS) graph module.

Implements Bazel-style content-addressed dependency hashing:
- dependency_hash = hash(body_hash + sorted(callee_dependency_hashes))
- Topological sort for bottom-up computation
- SCC (strongly connected component) handling for cycles
- Invalidation propagation from changed nodes
- Selective recomputation of affected subgraph
- Node-level change detection (replaces file-level)
- CAS-aware stale intent detection
- CAS-aware test impact analysis
- CAS-aware policy rule filtering
- Verification and debugging tools

Tasks Q-001 through Q-021.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple

from codegraph.logging_config import get_logger
from codegraph.utils.formatting import format_json, iso_now

logger = get_logger("cas")


# ═══════════════════════════════════════════════════════════════════════
# Q-002 — Core Dependency Hash Computation
# ═══════════════════════════════════════════════════════════════════════


def compute_dependency_hash(body_hash: str, callee_hashes: List[str]) -> str:
    """Compute dependency_hash = SHA256(body_hash + sorted callee hashes).

    If *callee_hashes* is empty, returns SHA256(body_hash) (leaf node).
    Sorting ensures determinism regardless of call order in source.
    """
    if not callee_hashes:
        return hashlib.sha256(body_hash.encode("utf-8")).hexdigest()
    sorted_callees = sorted(callee_hashes)
    payload = body_hash + ":" + ":".join(sorted_callees)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ═══════════════════════════════════════════════════════════════════════
# Q-003 — Topological Sort for Hash Computation Order
# ═══════════════════════════════════════════════════════════════════════


def _build_adjacency(
    graph0: Any, workflow: Any,
) -> Tuple[Dict[str, Set[str]], Set[str]]:
    """Build caller→callees adjacency from workflow edges.

    Returns (adjacency, all_node_ids).
    """
    adj: Dict[str, Set[str]] = defaultdict(set)
    all_ids: Set[str] = {n.id for n in graph0.nodes}
    for edge in workflow.edges:
        if edge.source in all_ids and edge.target in all_ids:
            adj[edge.source].add(edge.target)
    return dict(adj), all_ids


def _tarjan_scc(
    all_ids: Set[str], adj: Dict[str, Set[str]],
) -> List[FrozenSet[str]]:
    """Tarjan's algorithm for strongly connected components.

    Returns SCCs in reverse topological order (leaves first).
    """
    index_counter = [0]
    stack: list[str] = []
    on_stack: Set[str] = set()
    indices: Dict[str, int] = {}
    lowlinks: Dict[str, int] = {}
    result: List[FrozenSet[str]] = []

    def strongconnect(v: str) -> None:
        indices[v] = lowlinks[v] = index_counter[0]
        index_counter[0] += 1
        stack.append(v)
        on_stack.add(v)

        for w in adj.get(v, ()):
            if w not in all_ids:
                continue
            if w not in indices:
                strongconnect(w)
                lowlinks[v] = min(lowlinks[v], lowlinks[w])
            elif w in on_stack:
                lowlinks[v] = min(lowlinks[v], indices[w])

        if lowlinks[v] == indices[v]:
            scc: Set[str] = set()
            while True:
                w = stack.pop()
                on_stack.discard(w)
                scc.add(w)
                if w == v:
                    break
            result.append(frozenset(scc))

    for v in sorted(all_ids):
        if v not in indices:
            strongconnect(v)

    return result  # Already in reverse-topological order from Tarjan's


def topological_sort(
    workflow: Any, graph0: Any,
) -> Tuple[List[str], List[FrozenSet[str]]]:
    """Topological sort via Tarjan's SCC algorithm.

    Returns:
        (ordered_nodes, sccs) where ordered_nodes lists node IDs
        bottom-up (leaves first), and sccs lists all SCCs with >1 member.
    """
    adj, all_ids = _build_adjacency(graph0, workflow)
    scc_list = _tarjan_scc(all_ids, adj)

    ordered: List[str] = []
    cycles: List[FrozenSet[str]] = []

    for scc in scc_list:
        if len(scc) > 1:
            cycles.append(scc)
        ordered.extend(sorted(scc))

    return ordered, cycles


# ═══════════════════════════════════════════════════════════════════════
# Q-004 — Circular Dependency Handling
# ═══════════════════════════════════════════════════════════════════════


def compute_scc_hash(
    scc_node_ids: FrozenSet[str],
    graph0: Any,
    external_dep_hashes: Optional[List[str]] = None,
) -> str:
    """Compute a shared dependency_hash for all members of an SCC.

    All body_hashes are concatenated (sorted by ID) plus external
    dependency hashes for calls outside the SCC.
    """
    parts: List[str] = []
    for nid in sorted(scc_node_ids):
        node = graph0.get_node(nid)
        bh = node.body_hash if node else ""
        parts.append(f"{nid}:{bh}")

    if external_dep_hashes:
        parts.extend(sorted(external_dep_hashes))

    payload = ":".join(parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ═══════════════════════════════════════════════════════════════════════
# Q-005 — Full Graph Dependency Hash Builder
# ═══════════════════════════════════════════════════════════════════════


def build_dependency_hashes(
    graph0: Any, workflow: Any,
) -> Dict[str, str]:
    """Compute dependency_hash for every node in the graph.

    Bottom-up traversal: leaves first, then callers.
    SCCs are hashed as a unit.

    Returns mapping {node_id: dependency_hash}.
    """
    t0 = time.perf_counter()
    adj, all_ids = _build_adjacency(graph0, workflow)
    scc_list = _tarjan_scc(all_ids, adj)

    computed: Dict[str, str] = {}

    for scc in scc_list:
        if len(scc) == 1:
            nid = next(iter(scc))
            node = graph0.get_node(nid)
            if node is None:
                continue
            callee_hashes: List[str] = []
            for callee_id in adj.get(nid, ()):
                if callee_id in computed:
                    callee_hashes.append(computed[callee_id])
                else:
                    callee_node = graph0.get_node(callee_id)
                    if callee_node:
                        callee_hashes.append(callee_node.body_hash)
            computed[nid] = compute_dependency_hash(node.body_hash, callee_hashes)
        else:
            # SCC — collect external dependency hashes
            external_hashes: List[str] = []
            for nid in scc:
                for callee_id in adj.get(nid, ()):
                    if callee_id not in scc and callee_id in computed:
                        external_hashes.append(computed[callee_id])
            scc_hash = compute_scc_hash(scc, graph0, external_hashes)
            for nid in scc:
                computed[nid] = scc_hash
            if len(scc) > 2:
                logger.info("Cycle detected: %d nodes share SCC hash", len(scc))

    elapsed = time.perf_counter() - t0
    logger.info(
        "Computed dependency hashes for %d nodes in %.2fs",
        len(computed), elapsed,
    )
    return computed


# ═══════════════════════════════════════════════════════════════════════
# Q-006 — Reverse Dependency Index
# ═══════════════════════════════════════════════════════════════════════


def build_reverse_dependency_map(
    workflow: Any, graph0_ids: Optional[Set[str]] = None,
) -> Dict[str, Set[str]]:
    """Build callee→{callers} reverse map for upward propagation.

    Only includes edges where both endpoints are in *graph0_ids* (if given).
    """
    reverse: Dict[str, Set[str]] = defaultdict(set)
    for edge in workflow.edges:
        if graph0_ids and (edge.source not in graph0_ids or edge.target not in graph0_ids):
            continue
        reverse[edge.target].add(edge.source)
    return dict(reverse)


def get_all_dependents(
    node_id: str, reverse_map: Dict[str, Set[str]],
) -> Set[str]:
    """BFS upward through reverse map to find all transitive dependents."""
    visited: Set[str] = set()
    queue = deque(reverse_map.get(node_id, set()))
    while queue:
        current = queue.popleft()
        if current in visited:
            continue
        visited.add(current)
        for dep in reverse_map.get(current, ()):
            if dep not in visited:
                queue.append(dep)
    return visited


# ═══════════════════════════════════════════════════════════════════════
# Q-007 — Hash Invalidation Propagation Engine
# ═══════════════════════════════════════════════════════════════════════


def propagate_invalidation(
    changed_nodes: Set[str],
    reverse_map: Dict[str, Set[str]],
) -> Set[str]:
    """Propagate invalidation from changed nodes upward.

    Returns the full affected set = changed_nodes ∪ transitive dependents.
    """
    affected: Set[str] = set(changed_nodes)
    queue = deque(changed_nodes)

    while queue:
        current = queue.popleft()
        for dependent in reverse_map.get(current, ()):
            if dependent not in affected:
                affected.add(dependent)
                queue.append(dependent)

    if changed_nodes:
        factor = len(affected) / len(changed_nodes)
        logger.info(
            "%d changed nodes → %d affected nodes (propagation factor: %.1f)",
            len(changed_nodes), len(affected), factor,
        )
        if len(affected) > 1000:
            logger.warning(
                "Large affected set (%d nodes) — consider full rebuild",
                len(affected),
            )

    return affected


# ═══════════════════════════════════════════════════════════════════════
# Q-008 — Selective Dependency Hash Recomputation
# ═══════════════════════════════════════════════════════════════════════


def recompute_affected_hashes(
    affected: Set[str],
    graph0: Any,
    workflow: Any,
    cached_hashes: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """Recompute dependency_hash only for affected nodes.

    Unaffected nodes reuse their cached hashes.

    Returns mapping of all node hashes (affected recomputed, rest cached).
    """
    t0 = time.perf_counter()
    adj, all_ids = _build_adjacency(graph0, workflow)
    cache = dict(cached_hashes) if cached_hashes else {}

    # Topological sort only the affected subgraph
    affected_adj: Dict[str, Set[str]] = {}
    for nid in affected:
        if nid in adj:
            affected_adj[nid] = adj[nid]

    scc_list = _tarjan_scc(affected, affected_adj)
    recomputed = 0

    for scc in scc_list:
        if len(scc) == 1:
            nid = next(iter(scc))
            node = graph0.get_node(nid)
            if node is None:
                continue
            callee_hashes: List[str] = []
            for callee_id in adj.get(nid, ()):
                if callee_id in cache:
                    callee_hashes.append(cache[callee_id])
                elif callee_id in affected:
                    pass  # Will be computed; skip for now (handled by topo order)
                else:
                    callee_node = graph0.get_node(callee_id)
                    if callee_node and callee_node.dependency_hash:
                        callee_hashes.append(callee_node.dependency_hash)
                        cache[callee_id] = callee_node.dependency_hash
                    elif callee_node:
                        callee_hashes.append(callee_node.body_hash)
            new_hash = compute_dependency_hash(node.body_hash, callee_hashes)
            cache[nid] = new_hash
            recomputed += 1
        else:
            external_hashes: List[str] = []
            for nid in scc:
                for callee_id in adj.get(nid, ()):
                    if callee_id not in scc:
                        h = cache.get(callee_id)
                        if h:
                            external_hashes.append(h)
            scc_hash = compute_scc_hash(scc, graph0, external_hashes)
            for nid in scc:
                cache[nid] = scc_hash
            recomputed += len(scc)

    elapsed = time.perf_counter() - t0
    logger.info(
        "Recomputed %d dependency hashes (out of %d total) in %.2fs",
        recomputed, len(all_ids), elapsed,
    )
    return cache


# ═══════════════════════════════════════════════════════════════════════
# Q-009 — Node-Level Change Detection
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class NodeChanges:
    """Result of node-level change detection."""

    added: List[str] = field(default_factory=list)
    removed: List[str] = field(default_factory=list)
    body_changed: List[str] = field(default_factory=list)
    unchanged: List[str] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.removed or self.body_changed)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "added": self.added,
            "removed": self.removed,
            "body_changed": self.body_changed,
            "unchanged_count": len(self.unchanged),
        }


def detect_node_changes(
    old_graph0: Any, new_graph0: Any,
) -> NodeChanges:
    """Detect precise node-level changes by comparing body_hashes.

    This replaces the coarse 'all nodes in changed file' approach.
    """
    result = NodeChanges()
    old_ids = {n.id for n in old_graph0.nodes}
    new_ids = {n.id for n in new_graph0.nodes}

    result.added = sorted(new_ids - old_ids)
    result.removed = sorted(old_ids - new_ids)

    for nid in sorted(old_ids & new_ids):
        old_node = old_graph0.get_node(nid)
        new_node = new_graph0.get_node(nid)
        if old_node and new_node and old_node.body_hash != new_node.body_hash:
            result.body_changed.append(nid)
        else:
            result.unchanged.append(nid)

    return result


# ═══════════════════════════════════════════════════════════════════════
# Q-010 / Q-011 — Delta Engine CAS Integration
# ═══════════════════════════════════════════════════════════════════════


def run_cas_pipeline(
    old_graph0: Any,
    new_graph0: Any,
    workflow: Any,
    cached_hashes: Optional[Dict[str, str]] = None,
    old_workflow: Optional[Any] = None,
    extra_changed: Optional[Set[str]] = None,
) -> Tuple[Set[str], Dict[str, str]]:
    """Full CAS pipeline for delta integration.

    1. Detect node-level changes
    2. Build reverse dependency map
    3. Propagate invalidation
    4. Recompute affected hashes

    Returns (affected_set, new_hashes).

    ``extra_changed`` seeds invalidation from nodes whose *edges* changed even
    though their body did not (e.g. an import flip that re-resolves a callee).
    A dependency hash depends on callee edges, so such a node must be
    re-hashed even when no node-level change is detected (Issue #9).
    """
    node_changes = detect_node_changes(old_graph0, new_graph0)

    if not node_changes.has_changes and not extra_changed:
        logger.info("No node-level changes detected — CAS skip")
        # Return existing hashes
        existing = cached_hashes or {}
        return set(), existing

    # Seed invalidation from added, body-changed AND removed nodes: a removed
    # node's former callers must be re-hashed even though the node itself is
    # gone (Issue #9). Also seed nodes whose edges changed (extra_changed).
    changed_set = set(
        node_changes.added + node_changes.body_changed + list(node_changes.removed)
    )
    if extra_changed:
        changed_set.update(extra_changed)

    graph0_ids = {n.id for n in new_graph0.nodes}
    reverse_map = build_reverse_dependency_map(workflow, graph0_ids)
    # A node whose edge was *removed* between versions (present in the old
    # workflow, absent in the new one) must still invalidate its former
    # sources. build_reverse_dependency_map drops edges whose target no longer
    # exists, so for the old workflow we keep edges whose *source* (the caller)
    # still exists — that's exactly the caller we need to re-hash (Issue #9).
    if old_workflow is not None:
        for edge in old_workflow.edges:
            src = getattr(edge, "source", None)
            if src in graph0_ids:
                reverse_map.setdefault(edge.target, set()).add(src)
    affected = propagate_invalidation(changed_set, reverse_map)

    # Filter to nodes that still exist
    affected = affected & graph0_ids

    new_hashes = recompute_affected_hashes(
        affected, new_graph0, workflow, cached_hashes,
    )

    return affected, new_hashes


# ═══════════════════════════════════════════════════════════════════════
# Q-012 — CAS-Aware Index Update
# ═══════════════════════════════════════════════════════════════════════


def get_cas_index_updates(
    affected: Set[str],
    new_hashes: Dict[str, str],
    graph0: Any,
) -> List[Tuple[str, str, str]]:
    """Get index update tuples for affected nodes.

    Returns list of (node_id, dependency_hash, body_hash) for SQL updates.
    """
    updates: List[Tuple[str, str, str]] = []
    for nid in affected:
        dep_hash = new_hashes.get(nid, "")
        node = graph0.get_node(nid)
        body_hash = node.body_hash if node else ""
        updates.append((nid, dep_hash, body_hash))
    return updates


# ═══════════════════════════════════════════════════════════════════════
# Q-013 — CAS-Aware Stale Intent Detection
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class StaleIntentReport:
    """Result of CAS-aware stale intent detection."""

    directly_stale: List[str] = field(default_factory=list)
    transitively_stale: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "directly_stale": self.directly_stale,
            "transitively_stale": self.transitively_stale,
            "total": len(self.directly_stale) + len(self.transitively_stale),
        }


def detect_stale_intents_cas(
    affected_nodes: Set[str],
    body_changed_nodes: Set[str],
    graph1: Any,
) -> StaleIntentReport:
    """Detect both directly and transitively stale intents.

    - directly_stale: body_hash changed AND has intent
    - transitively_stale: body unchanged BUT dep_hash changed AND has intent
    """
    report = StaleIntentReport()

    for nid in sorted(affected_nodes):
        g1_node = graph1.get_node(nid) if hasattr(graph1, "get_node") else None
        if g1_node is None:
            continue
        # Only count nodes that actually have intent text
        intent = getattr(g1_node, "intent", None)
        if not intent:
            continue

        if nid in body_changed_nodes:
            report.directly_stale.append(nid)
        else:
            report.transitively_stale.append(nid)

    return report


# ═══════════════════════════════════════════════════════════════════════
# Q-014 — CAS-Aware Task Generation (filter for analyzer)
# ═══════════════════════════════════════════════════════════════════════


def get_cas_task_context(
    node_id: str,
    body_changed_nodes: Set[str],
    reverse_map: Dict[str, Set[str]],
) -> Dict[str, Any]:
    """Build propagation chain context for a CAS-triggered task."""
    context: Dict[str, Any] = {"cas_triggered": True}

    if node_id in body_changed_nodes:
        context["trigger"] = "direct_body_change"
    else:
        # Find which body-changed node triggered this
        chain: List[str] = []
        visited: Set[str] = set()
        queue = deque([node_id])
        while queue:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            for callee in reverse_map.get(current, ()):
                if callee in body_changed_nodes:
                    chain.append(callee)
                elif callee not in visited:
                    queue.append(callee)
        context["trigger"] = "transitive_propagation"
        context["propagation_sources"] = chain[:10]

    return context


# ═══════════════════════════════════════════════════════════════════════
# Q-015 — CAS-Aware Test Impact Analysis
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class CASTestImpact:
    """Test impact result from CAS propagation."""

    affected_tests: List[str] = field(default_factory=list)
    direct_tests: List[str] = field(default_factory=list)
    transitive_tests: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "affected_tests": self.affected_tests,
            "direct_count": len(self.direct_tests),
            "transitive_count": len(self.transitive_tests),
            "total": len(self.affected_tests),
        }


def test_impact_cas(
    affected_nodes: Set[str],
    graph0: Any,
    body_changed_nodes: Optional[Set[str]] = None,
) -> CASTestImpact:
    """Determine affected tests from CAS affected set.

    Any test-layer (layer 4) node in the affected set is an affected test.
    O(|affected_set|) instead of graph traversal.
    """
    from codegraph.layers import Layer

    result = CASTestImpact()
    body_changed = body_changed_nodes or set()

    for nid in sorted(affected_nodes):
        node = graph0.get_node(nid)
        if node is None:
            continue
        # Check if test node (layer 4 or test-pattern file)
        node_layer = getattr(node, "layer", None)
        is_test = False
        if node_layer is not None:
            try:
                is_test = Layer(node_layer) == Layer.TEST
            except (ValueError, TypeError):
                is_test = node_layer == 4
        if not is_test:
            # Fallback: check file pattern
            is_test = any(
                p in node.file for p in ("test_", "_test.", "conftest.", "tests/")
            )

        if is_test:
            result.affected_tests.append(nid)
            if nid in body_changed:
                result.direct_tests.append(nid)
            else:
                result.transitive_tests.append(nid)

    return result


test_impact_cas.__test__ = False  # type: ignore[attr-defined]


# ═══════════════════════════════════════════════════════════════════════
# Q-016 — CAS-Aware Policy Rule Filtering
# ═══════════════════════════════════════════════════════════════════════


def filter_affected_rules(
    rules: List[Any],
    affected_nodes: Set[str],
    graph0: Any,
) -> List[Any]:
    """Filter policy rules to only those involving affected nodes.

    A rule is affected if its source or target scope includes any affected node.
    """
    if not affected_nodes:
        return []

    affected_rules: List[Any] = []
    for rule in rules:
        source_scope = getattr(rule, "source", None) or ""
        target_scope = getattr(rule, "target", None) or ""

        # Direct match
        if source_scope in affected_nodes or target_scope in affected_nodes:
            affected_rules.append(rule)
            continue

        # Glob/prefix match: check if any affected node matches the scope
        matched = False
        for nid in affected_nodes:
            if _scope_matches(source_scope, nid) or _scope_matches(target_scope, nid):
                matched = True
                break
        if matched:
            affected_rules.append(rule)

    logger.info(
        "Evaluated %d of %d policy rules (CAS filtering)",
        len(affected_rules), len(rules),
    )
    return affected_rules


def _scope_matches(scope: str, node_id: str) -> bool:
    """Check if a scope pattern matches a node ID."""
    if not scope:
        return False
    if scope == node_id:
        return True
    if scope.endswith("*"):
        return node_id.startswith(scope[:-1])
    if scope.endswith("::*"):
        return node_id.startswith(scope[:-1])
    return False


# ═══════════════════════════════════════════════════════════════════════
# Q-017 / Q-018 — Hash Snapshot Storage
# ═══════════════════════════════════════════════════════════════════════


def save_hash_snapshot(
    hashes: Dict[str, str],
    project_root: Path,
    graph_version: int = 0,
) -> None:
    """Save dependency hash snapshot for next delta comparison."""
    cas_dir = project_root / ".codegraph" / "cas"
    cas_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "graph_version": graph_version,
        "timestamp": iso_now(),
        "node_count": len(hashes),
        "hashes": hashes,
    }
    snap_path = cas_dir / "hash_snapshot.json"
    snap_path.write_text(
        format_json(data, compact=True), encoding="utf-8",
    )


def load_hash_snapshot(
    project_root: Path,
) -> Optional[Dict[str, str]]:
    """Load previous hash snapshot. Returns None if missing/corrupt."""
    snap_path = project_root / ".codegraph" / "cas" / "hash_snapshot.json"
    if not snap_path.exists():
        return None
    try:
        data = json.loads(snap_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "hashes" not in data:
            logger.warning("Invalid hash snapshot format, will recompute")
            return None
        return data["hashes"]
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Corrupt hash snapshot: %s — will recompute", exc)
        return None


# ═══════════════════════════════════════════════════════════════════════
# Q-019 — CAS Hash Cache
# ═══════════════════════════════════════════════════════════════════════


class CASCache:
    """In-memory cache of computed dependency hashes."""

    def __init__(self, initial: Optional[Dict[str, str]] = None) -> None:
        self._cache: Dict[str, str] = dict(initial) if initial else {}
        self._hits = 0
        self._misses = 0

    def get(self, node_id: str) -> Optional[str]:
        """Return cached hash, or None."""
        val = self._cache.get(node_id)
        if val is not None:
            self._hits += 1
        else:
            self._misses += 1
        return val

    def set(self, node_id: str, dep_hash: str) -> None:
        """Store computed hash."""
        self._cache[node_id] = dep_hash

    def invalidate(self, node_id: str) -> None:
        """Remove a single node from cache."""
        self._cache.pop(node_id, None)

    def invalidate_set(self, node_ids: Set[str]) -> None:
        """Bulk invalidation."""
        for nid in node_ids:
            self._cache.pop(nid, None)

    def as_dict(self) -> Dict[str, str]:
        """Return copy of all cached hashes."""
        return dict(self._cache)

    @property
    def stats(self) -> Dict[str, int]:
        return {
            "size": len(self._cache),
            "hits": self._hits,
            "misses": self._misses,
        }


# ═══════════════════════════════════════════════════════════════════════
# Q-020 — CAS Consistency Verification
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class CASVerificationResult:
    """Result of CAS integrity verification."""

    passed: bool = True
    total_nodes: int = 0
    checked: int = 0
    mismatches: Dict[str, Tuple[str, str]] = field(default_factory=dict)
    not_computed: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "total_nodes": self.total_nodes,
            "checked": self.checked,
            "mismatches": len(self.mismatches),
            "not_computed": len(self.not_computed),
        }


def verify_cas_integrity(
    graph0: Any, workflow: Any,
) -> CASVerificationResult:
    """Full CAS verification: recompute all hashes and compare with stored.

    Returns pass/fail with mismatch details.
    """
    result = CASVerificationResult()
    result.total_nodes = len(graph0.nodes)

    # Recompute from scratch
    fresh_hashes = build_dependency_hashes(graph0, workflow)

    for node in graph0.nodes:
        stored = node.dependency_hash
        computed = fresh_hashes.get(node.id)

        if stored is None:
            result.not_computed.append(node.id)
            continue

        result.checked += 1
        if computed and stored != computed:
            result.mismatches[node.id] = (stored, computed)

    result.passed = len(result.mismatches) == 0
    return result


# ═══════════════════════════════════════════════════════════════════════
# Q-021 — CAS Explain Enhancement
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class CASExplainInfo:
    """CAS-specific information for the explain command."""

    node_id: str = ""
    dependency_hash: Optional[str] = None
    body_hash: str = ""
    direct_callees: List[str] = field(default_factory=list)
    direct_callers: List[str] = field(default_factory=list)
    transitive_dependents_count: int = 0
    would_invalidate: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "dependency_hash": self.dependency_hash,
            "body_hash": self.body_hash,
            "direct_callees": self.direct_callees,
            "direct_callers": self.direct_callers,
            "transitive_dependents_count": self.transitive_dependents_count,
            "would_invalidate": self.would_invalidate[:20],
        }


def explain_cas(
    node_id: str,
    graph0: Any,
    workflow: Any,
) -> CASExplainInfo:
    """Build CAS explanation for a node."""
    info = CASExplainInfo(node_id=node_id)

    node = graph0.get_node(node_id)
    if node is None:
        return info

    info.body_hash = node.body_hash
    info.dependency_hash = node.dependency_hash

    # Direct callees and callers from workflow
    graph0_ids = {n.id for n in graph0.nodes}
    adj, _ = _build_adjacency(graph0, workflow)
    info.direct_callees = sorted(adj.get(node_id, set()))

    reverse = build_reverse_dependency_map(workflow, graph0_ids)
    info.direct_callers = sorted(reverse.get(node_id, set()))

    # Transitive dependents (what would break if this changed)
    dependents = get_all_dependents(node_id, reverse)
    info.transitive_dependents_count = len(dependents)
    info.would_invalidate = sorted(dependents)[:20]

    return info
