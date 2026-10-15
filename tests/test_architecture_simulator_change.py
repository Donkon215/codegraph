from __future__ import annotations

import copy

from codegraph.architecture_graph import ArchitectureGraph
from codegraph.architecture_simulator import simulate_change


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


def test_score_delta_reflects_mutation(monkeypatch, tmp_path):
    graph = _FakeGraph(_NODES, _EDGES)
    _use_graph(monkeypatch, graph)

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
    graph = _FakeGraph(_NODES, _EDGES)
    _use_graph(monkeypatch, graph)

    result = simulate_change(tmp_path, node="ring.py::A", change="none", target="")

    assert result["status"] == "simulated"
    assert result["score_delta"] == 0
    assert result["coupling_delta"] == 0


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
