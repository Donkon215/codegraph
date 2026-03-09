"""Tests for codegraph.arch_health — architecture health scoring."""

import sqlite3
from unittest.mock import MagicMock

import pytest

from codegraph.arch_health import (
    ModuleHealth,
    ArchHealthReport,
    compute_health,
)


def _make_index(nodes, callers, callees):
    """Create mock index with in-memory SQLite tables."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE nodes (node_id TEXT, id TEXT, file TEXT, type TEXT, line INTEGER, body_hash TEXT, dep_hash TEXT)")
    conn.execute("CREATE TABLE callers (node_id TEXT, caller_id TEXT)")
    conn.execute("CREATE TABLE callees (node_id TEXT, callee_id TEXT)")

    for nid in nodes:
        conn.execute("INSERT INTO nodes (node_id) VALUES (?)", (nid,))
    for nid, caller in callers:
        conn.execute("INSERT INTO callers VALUES (?, ?)", (nid, caller))
    for nid, callee in callees:
        conn.execute("INSERT INTO callees VALUES (?, ?)", (nid, callee))

    mock = MagicMock()
    mock._conn = conn
    return mock


def _make_graph0(nodes):
    """Create mock graph0."""
    mock = MagicMock()
    node_objs = []
    for n in nodes:
        obj = MagicMock()
        obj.id = n["id"]
        obj.file = n["file"]
        obj.type = n.get("type", "function")
        obj.body_hash = n.get("body_hash", "abc123")
        node_objs.append(obj)
    mock.nodes = node_objs
    return mock


class TestModuleHealth:
    def test_to_dict(self):
        m = ModuleHealth(
            file="a.py",
            node_count=10,
            avg_risk=0.3,
            max_risk=0.8,
            fan_in_total=5,
            fan_out_total=3,
            in_cycle=False,
            health_score=0.85,
        )
        d = m.to_dict()
        assert d["file"] == "a.py"
        assert d["health_score"] == 0.85

    def test_defaults(self):
        m = ModuleHealth(file="b.py")
        assert m.node_count == 0
        assert m.issues == []


class TestArchHealthReport:
    def test_grade_mapping(self):
        r = ArchHealthReport(overall_score=0.95)
        assert r.to_dict()["grade"] == "A"

        r2 = ArchHealthReport(overall_score=0.45)
        assert r2.to_dict()["grade"] == "F"

        r3 = ArchHealthReport(overall_score=0.75)
        assert r3.to_dict()["grade"] == "C"

    def test_to_dict(self):
        r = ArchHealthReport(overall_score=0.82, cycle_count=1)
        d = r.to_dict()
        assert d["overall_score"] == 0.82
        assert d["grade"] == "B"
        assert d["cycle_count"] == 1

    def test_format(self):
        r = ArchHealthReport(overall_score=0.9, cycle_count=0)
        text = r.format()
        assert "A" in text
        assert "90.0%" in text


class TestComputeHealth:
    def test_simple_healthy(self):
        """A simple graph with no cycles should score well."""
        nodes = ["a.py::f", "a.py::g", "b.py::h"]
        callers = [("b.py::h", "a.py::f")]
        callees = [("a.py::f", "b.py::h")]
        graph0 = _make_graph0([
            {"id": "a.py::f", "file": "a.py"},
            {"id": "a.py::g", "file": "a.py"},
            {"id": "b.py::h", "file": "b.py"},
        ])
        index = _make_index(nodes, callers, callees)
        report = compute_health(graph0, index)
        assert report.overall_score > 0.5
        assert report._grade() in ("A", "B", "C")

    def test_empty_graph(self):
        graph0 = _make_graph0([])
        index = _make_index([], [], [])
        report = compute_health(graph0, index)
        assert report.overall_score == 1.0
        assert report._grade() == "A"

    def test_cyclic_graph_penalized(self):
        """A graph with cycles should have a lower score."""
        nodes = ["a.py::f", "b.py::g"]
        callers = [
            ("a.py::f", "b.py::g"),
            ("b.py::g", "a.py::f"),
        ]
        callees = [
            ("a.py::f", "b.py::g"),
            ("b.py::g", "a.py::f"),
        ]
        graph0 = _make_graph0([
            {"id": "a.py::f", "file": "a.py"},
            {"id": "b.py::g", "file": "b.py"},
        ])
        index = _make_index(nodes, callers, callees)
        report = compute_health(graph0, index)
        # Cycles should reduce the score
        assert report.cycle_count >= 1 or report.overall_score < 1.0
