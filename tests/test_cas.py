"""Unit tests for the Content Addressed Store (CAS) module.

Tests Q-001 through Q-021.
"""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Dict, Set

import pytest

from codegraph.cas import (
    compute_dependency_hash,
    topological_sort,
    _tarjan_scc,
    compute_scc_hash,
    build_dependency_hashes,
    build_reverse_dependency_map,
    get_all_dependents,
    propagate_invalidation,
    recompute_affected_hashes,
    detect_node_changes,
    run_cas_pipeline,
    get_cas_index_updates,
    detect_stale_intents_cas,
    test_impact_cas,
    filter_affected_rules,
    save_hash_snapshot,
    load_hash_snapshot,
    CASCache,
    verify_cas_integrity,
    explain_cas,
    NodeChanges,
    StaleIntentReport,
    CASTestImpact,
    CASVerificationResult,
    CASExplainInfo,
)
from codegraph.models.graph0 import Graph0, Graph0Node
from codegraph.models.workflow import Workflow, WorkflowEdge


# ── Helpers ────────────────────────────────────────────────────────────


def _make_graph0(*nodes_data) -> Graph0:
    """Build a Graph0 from (id, body_hash, file, type, line) tuples."""
    nodes = [
        Graph0Node(id=nd[0], body_hash=nd[1], file=nd[2], type=nd[3], line=nd[4])
        for nd in nodes_data
    ]
    return Graph0(nodes=nodes)


def _make_workflow(*edges_data) -> Workflow:
    """Build a Workflow from (source, target) tuples.

    Edges mean: source *calls* target.
    """
    edges = [WorkflowEdge(source=s, target=t) for s, t in edges_data]
    return Workflow(edges=edges)


# ── Q-002: compute_dependency_hash ─────────────────────────────────────


class TestComputeDependencyHash:

    def test_leaf_node(self) -> None:
        """A leaf node with no callees should produce a deterministic hash."""
        h = compute_dependency_hash("abc123", [])
        assert isinstance(h, str)
        assert len(h) == 64  # SHA-256 hex digest

    def test_same_inputs_same_hash(self) -> None:
        h1 = compute_dependency_hash("abc", ["def", "ghi"])
        h2 = compute_dependency_hash("abc", ["def", "ghi"])
        assert h1 == h2

    def test_order_independence(self) -> None:
        """Callee hashes are sorted so order doesn't matter."""
        h1 = compute_dependency_hash("abc", ["z", "a"])
        h2 = compute_dependency_hash("abc", ["a", "z"])
        assert h1 == h2

    def test_different_body_different_hash(self) -> None:
        h1 = compute_dependency_hash("abc", ["x"])
        h2 = compute_dependency_hash("def", ["x"])
        assert h1 != h2

    def test_different_callees_different_hash(self) -> None:
        h1 = compute_dependency_hash("abc", ["x"])
        h2 = compute_dependency_hash("abc", ["y"])
        assert h1 != h2


# ── Q-003: Topological Sort & Tarjan SCC ───────────────────────────────


class TestTopologicalSort:

    def test_linear_chain(self) -> None:
        g = _make_graph0(
            ("a", "h1", "f.py", "function", 1),
            ("b", "h2", "f.py", "function", 5),
            ("c", "h3", "f.py", "function", 10),
        )
        # a calls b, b calls c  ⟹  topo order: c, b, a (leaves first)
        wf = _make_workflow(("a", "b"), ("b", "c"))
        order, sccs = topological_sort(wf, g)
        assert isinstance(order, list)
        # c should come before b, and b before a
        assert order.index("c") < order.index("b")
        assert order.index("b") < order.index("a")

    def test_disconnected_nodes(self) -> None:
        g = _make_graph0(
            ("a", "h1", "f.py", "function", 1),
            ("b", "h2", "f.py", "function", 5),
        )
        wf = _make_workflow()  # no edges
        order, sccs = topological_sort(wf, g)
        assert set(order) == {"a", "b"}

    def test_with_cycle(self) -> None:
        g = _make_graph0(
            ("a", "h1", "f.py", "function", 1),
            ("b", "h2", "f.py", "function", 5),
        )
        wf = _make_workflow(("a", "b"), ("b", "a"))
        order, sccs = topological_sort(wf, g)
        # The cycle {a, b} should appear in the SCC list
        cycle_found = any(len(scc) == 2 and {"a", "b"} == scc for scc in sccs)
        assert cycle_found


