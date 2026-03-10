"""Tests for codegraph.risk_metrics — risk scoring and structural metrics."""

import sqlite3
from unittest.mock import MagicMock

import pytest

from codegraph.risk_metrics import (
    NodeMetrics,
    RiskLevel,
    RiskReport,
    compute_risk_metrics,
    check_dependency_limits,
    _approximate_betweenness,
)


def _make_index_mock(nodes, callers, callees):
    """Create a mock index with in-memory SQLite tables."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE nodes (node_id TEXT, id TEXT, file TEXT, type TEXT, line INTEGER, body_hash TEXT, dep_hash TEXT)")
    conn.execute("CREATE TABLE callers (node_id TEXT, caller_id TEXT)")
    conn.execute("CREATE TABLE callees (node_id TEXT, callee_id TEXT)")

    for nid in nodes:
        conn.execute("INSERT INTO nodes (node_id, id) VALUES (?, ?)", (nid, nid))
    for nid, caller in callers:
        conn.execute("INSERT INTO callers VALUES (?, ?)", (nid, caller))
    for nid, callee in callees:
        conn.execute("INSERT INTO callees VALUES (?, ?)", (nid, callee))

    mock = MagicMock()
    mock._conn = conn
    mock._get_conn.return_value = conn
    return mock


class TestNodeMetrics:
    def test_to_dict(self):
        m = NodeMetrics(node_id="a::f", fan_in=3, fan_out=5, degree=8)
        d = m.to_dict()
        assert d["node_id"] == "a::f"
        assert d["fan_in"] == 3
        assert d["fan_out"] == 5
        assert d["degree"] == 8

    def test_risk_level_default(self):
        m = NodeMetrics(node_id="x")
        assert m.risk_level == RiskLevel.LOW


class TestRiskReport:
    def test_empty_report(self):
        r = RiskReport()
        d = r.to_dict()
        assert d["total_nodes"] == 0
        assert d["avg_fan_in"] == 0

    def test_format(self):
        r = RiskReport(total_nodes=10)
        text = r.format()
        assert "10 nodes" in text


class TestComputeRiskMetrics:
    def test_empty_graph(self):
        idx = _make_index_mock([], [], [])
        report = compute_risk_metrics(idx)
        assert report.total_nodes == 0

    def test_simple_graph(self):
        idx = _make_index_mock(
            ["a", "b", "c"],
            [("b", "a")],          # b is called by a
            [("a", "b"), ("a", "c")],  # a calls b and c
        )
        report = compute_risk_metrics(idx)
        assert report.total_nodes == 3
        assert report.max_fan_out == 2

    def test_risk_levels_assigned(self):
        nodes = [f"n{i}" for i in range(20)]
        callees = []
        # Make node n0 call everything
        for i in range(1, 20):
            callees.append(("n0", f"n{i}"))
        callers = [(f"n{i}", "n0") for i in range(1, 20)]

        idx = _make_index_mock(nodes, callers, callees)
        report = compute_risk_metrics(idx)
        assert report.total_nodes == 20
        # n0 should be highest risk
        assert report.node_metrics[0].node_id == "n0"


class TestCheckDependencyLimits:
    def test_no_rules(self):
        idx = _make_index_mock(["a"], [], [])
        violations = check_dependency_limits(idx, [])
        assert violations == []

    def test_fan_out_exceeded(self):
        idx = _make_index_mock(
            ["a", "b", "c", "d"],
            [],
            [("a", "b"), ("a", "c"), ("a", "d")],
        )
        rule = MagicMock()
        rule.type = "dependency_limit"
        rule.id = "rule_001"
        rule.source = "a"
        rule.source_arch_layer = None
        rule.max_fan_in = None
        rule.max_fan_out = 2

        violations = check_dependency_limits(idx, [rule])
        assert len(violations) == 1
        assert violations[0]["metric"] == "fan_out"
        assert violations[0]["actual"] == 3

    def test_within_limits(self):
        idx = _make_index_mock(
            ["a", "b"],
            [],
            [("a", "b")],
        )
        rule = MagicMock()
        rule.type = "dependency_limit"
        rule.id = "rule_001"
        rule.source = "a"
        rule.source_arch_layer = None
        rule.max_fan_in = None
        rule.max_fan_out = 5

        violations = check_dependency_limits(idx, [rule])
        assert len(violations) == 0


class TestApproximateBetweenness:
    def test_empty_graph(self):
        result = _approximate_betweenness([], {}, sample_size=10)
        assert result == {}

    def test_linear_path(self):
        adj = {"a": ["b"], "b": ["c"]}
        result = _approximate_betweenness(["a", "b", "c"], adj, sample_size=3)
        # b should have highest betweenness (it's in the middle)
        assert result.get("b", 0) >= result.get("a", 0)
