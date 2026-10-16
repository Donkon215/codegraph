from __future__ import annotations

import copy

from codegraph.architecture_graph import ArchitectureGraph
from codegraph.architecture_simulator import simulate_change, simulate_changes


class _FakeGraph:
    """Minimal stand-in for ArchitectureGraph: only the fields the simulator path reads."""

    def __init__(self, node_ids, edges):
        self.nodes = [{"id": nid} for nid in node_ids]
        self.edges = [dict(e) for e in edges]
        self.adj_out = {}
        for e in edges:
            self.adj_out.setdefault(e["source"], set()).add(e["target"])


_NODES = ["ring.py::A", "ring.py::B", "ring.py::C", "ring.py::D"]
# A closed cycle: removing one edge should reduce the cycle count.
_EDGES = [
    {"source": "ring.py::A", "target": "ring.py::B", "edge_type": "call"},
    {"source": "ring.py::B", "target": "ring.py::C", "edge_type": "call"},
    {"source": "ring.py::C", "target": "ring.py::D", "edge_type": "call"},
    {"source": "ring.py::D", "target": "ring.py::A", "edge_type": "call"},
]


def _use_graph(monkeypatch, graph):
    monkeypatch.setattr(ArchitectureGraph, "load", staticmethod(lambda root: graph))


def _use_fuller(monkeypatch, *, available=True, blocking=False, advisory=False, reasons=()):
    result = {
        "available": available,
        "blocking": blocking,
        "advisory": advisory,
        "reasons": list(reasons),
        "blast_radius": 0,
    }
    monkeypatch.setattr(
        "codegraph.architecture_simulator._fuller_checks",
        lambda root, changes, sandbox_ids, graph_ids: dict(result),
    )


def test_score_delta_reflects_mutation(monkeypatch, tmp_path):
    graph = _FakeGraph(_NODES, _EDGES)
    _use_graph(monkeypatch, graph)
    _use_fuller(monkeypatch)

    result = simulate_change(tmp_path, node="ring.py::A", change="remove_edge", target="ring.py::B")

    assert result["status"] == "simulated"
    assert result["predicted_subsystem_score"] != result["baseline_subsystem_score"]
    assert result["score_delta"] != 0
    assert result["score_delta"] == round(
        result["predicted_subsystem_score"] - result["baseline_subsystem_score"], 4
    )


def test_coupling_delta_reflects_added_edge(monkeypatch, tmp_path):
    # A chord A->C raises fan-out at A and fan-in at C, so coupling must rise.
    graph = _FakeGraph(_NODES, _EDGES)
    _use_graph(monkeypatch, graph)

    result = simulate_change(tmp_path, node="ring.py::A", change="add_edge", target="ring.py::C")

    assert result["coupling_delta"] > 0


def test_noop_change_has_zero_deltas(monkeypatch, tmp_path):
    # Removing an edge that does not exist changes nothing.
    graph = _FakeGraph(_NODES, _EDGES)
    _use_graph(monkeypatch, graph)
    _use_fuller(monkeypatch)

    result = simulate_change(tmp_path, node="ring.py::A", change="remove_edge", target="ring.py::Z")

    assert result["status"] == "simulated"
    assert result["score_delta"] == 0
    assert result["coupling_delta"] == 0
    assert result["verdict"] == "REVIEW"


def test_simulation_leaves_graph_and_disk_unchanged(monkeypatch, tmp_path):
    graph = _FakeGraph(_NODES, _EDGES)
    _use_graph(monkeypatch, graph)
    nodes_before = copy.deepcopy(graph.nodes)
    edges_before = copy.deepcopy(graph.edges)
    adj_before = copy.deepcopy(graph.adj_out)
    files_before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))

    simulate_change(tmp_path, node="ring.py::A", change="remove_edge", target="ring.py::B")

    assert graph.nodes == nodes_before
    assert graph.edges == edges_before
    assert graph.adj_out == adj_before
    assert sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*")) == files_before


# Acyclic chain: adding D -> A creates the first cycle.
_CHAIN_NODES = ["chain.py::A", "chain.py::B", "chain.py::C", "chain.py::D"]
_CHAIN_EDGES = [
    {"source": "chain.py::A", "target": "chain.py::B", "edge_type": "call"},
    {"source": "chain.py::B", "target": "chain.py::C", "edge_type": "call"},
    {"source": "chain.py::C", "target": "chain.py::D", "edge_type": "call"},
]