class TestTarjanSCC:

    def test_no_cycles(self) -> None:
        adj: Dict[str, Set[str]] = {"a": {"b"}, "b": {"c"}, "c": set()}
        sccs = _tarjan_scc({"a", "b", "c"}, adj)
        # Each node in its own SCC
        assert all(len(scc) == 1 for scc in sccs)

    def test_two_node_cycle(self) -> None:
        adj: Dict[str, Set[str]] = {"a": {"b"}, "b": {"a"}}
        sccs = _tarjan_scc({"a", "b"}, adj)
        cycle = [s for s in sccs if len(s) > 1]
        assert len(cycle) == 1
        assert cycle[0] == frozenset({"a", "b"})

    def test_self_loop(self) -> None:
        adj: Dict[str, Set[str]] = {"a": {"a"}}
        sccs = _tarjan_scc({"a"}, adj)
        assert any(frozenset({"a"}) == scc for scc in sccs)


# ── Q-004: SCC Hash ────────────────────────────────────────────────────


class TestComputeSCCHash:

    def test_scc_hash_deterministic(self) -> None:
        g = _make_graph0(
            ("a", "h1", "f.py", "function", 1),
            ("b", "h2", "f.py", "function", 5),
        )
        scc = frozenset({"a", "b"})
        h1 = compute_scc_hash(scc, g)
        h2 = compute_scc_hash(scc, g)
        assert h1 == h2
        assert len(h1) == 64

    def test_scc_hash_changes_with_body(self) -> None:
        g1 = _make_graph0(
            ("a", "h1", "f.py", "function", 1),
            ("b", "h2", "f.py", "function", 5),
        )
        g2 = _make_graph0(
            ("a", "CHANGED", "f.py", "function", 1),
            ("b", "h2", "f.py", "function", 5),
        )
        scc = frozenset({"a", "b"})
        assert compute_scc_hash(scc, g1) != compute_scc_hash(scc, g2)


# ── Q-005: build_dependency_hashes ─────────────────────────────────────


class TestBuildDependencyHashes:

    def test_one_node(self) -> None:
        g = _make_graph0(("a", "h1", "f.py", "function", 1))
        wf = _make_workflow()
        hashes = build_dependency_hashes(g, wf)
        assert "a" in hashes
        assert len(hashes["a"]) == 64

    def test_chain_hashes(self) -> None:
        g = _make_graph0(
            ("a", "h1", "f.py", "function", 1),
            ("b", "h2", "f.py", "function", 5),
        )
        wf = _make_workflow(("a", "b"))
        hashes = build_dependency_hashes(g, wf)
        assert "a" in hashes and "b" in hashes
        # a's hash differs from b's because a depends on b
        assert hashes["a"] != hashes["b"]

    def test_all_nodes_get_hashes(self) -> None:
        g = _make_graph0(
            ("a", "h1", "a.py", "function", 1),
            ("b", "h2", "b.py", "function", 1),
            ("c", "h3", "c.py", "function", 1),
        )
        wf = _make_workflow(("a", "b"), ("b", "c"))
        hashes = build_dependency_hashes(g, wf)
        assert set(hashes.keys()) == {"a", "b", "c"}


# ── Q-006: Reverse Dependency Map ──────────────────────────────────────


class TestReverseDependencyMap:

    def test_simple_reverse(self) -> None:
        wf = _make_workflow(("a", "b"), ("a", "c"))
        rev = build_reverse_dependency_map(wf)
        assert "b" in rev and "a" in rev["b"]
        assert "c" in rev and "a" in rev["c"]

    def test_get_all_dependents(self) -> None:
        wf = _make_workflow(("a", "b"), ("b", "c"))
        rev = build_reverse_dependency_map(wf)
        deps = get_all_dependents("c", rev)
        assert "b" in deps
        assert "a" in deps

    def test_get_all_dependents_no_deps(self) -> None:
        wf = _make_workflow(("a", "b"))
        rev = build_reverse_dependency_map(wf)
        deps = get_all_dependents("a", rev)
        assert deps == set()


