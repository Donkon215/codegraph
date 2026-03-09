"""Tests for codegraph.subsystem — community detection and clustering."""

import sqlite3
from unittest.mock import MagicMock

import pytest

from codegraph.subsystem import (
    Subsystem,
    SubsystemCoupling,
    SubsystemReport,
    detect_subsystems,
    _derive_subsystem_name,
)


def _make_index(callees):
    """Create mock index with callees table."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE callees (node_id TEXT, callee_id TEXT)")
    for nid, callee in callees:
        conn.execute("INSERT INTO callees VALUES (?, ?)", (nid, callee))
    mock = MagicMock()
    mock._conn = conn
    return mock


def _make_graph0(nodes):
    """Create mock graph0 with nodes list."""
    mock = MagicMock()
    node_objs = []
    for n in nodes:
        obj = MagicMock()
        obj.id = n["id"]
        obj.file = n["file"]
        obj.type = n.get("type", "function")
        node_objs.append(obj)
    mock.nodes = node_objs
    return mock


class TestSubsystem:
    def test_to_dict(self):
        ss = Subsystem(
            name="core",
            nodes=["a.py::f", "a.py::g"],
            files=["a.py"],
            internal_edges=3,
            external_edges=1,
            cohesion=0.75,
        )
        d = ss.to_dict()
        assert d["name"] == "core"
        assert d["node_count"] == 2
        assert d["cohesion"] == 0.75


class TestSubsystemCoupling:
    def test_to_dict(self):
        c = SubsystemCoupling("a", "b", 5, 0.3)
        d = c.to_dict()
        assert d["subsystem_a"] == "a"
        assert d["edge_count"] == 5


class TestSubsystemReport:
    def test_empty_report(self):
        r = SubsystemReport()
        d = r.to_dict()
        assert d["total_subsystems"] == 0
        assert d["modularity_score"] == 0

    def test_format(self):
        r = SubsystemReport(
            subsystems=[Subsystem("x", ["n1"], ["f1"], 1, 0, 1.0)],
            modularity_score=0.5,
        )
        text = r.format()
        assert "1 subsystem" in text.lower() or "Subsystem" in text
        assert "0.500" in text


class TestDeriveSubsystemName:
    def test_single_file(self):
        name = _derive_subsystem_name(["codegraph/models/graph0.py"])
        assert "codegraph/models" in name or "graph0" in name

    def test_common_prefix(self):
        name = _derive_subsystem_name(["src/utils/a.py", "src/utils/b.py"])
        assert "src/utils" in name

    def test_empty(self):
        name = _derive_subsystem_name([])
        assert name == "unknown"


class TestDetectSubsystems:
    def test_trivial_single_file(self):
        """All nodes in one file -> one subsystem."""
        graph0 = _make_graph0([
            {"id": "a.py::f", "file": "a.py"},
            {"id": "a.py::g", "file": "a.py"},
        ])
        index = _make_index([("a.py::f", "a.py::g")])
        report = detect_subsystems(graph0, index, min_size=1)
        assert len(report.subsystems) >= 1

    def test_two_clusters(self):
        """Two separate clusters should be detected."""
        nodes = [
            {"id": "a.py::f1", "file": "a.py"},
            {"id": "a.py::f2", "file": "a.py"},
            {"id": "b.py::g1", "file": "b.py"},
            {"id": "b.py::g2", "file": "b.py"},
        ]
        callees = [
            ("a.py::f1", "a.py::f2"),
            ("a.py::f2", "a.py::f1"),
            ("b.py::g1", "b.py::g2"),
            ("b.py::g2", "b.py::g1"),
        ]
        graph0 = _make_graph0(nodes)
        index = _make_index(callees)
        report = detect_subsystems(graph0, index, min_size=1)
        assert len(report.subsystems) >= 2

    def test_min_size_filter(self):
        """Subsystems smaller than min_size should be filtered."""
        graph0 = _make_graph0([
            {"id": "a.py::f", "file": "a.py"},
        ])
        index = _make_index([])
        report = detect_subsystems(graph0, index, min_size=5)
        assert len(report.subsystems) == 0

    def test_empty_graph(self):
        graph0 = _make_graph0([])
        index = _make_index([])
        report = detect_subsystems(graph0, index)
        assert len(report.subsystems) == 0
