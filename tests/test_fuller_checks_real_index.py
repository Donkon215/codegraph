"""Function-level checks against a real index.

The index is built with build_all_indexes, the same writer the rest of the suite
uses, and the function-level checks are NOT stubbed, so the path that reads
codegraph.db is exercised.
"""

from __future__ import annotations

from codegraph.architecture_graph import ArchitectureGraph
from codegraph.architecture_simulator import simulate_changes
from codegraph.index import build_all_indexes
from codegraph.models.graph0 import Graph0, Graph0Node
from codegraph.models.graph1 import Graph1
from codegraph.models.workflow import Workflow, WorkflowEdge

A = "mod_a.py::a"
B = "mod_b.py::b"
C = "mod_c.py::c"


class _FakeGraph:
    """Minimal stand-in for ArchitectureGraph: only the fields the sandbox reads."""

    def __init__(self, node_ids, edges):
        self.nodes = [{"id": nid} for nid in node_ids]
        self.edges = [dict(e) for e in edges]
        self.adj_out = {}
        for e in edges:
            self.adj_out.setdefault(e["source"], set()).add(e["target"])


def _build_index(root):
    """Index with two functions and one call edge B -> A."""
    g0 = Graph0()
    for nid, file in ((A, "mod_a.py"), (B, "mod_b.py")):
        g0.add_node(Graph0Node(id=nid, body_hash="h", file=file, type="function", line=1))
    wf = Workflow()
    wf.add_edge(WorkflowEdge(source=B, target=A, edge_type="call", confidence="static"))
    build_all_indexes(g0, Graph1(), wf, root)


def _use_graph(monkeypatch, node_ids):
    graph = _FakeGraph(node_ids, [{"source": B, "target": A, "edge_type": "call"}])
    monkeypatch.setattr(ArchitectureGraph, "load", staticmethod(lambda root: graph))


def test_real_index_cycle_is_reject(monkeypatch, tmp_path):
    _build_index(tmp_path)
    _use_graph(monkeypatch, [A, B])

    result = simulate_changes(tmp_path, [{"change": "add_edge", "node": A, "target": B}])

    assert result["function_checks_available"] is True
    assert result["verdict"] == "REJECT"
    assert any(r.startswith("REJECT new_cycle") for r in result["reasons"])


def test_unknown_id_is_held_not_checked(monkeypatch, tmp_path):
    # Gate 1: an id missing from the index must not become a phantom node.
    _build_index(tmp_path)
    _use_graph(monkeypatch, [A, B, "ghost.py::z"])

    result = simulate_changes(tmp_path, [{"change": "add_edge", "node": A, "target": "ghost.py::z"}])

    assert result["function_checks_available"] is False
    assert result["simulated"] is False
    assert result["verdict"] == "REVIEW"
    assert any("ids not in the function-level index: ghost.py::z" in r for r in result["reasons"])


def test_subsystem_only_id_is_named_as_such(monkeypatch, tmp_path):
    # C is a real subsystem-graph node but not a function-level id. Even outside the sandbox
    # partition, the reason must name the id and the space it belongs to.
    _build_index(tmp_path)
    _use_graph(monkeypatch, [A, B, C])  # C is isolated, so it lies outside the partition

    result = simulate_changes(tmp_path, [{"change": "add_edge", "node": A, "target": C}])

    assert result["function_checks_available"] is False
    reasons = [r for r in result["reasons"] if "function-level index" in r]
    assert len(reasons) == 1, result["reasons"]
    assert C in reasons[0]                       # the id is named
    assert "function-level index" in reasons[0]  # the space it failed to resolve in is named
    assert "subsystem-graph ids" in reasons[0]   # and the space it actually belongs to