# ── Q-007: Invalidation Propagation ───────────────────────────────────


class TestPropagateInvalidation:

    def test_propagate_from_leaf(self) -> None:
        wf = _make_workflow(("a", "b"), ("b", "c"))
        rev = build_reverse_dependency_map(wf)
        affected = propagate_invalidation({"c"}, rev)
        assert "c" in affected
        assert "b" in affected
        assert "a" in affected

    def test_no_propagation_for_root(self) -> None:
        wf = _make_workflow(("a", "b"))
        rev = build_reverse_dependency_map(wf)
        affected = propagate_invalidation({"a"}, rev)
        assert affected == {"a"}

    def test_diamond_propagation(self) -> None:
        # a -> b, a -> c, b -> d, c -> d
        wf = _make_workflow(("a", "b"), ("a", "c"), ("b", "d"), ("c", "d"))
        rev = build_reverse_dependency_map(wf)
        affected = propagate_invalidation({"d"}, rev)
        assert affected == {"a", "b", "c", "d"}


# ── Q-008: Selective Hash Recomputation ────────────────────────────────


class TestRecomputeAffectedHashes:

    def test_recomputes_affected_nodes(self) -> None:
        g = _make_graph0(
            ("a", "h1", "f.py", "function", 1),
            ("b", "h2", "f.py", "function", 5),
        )
        wf = _make_workflow(("a", "b"))
        result = recompute_affected_hashes({"a", "b"}, g, wf)
        assert "a" in result and "b" in result


# ── Q-009: Node Change Detection ──────────────────────────────────────


class TestDetectNodeChanges:

    def test_no_changes(self) -> None:
        g = _make_graph0(("a", "h1", "f.py", "function", 1))
        changes = detect_node_changes(g, g)
        assert not changes.has_changes

    def test_body_changed(self) -> None:
        old = _make_graph0(("a", "h1", "f.py", "function", 1))
        new = _make_graph0(("a", "h2", "f.py", "function", 1))
        changes = detect_node_changes(old, new)
        assert "a" in changes.body_changed

    def test_added_node(self) -> None:
        old = _make_graph0(("a", "h1", "f.py", "function", 1))
        new = _make_graph0(
            ("a", "h1", "f.py", "function", 1),
            ("b", "h2", "f.py", "function", 5),
        )
        changes = detect_node_changes(old, new)
        assert "b" in changes.added

    def test_removed_node(self) -> None:
        old = _make_graph0(
            ("a", "h1", "f.py", "function", 1),
            ("b", "h2", "f.py", "function", 5),
        )
        new = _make_graph0(("a", "h1", "f.py", "function", 1))
        changes = detect_node_changes(old, new)
        assert "b" in changes.removed

    def test_unchanged_node(self) -> None:
        old = _make_graph0(("a", "h1", "f.py", "function", 1))
        new = _make_graph0(("a", "h1", "f.py", "function", 1))
        changes = detect_node_changes(old, new)
        assert "a" in changes.unchanged

    def test_node_changes_to_dict(self) -> None:
        changes = NodeChanges(added=["x"], body_changed=["y"])
        d = changes.to_dict()
        assert d["added"] == ["x"]
        assert d["body_changed"] == ["y"]


# ── Q-010/Q-011: CAS Pipeline ─────────────────────────────────────────


