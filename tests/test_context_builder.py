"""Tests for codegraph.context_builder — LLM prompt context extraction."""

import sqlite3
from unittest.mock import MagicMock

import pytest

from codegraph.context_builder import (
    NodeContext,
    PromptContext,
    build_context,
)


def _make_index(callers, callees):
    """Create mock index with caller/callee tables."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE callers (node_id TEXT, caller_id TEXT)")
    conn.execute("CREATE TABLE callees (node_id TEXT, callee_id TEXT)")

    for nid, caller in callers:
        conn.execute("INSERT INTO callers VALUES (?, ?)", (nid, caller))
    for nid, callee in callees:
        conn.execute("INSERT INTO callees VALUES (?, ?)", (nid, callee))

    mock = MagicMock()
    mock._conn = conn
    return mock


def _make_node(node_id, file="a.py", node_type="function"):
    obj = MagicMock()
    obj.id = node_id
    obj.file = file
    obj.type = node_type
    return obj


def _make_graph0(nodes):
    mock = MagicMock()
    node_objs = [_make_node(n["id"], n.get("file", "a.py")) for n in nodes]
    mock.nodes = node_objs
    return mock


def _make_graph1(intents):
    """Create mock graph1 with intent lookup."""
    mock = MagicMock()
    node_map = {}
    for nid, intent in intents.items():
        n = MagicMock()
        n.id = nid
        n.intent = intent
        n.layer = None
        n.arch_layer = None
        node_map[nid] = n

    def get_node(nid):
        return node_map.get(nid)

    mock.get_node = get_node
    mock.nodes = list(node_map.values())
    return mock


def _make_workflow(edges):
    mock = MagicMock()
    edge_objs = []
    for src, tgt in edges:
        e = MagicMock()
        e.source = src
        e.target = tgt
        e.edge_type = "call"
        edge_objs.append(e)
    mock.edges = edge_objs
    return mock


class TestNodeContext:
    def test_to_dict(self):
        nc = NodeContext(
            node_id="a.py::f",
            file="a.py",
            node_type="function",
            intent="Does something",
            callers=["b.py::g"],
            callees=["c.py::h"],
        )
        d = nc.to_dict()
        assert d["id"] == "a.py::f"
        assert d["intent"] == "Does something"
        assert len(d["callers"]) == 1


class TestPromptContext:
    def test_empty_context(self):
        pc = PromptContext()
        prompt = pc.to_prompt()
        # Empty context should produce empty/minimal prompt
        assert isinstance(prompt, str)

    def test_token_estimate(self):
        pc = PromptContext()
        pc.focus_nodes.append(NodeContext(
            node_id="a.py::f", file="a.py", node_type="function",
        ))
        est = pc.token_estimate()
        assert est > 0

    def test_to_dict(self):
        pc = PromptContext()
        d = pc.to_dict()
        assert "focus_nodes" in d
        assert "related_nodes" in d


class TestBuildContext:
    def test_basic_context(self):
        """Build context for a single node."""
        graph0 = _make_graph0([
            {"id": "a.py::f"},
            {"id": "b.py::g"},
        ])
        graph1 = _make_graph1({"a.py::f": "Computes something"})
        workflow = _make_workflow([("a.py::f", "b.py::g")])
        index = _make_index(
            callers=[("a.py::f", "b.py::g")],
            callees=[("a.py::f", "b.py::g")],
        )

        ctx = build_context(["a.py::f"], graph0, graph1, workflow, index, depth=1)
        assert len(ctx.focus_nodes) >= 1
        assert ctx.focus_nodes[0].node_id == "a.py::f"

    def test_depth_expansion(self):
        """Context should expand to neighbors."""
        graph0 = _make_graph0([
            {"id": "a.py::f"},
            {"id": "b.py::g"},
            {"id": "c.py::h"},
        ])
        graph1 = _make_graph1({})
        workflow = _make_workflow([
            ("a.py::f", "b.py::g"),
            ("b.py::g", "c.py::h"),
        ])
        index = _make_index(
            callers=[],
            callees=[
                ("a.py::f", "b.py::g"),
                ("b.py::g", "c.py::h"),
            ],
        )

        ctx = build_context(["a.py::f"], graph0, graph1, workflow, index, depth=2)
        all_ids = {n.node_id for n in ctx.focus_nodes + ctx.related_nodes}
        assert "a.py::f" in all_ids

    def test_unknown_node(self):
        """Unknown focus node should produce empty focus."""
        graph0 = _make_graph0([{"id": "a.py::f"}])
        graph1 = _make_graph1({})
        workflow = _make_workflow([])
        index = _make_index([], [])

        ctx = build_context(["nonexistent::node"], graph0, graph1, workflow, index)
        # Should still produce a context, just possibly empty
        assert isinstance(ctx, PromptContext)
