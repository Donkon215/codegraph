"""Tests for codegraph.visualization — graph visualization export."""

import json
from unittest.mock import MagicMock

import pytest

from codegraph.visualization import (
    VisNode,
    VisEdge,
    VisGraph,
    build_vis_graph,
    export_mermaid,
    export_html_report,
    save_visualization,
)


def _make_graph0(nodes_data):
    """Create a mock Graph0."""
    mock = MagicMock()
    nodes = []
    for nid, fpath, ntype in nodes_data:
        node = MagicMock()
        node.id = nid
        node.file = fpath
        node.type = ntype
        nodes.append(node)
    mock.nodes = nodes
    return mock


def _make_graph1(intents):
    """Create a mock Graph1."""
    mock = MagicMock()
    nodes = []
    for nid, intent, layer in intents:
        node = MagicMock()
        node.id = nid
        node.intent = intent
        node.layer = layer
        nodes.append(node)
    mock.nodes = nodes
    return mock


def _make_workflow(edges_data):
    """Create a mock Workflow."""
    mock = MagicMock()
    edges = []
    for src, tgt in edges_data:
        edge = MagicMock()
        edge.source = src
        edge.target = tgt
        edge.type = "call"
        edges.append(edge)
    mock.edges = edges
    return mock


class TestVisNode:
    def test_to_dict(self):
        n = VisNode(id="a::f", label="f", file="a.py", node_type="function")
        d = n.to_dict()
        assert d["id"] == "a::f"
        assert d["label"] == "f"
        assert d["type"] == "function"


class TestVisEdge:
    def test_to_dict(self):
        e = VisEdge(source="a::f", target="b::g")
        d = e.to_dict()
        assert d["source"] == "a::f"
        assert d["target"] == "b::g"


class TestVisGraph:
    def test_empty(self):
        g = VisGraph()
        d = g.to_dict()
        assert d["nodes"] == []
        assert d["edges"] == []

    def test_to_json(self):
        g = VisGraph(nodes=[VisNode(id="a", label="a")])
        j = g.to_json()
        data = json.loads(j)
        assert len(data["nodes"]) == 1


class TestBuildVisGraph:
    def test_basic_graph(self):
        g0 = _make_graph0([("a::f", "a.py", "function"), ("b::g", "b.py", "function")])
        g1 = _make_graph1([("a::f", "does stuff", 3), ("b::g", "", 3)])
        wf = _make_workflow([("a::f", "b::g")])

        vis = build_vis_graph(g0, g1, wf)
        assert len(vis.nodes) == 2
        assert len(vis.edges) == 1

    def test_filter_file(self):
        g0 = _make_graph0([("a::f", "a.py", "function"), ("b::g", "b.py", "function")])
        g1 = _make_graph1([("a::f", "x", 3), ("b::g", "y", 3)])
        wf = _make_workflow([("a::f", "b::g")])

        vis = build_vis_graph(g0, g1, wf, filter_file="a.py")
        assert len(vis.nodes) == 1
        assert vis.nodes[0].id == "a::f"

    def test_max_nodes(self):
        nodes = [(f"n{i}::f", f"n{i}.py", "function") for i in range(100)]
        intents = [(f"n{i}::f", "", 3) for i in range(100)]
        g0 = _make_graph0(nodes)
        g1 = _make_graph1(intents)
        wf = _make_workflow([])

        vis = build_vis_graph(g0, g1, wf, max_nodes=10)
        assert len(vis.nodes) == 10


class TestExportMermaid:
    def test_basic_mermaid(self):
        g0 = _make_graph0([("a::f", "a.py", "function"), ("b::g", "b.py", "function")])
        g1 = _make_graph1([("a::f", "x", 3), ("b::g", "y", 3)])
        wf = _make_workflow([("a::f", "b::g")])

        mermaid = export_mermaid(g0, g1, wf)
        assert "graph TD" in mermaid
        assert "-->" in mermaid


class TestExportHtmlReport:
    def test_basic_html(self):
        g0 = _make_graph0([("a::f", "a.py", "function")])
        g1 = _make_graph1([("a::f", "x", 3)])
        wf = _make_workflow([])

        html = export_html_report(g0, g1, wf, title="Test Report")
        assert "<html" in html
        assert "Test Report" in html
        assert "d3.v7" in html


class TestSaveVisualization:
    def test_save_json(self, tmp_path):
        g0 = _make_graph0([("a::f", "a.py", "function")])
        g1 = _make_graph1([("a::f", "x", 3)])
        wf = _make_workflow([])

        out_path = tmp_path / "graph.json"
        save_visualization(g0, g1, wf, out_path, fmt="json")
        assert out_path.exists()
        data = json.loads(out_path.read_text())
        assert len(data["nodes"]) == 1

    def test_save_mermaid(self, tmp_path):
        g0 = _make_graph0([("a::f", "a.py", "function")])
        g1 = _make_graph1([("a::f", "x", 3)])
        wf = _make_workflow([])

        out_path = tmp_path / "graph.md"
        save_visualization(g0, g1, wf, out_path, fmt="mermaid")
        assert out_path.exists()
        assert "graph TD" in out_path.read_text()

    def test_save_html(self, tmp_path):
        g0 = _make_graph0([("a::f", "a.py", "function")])
        g1 = _make_graph1([("a::f", "x", 3)])
        wf = _make_workflow([])

        out_path = tmp_path / "graph.html"
        save_visualization(g0, g1, wf, out_path, fmt="html")
        assert out_path.exists()
        assert "<html" in out_path.read_text()

    def test_invalid_format(self, tmp_path):
        g0 = _make_graph0([])
        g1 = _make_graph1([])
        wf = _make_workflow([])

        with pytest.raises(ValueError, match="Unknown format"):
            save_visualization(g0, g1, wf, tmp_path / "x", fmt="invalid")