class TestRunCasPipeline:

    def test_no_changes(self) -> None:
        g = _make_graph0(("a", "h1", "f.py", "function", 1))
        wf = _make_workflow()
        affected, hashes = run_cas_pipeline(g, g, wf)
        assert len(affected) == 0

    def test_with_body_change(self) -> None:
        old = _make_graph0(("a", "h1", "f.py", "function", 1))
        new = _make_graph0(("a", "h2", "f.py", "function", 1))
        wf = _make_workflow()
        affected, hashes = run_cas_pipeline(old, new, wf)
        assert "a" in affected
        assert "a" in hashes

    def test_with_chain_propagation(self) -> None:
        old = _make_graph0(
            ("a", "h1", "f.py", "function", 1),
            ("b", "h2", "f.py", "function", 5),
        )
        new = _make_graph0(
            ("a", "h1", "f.py", "function", 1),
            ("b", "CHANGED", "f.py", "function", 5),
        )
        wf = _make_workflow(("a", "b"))
        affected, hashes = run_cas_pipeline(old, new, wf)
        assert "b" in affected
        # a should also be invalidated since it depends on b
        assert "a" in affected


# ── Q-012: CAS Index Updates ──────────────────────────────────────────


class TestGetCasIndexUpdates:

    def test_produces_index_rows(self) -> None:
        g = _make_graph0(("a", "body_h", "f.py", "function", 1))
        hashes = {"a": "dep_hash_123"}
        updates = get_cas_index_updates({"a"}, hashes, g)
        assert len(updates) == 1
        node_id, dep_hash, body_hash = updates[0]
        assert node_id == "a"
        assert dep_hash == "dep_hash_123"
        assert body_hash == "body_h"


# ── Q-013: Stale Intent Detection ─────────────────────────────────────


class TestDetectStaleIntentsCas:

    def test_directly_stale(self) -> None:
        from codegraph.models.graph1 import Graph1, Graph1Node
        g1 = Graph1(nodes=[Graph1Node(id="a", intent="do something")])
        report = detect_stale_intents_cas({"a", "b"}, {"a"}, g1)
        assert "a" in report.directly_stale

    def test_transitively_stale(self) -> None:
        from codegraph.models.graph1 import Graph1, Graph1Node
        g1 = Graph1(nodes=[Graph1Node(id="b", intent="another thing")])
        report = detect_stale_intents_cas({"a", "b"}, {"a"}, g1)
        # b is affected but its body didn't change — transitively stale
        assert "b" in report.transitively_stale

    def test_report_to_dict(self) -> None:
        report = StaleIntentReport(directly_stale=["a"], transitively_stale=["b"])
        d = report.to_dict()
        assert "directly_stale" in d
        assert "transitively_stale" in d


# ── Q-015: Test Impact Analysis ────────────────────────────────────────


class TestTestImpactCas:

    def test_affected_test_nodes(self) -> None:
        g = _make_graph0(
            ("src/mod.py::func", "h1", "src/mod.py", "function", 1),
            ("tests/test_mod.py::test_func", "h2", "tests/test_mod.py", "function", 1),
        )
        result = test_impact_cas(
            {"src/mod.py::func", "tests/test_mod.py::test_func"},
            g,
            body_changed_nodes={"src/mod.py::func"},
        )
        assert isinstance(result, CASTestImpact)
        assert "tests/test_mod.py::test_func" in result.affected_tests

    def test_result_to_dict(self) -> None:
        r = CASTestImpact(affected_tests=["t1"], direct_tests=["t1"])
        d = r.to_dict()
        assert d["affected_tests"] == ["t1"]


# ── Q-016: Policy Rule Filtering ──────────────────────────────────────


class TestFilterAffectedRules:

    def test_filters_by_scope(self) -> None:
        g = _make_graph0(("src/mod.py::func", "h1", "src/mod.py", "function", 1))
        # Rules have source/target attributes (not scope)
        class FakeRule:
            def __init__(self, source, target=""):
                self.source = source
                self.target = target
        rules = [FakeRule("src/mod.py::func"), FakeRule("other/file.py::bar")]
        result = filter_affected_rules(rules, {"src/mod.py::func"}, g)
        assert len(result) == 1

    def test_glob_scope(self) -> None:
        g = _make_graph0(("src/mod.py::func", "h1", "src/mod.py", "function", 1))
        class FakeRule:
            def __init__(self, source, target=""):
                self.source = source
                self.target = target
        rules = [FakeRule("src/*")]
        result = filter_affected_rules(rules, {"src/mod.py::func"}, g)
        assert len(result) == 1