def test_plan_adding_cycle_is_rejected_with_reason(monkeypatch, tmp_path):
    _use_graph(monkeypatch, _FakeGraph(_CHAIN_NODES, _CHAIN_EDGES))

    result = simulate_changes(
        tmp_path,
        [{"change": "add_edge", "node": "chain.py::D", "target": "chain.py::A"}],
    )

    assert result["verdict"] == "REJECT"
    assert any("new cycle" in reason for reason in result["reasons"])


def test_plan_breaking_cycle_is_accepted(monkeypatch, tmp_path):
    _use_graph(monkeypatch, _FakeGraph(_NODES, _EDGES))
    _use_fuller(monkeypatch)

    result = simulate_changes(
        tmp_path,
        [{"change": "remove_edge", "node": "ring.py::A", "target": "ring.py::B"}],
    )

    assert result["verdict"] == "ACCEPT"
    assert result["reasons"]


def test_empty_plan_is_review(monkeypatch, tmp_path):
    _use_graph(monkeypatch, _FakeGraph(_NODES, _EDGES))

    result = simulate_changes(tmp_path, [])

    assert result["verdict"] == "REVIEW"
    assert any("empty" in reason for reason in result["reasons"])
    assert result["simulated"] is False


def test_change_outside_partition_is_review_with_reason(monkeypatch, tmp_path):
    _use_graph(monkeypatch, _FakeGraph(_CHAIN_NODES, _CHAIN_EDGES))

    result = simulate_changes(
        tmp_path,
        [{"change": "add_edge", "node": "chain.py::D", "target": "ghost.py::Z"}],
    )

    assert result["verdict"] == "REVIEW"
    assert any("outside the sandbox partition" in reason for reason in result["reasons"])
    assert result["partition_limited"] is True


def test_crash_is_reported_as_not_simulated(monkeypatch, tmp_path):
    def _boom(root):
        raise RuntimeError("graph unavailable")

    monkeypatch.setattr(ArchitectureGraph, "load", staticmethod(_boom))

    result = simulate_changes(
        tmp_path,
        [{"change": "add_edge", "node": "chain.py::D", "target": "chain.py::A"}],
    )

    assert result["simulated"] is False
    assert result["verdict"] == "REVIEW"
    assert any("could not simulate" in reason for reason in result["reasons"])


def test_no_index_holds_accept_back_to_review(monkeypatch, tmp_path):
    # Sandbox says ACCEPT, but the function-level checks cannot run without an index.
    _use_graph(monkeypatch, _FakeGraph(_NODES, _EDGES))

    result = simulate_changes(
        tmp_path,
        [{"change": "remove_edge", "node": "ring.py::A", "target": "ring.py::B"}],
    )

    assert result["verdict"] == "REVIEW"
    assert result["simulated"] is False
    assert any("function-level checks did not run" in r for r in result["reasons"])


def test_cycle_reject_is_not_softened_without_index(monkeypatch, tmp_path):
    _use_graph(monkeypatch, _FakeGraph(_CHAIN_NODES, _CHAIN_EDGES))

    result = simulate_changes(
        tmp_path,
        [{"change": "add_edge", "node": "chain.py::D", "target": "chain.py::A"}],
    )

    assert result["verdict"] == "REJECT"


def test_blocking_function_level_violation_is_reject(monkeypatch, tmp_path):
    _use_graph(monkeypatch, _FakeGraph(_NODES, _EDGES))
    _use_fuller(monkeypatch, blocking=True, reasons=["forbidden_path: A -> B"])

    result = simulate_changes(
        tmp_path,
        [{"change": "remove_edge", "node": "ring.py::A", "target": "ring.py::B"}],
    )

    assert result["verdict"] == "REJECT"
    assert "forbidden_path: A -> B" in result["reasons"]


def test_rewire_is_held_for_review(monkeypatch, tmp_path):
    _use_graph(monkeypatch, _FakeGraph(_NODES, _EDGES))

    result = simulate_changes(
        tmp_path,
        [{"change": "rewire_edge", "node": "ring.py::A", "target": "ring.py::C"}],
    )

    assert result["verdict"] == "REVIEW"
    assert result["simulated"] is False
    assert any("rewire_edge is not covered" in r for r in result["reasons"])


def test_advisory_violation_holds_accept_to_review(monkeypatch, tmp_path):
    # A generic layer rule flags the plan: advisory, so an ACCEPT is held to REVIEW, not REJECT.
    _use_graph(monkeypatch, _FakeGraph(_NODES, _EDGES))
    _use_fuller(monkeypatch, advisory=True, reasons=["advisory layer_violation: ui -> db"])

    result = simulate_changes(
        tmp_path,
        [{"change": "remove_edge", "node": "ring.py::A", "target": "ring.py::B"}],
    )

    assert result["verdict"] == "REVIEW"
    assert any("generic advisory checks" in r for r in result["reasons"])
