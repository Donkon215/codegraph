"""Tests for codegraph.refactor — refactoring suggestions engine."""

import sqlite3
from unittest.mock import MagicMock

import pytest

from codegraph.refactor import (
    CycleInfo,
    GodModule,
    CouplingPair,
    RefactorSuggestion,
    RefactorReport,
    detect_cycles,
    detect_god_modules,
    detect_coupling,
    analyze_refactoring,
)


def _make_index_mock(callees, node_files=None):
    """Create a mock index with in-memory SQLite tables."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE nodes (node_id TEXT, id TEXT, file TEXT, type TEXT, line INTEGER, body_hash TEXT, dep_hash TEXT)")
    conn.execute("CREATE TABLE callers (node_id TEXT, caller_id TEXT)")
    conn.execute("CREATE TABLE callees (node_id TEXT, callee_id TEXT)")

    all_nodes = set()
    for src, dst in callees:
        all_nodes.add(src)
        all_nodes.add(dst)

    if node_files:
        for nid, fpath in node_files.items():
            conn.execute("INSERT INTO nodes (node_id, id, file) VALUES (?, ?, ?)", (nid, nid, fpath))
            all_nodes.discard(nid)

    for nid in all_nodes:
        conn.execute("INSERT INTO nodes (node_id, id, file) VALUES (?, ?, ?)", (nid, nid, "unknown"))

    for src, dst in callees:
        conn.execute("INSERT INTO callees VALUES (?, ?)", (src, dst))
        conn.execute("INSERT INTO callers VALUES (?, ?)", (dst, src))

    mock = MagicMock()
    mock._conn = conn
    mock._get_conn.return_value = conn
    return mock


def _make_graph0(files_nodes):
    """Create a mock graph0 with file-node mappings."""
    mock = MagicMock()
    nodes = []
    for fpath, node_ids in files_nodes.items():
        for nid in node_ids:
            node = MagicMock()
            node.id = nid
            node.file = fpath
            node.type = "function"
            nodes.append(node)
    mock.nodes = nodes
    return mock


class TestCycleInfo:
    def test_to_dict(self):
        c = CycleInfo(nodes=["a", "b", "c"], files_involved=["x.py"])
        d = c.to_dict()
        assert d["size"] == 3
        assert d["nodes"] == ["a", "b", "c"]


class TestDetectCycles:
    def test_no_cycles(self):
        idx = _make_index_mock([("a", "b"), ("b", "c")])
        cycles = detect_cycles(idx)
        assert len(cycles) == 0

    def test_simple_cycle(self):
        idx = _make_index_mock([("a", "b"), ("b", "c"), ("c", "a")])
        cycles = detect_cycles(idx)
        assert len(cycles) == 1
        assert cycles[0].size == 3

    def test_two_cycles(self):
        idx = _make_index_mock([
            ("a", "b"), ("b", "a"),
            ("c", "d"), ("d", "c"),
        ])
        cycles = detect_cycles(idx)
        assert len(cycles) == 2


class TestDetectGodModules:
    def test_no_god_modules(self):
        g0 = _make_graph0({"a.py": ["a1", "a2", "a3"]})
        result = detect_god_modules(g0, threshold=5)
        assert len(result) == 0

    def test_god_module_detected(self):
        g0 = _make_graph0({"big.py": [f"n{i}" for i in range(40)]})
        result = detect_god_modules(g0, threshold=30)
        assert len(result) == 1
        assert result[0].node_count == 40

    def test_threshold_exact(self):
        g0 = _make_graph0({"x.py": [f"n{i}" for i in range(30)]})
        result = detect_god_modules(g0, threshold=30)
        assert len(result) == 1


class TestDetectCoupling:
    def test_no_coupling(self):
        idx = _make_index_mock(
            [("a.py::f1", "a.py::f2")],
            {"a.py::f1": "a.py", "a.py::f2": "a.py"},
        )
        result = detect_coupling(idx, threshold=1)
        assert len(result) == 0  # Same file — not cross-module

    def test_high_coupling(self):
        callees = [(f"a.py::f{i}", f"b.py::g{i}") for i in range(15)]
        node_files = {}
        for i in range(15):
            node_files[f"a.py::f{i}"] = "a.py"
            node_files[f"b.py::g{i}"] = "b.py"
        idx = _make_index_mock(callees, node_files)
        result = detect_coupling(idx, threshold=10)
        assert len(result) == 1
        assert result[0].shared_edges >= 10


class TestRefactorReport:
    def test_empty_report(self):
        r = RefactorReport()
        d = r.to_dict()
        assert d["summary"]["total_cycles"] == 0

    def test_format(self):
        r = RefactorReport(
            cycles=[CycleInfo(nodes=["a", "b"], files_involved=["x.py"])],
        )
        text = r.format()
        assert "Cycles: 1" in text


class TestAnalyzeRefactoring:
    def test_full_analysis(self):
        callees = [("a", "b"), ("b", "a")]
        idx = _make_index_mock(callees, {"a": "big.py", "b": "big.py"})
        g0 = _make_graph0({"big.py": [f"n{i}" for i in range(35)]})

        report = analyze_refactoring(idx, g0, god_module_threshold=30)
        assert report.to_dict()["summary"]["total_cycles"] == 1
        assert report.to_dict()["summary"]["total_god_modules"] == 1