# ── Q-017/Q-018: Hash Snapshots ────────────────────────────────────────


class TestHashSnapshots:

    def test_save_and_load(self, tmp_path: Path) -> None:
        # Create .codegraph dir
        cg = tmp_path / ".codegraph"
        cg.mkdir()
        hashes = {"a": "hash_a", "b": "hash_b"}
        save_hash_snapshot(hashes, tmp_path)
        loaded = load_hash_snapshot(tmp_path)
        assert loaded is not None
        assert loaded["a"] == "hash_a"
        assert loaded["b"] == "hash_b"

    def test_load_missing_returns_none(self, tmp_path: Path) -> None:
        cg = tmp_path / ".codegraph"
        cg.mkdir()
        loaded = load_hash_snapshot(tmp_path)
        assert loaded is None


# ── Q-019: CASCache ────────────────────────────────────────────────────


class TestCASCache:

    def test_get_set(self) -> None:
        cache = CASCache()
        cache.set("a", "hash_a")
        assert cache.get("a") == "hash_a"
        assert cache.get("missing") is None

    def test_initial_data(self) -> None:
        cache = CASCache(initial={"x": "hx"})
        assert cache.get("x") == "hx"

    def test_invalidate(self) -> None:
        cache = CASCache(initial={"a": "ha", "b": "hb"})
        cache.invalidate("a")
        assert cache.get("a") is None
        assert cache.get("b") == "hb"

    def test_invalidate_set(self) -> None:
        cache = CASCache(initial={"a": "ha", "b": "hb", "c": "hc"})
        cache.invalidate_set({"a", "c"})
        assert cache.get("a") is None
        assert cache.get("b") == "hb"
        assert cache.get("c") is None

    def test_as_dict(self) -> None:
        cache = CASCache(initial={"a": "ha"})
        d = cache.as_dict()
        assert d == {"a": "ha"}

    def test_stats(self) -> None:
        cache = CASCache()
        cache.get("x")  # miss
        cache.set("x", "hx")
        cache.get("x")  # hit
        s = cache.stats
        assert s["hits"] >= 1
        assert s["misses"] >= 1


# ── Q-020: CAS Verification ───────────────────────────────────────────


class TestVerifyCasIntegrity:

    def test_passes_after_build(self) -> None:
        g = _make_graph0(
            ("a", "h1", "f.py", "function", 1),
            ("b", "h2", "f.py", "function", 5),
        )
        wf = _make_workflow(("a", "b"))
        hashes = build_dependency_hashes(g, wf)
        g.update_dependency_hashes(hashes)
        result = verify_cas_integrity(g, wf)
        assert isinstance(result, CASVerificationResult)
        assert result.passed

    def test_detects_tampering(self) -> None:
        g = _make_graph0(
            ("a", "h1", "f.py", "function", 1),
            ("b", "h2", "f.py", "function", 5),
        )
        wf = _make_workflow(("a", "b"))
        hashes = build_dependency_hashes(g, wf)
        g.update_dependency_hashes(hashes)
        # Tamper with one hash
        g.get_node("a").dependency_hash = "tampered"
        result = verify_cas_integrity(g, wf)
        assert not result.passed
        assert "a" in result.mismatches

    def test_result_to_dict(self) -> None:
        r = CASVerificationResult(passed=True, total_nodes=5, checked=5)
        d = r.to_dict()
        assert d["passed"] is True


# ── Q-021: CAS Explain ────────────────────────────────────────────────


class TestExplainCas:

    def test_basic_explain(self) -> None:
        g = _make_graph0(
            ("a", "h1", "f.py", "function", 1),
            ("b", "h2", "f.py", "function", 5),
        )
        wf = _make_workflow(("a", "b"))
        info = explain_cas("a", g, wf)
        assert isinstance(info, CASExplainInfo)
        assert info.node_id == "a"
        assert "b" in info.direct_callees

    def test_explain_to_dict(self) -> None:
        info = CASExplainInfo(node_id="a", body_hash="bh")
        d = info.to_dict()
        assert d["node_id"] == "a"
