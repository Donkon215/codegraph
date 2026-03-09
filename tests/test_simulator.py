"""Tests for codegraph.simulator — change simulation engine."""

import sqlite3
from unittest.mock import MagicMock

import pytest

from codegraph.simulator import (
    SimulatedChange,
    SimViolation,
    SimulationResult,
    simulate_changes,
    simulate_agent_response,
)


def _make_index(callees, nodes=None):
    """Create mock index with callees and nodes tables."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE nodes (node_id TEXT, id TEXT, file TEXT, type TEXT, line INTEGER, body_hash TEXT, dep_hash TEXT)")
    conn.execute("CREATE TABLE callees (node_id TEXT, callee_id TEXT)")
    if nodes:
        for nid in nodes:
            conn.execute("INSERT INTO nodes (node_id) VALUES (?)", (nid,))
    for nid, callee in callees:
        conn.execute("INSERT INTO callees VALUES (?, ?)", (nid, callee))
        # Ensure nodes exist for all referenced nodes
        conn.execute("INSERT OR IGNORE INTO nodes (node_id) VALUES (?)", (nid,))
        conn.execute("INSERT OR IGNORE INTO nodes (node_id) VALUES (?)", (callee,))

    mock = MagicMock()
    mock._conn = conn
    return mock


class TestSimulatedChange:
    def test_to_dict(self):
        c = SimulatedChange(action="add_edge", source="a::f", target="b::g")
        d = c.to_dict()
        assert d["action"] == "add_edge"
        assert d["source"] == "a::f"


class TestSimViolation:
    def test_to_dict(self):
        v = SimViolation(
            violation_type="new_cycle",
            severity="high",
            description="Cycle detected",
        )
        d = v.to_dict()
        assert d["type"] == "new_cycle"
        assert d["severity"] == "high"


class TestSimulationResult:
    def test_safe_result(self):
        r = SimulationResult(changes=[], violations=[], safe=True)
        d = r.to_dict()
        assert d["safe"] is True

    def test_unsafe_result(self):
        v = SimViolation("new_cycle", "high", "cycle")
        r = SimulationResult(changes=[], violations=[v], safe=False)
        assert not r.safe


class TestSimulateChanges:
    def test_no_changes(self):
        """Empty changes should be safe."""
        index = _make_index([])
        result = simulate_changes([], index)
        assert result.safe
        assert result.violations == []

    def test_add_edge_no_cycle(self):
        """Adding an edge that doesn't create a cycle should be safe."""
        index = _make_index([("a::f", "b::g")])
        changes = [
            SimulatedChange(action="add_edge", source="b::g", target="c::h"),
        ]
        result = simulate_changes(changes, index)
        assert result.safe

    def test_add_edge_creates_cycle(self):
        """Adding an edge that creates a cycle should be detected."""
        index = _make_index([
            ("a::f", "b::g"),
            ("b::g", "c::h"),
        ])
        changes = [
            SimulatedChange(action="add_edge", source="c::h", target="a::f"),
        ]
        result = simulate_changes(changes, index, check_cycles=True)
        assert result.new_cycle_count > 0

    def test_remove_edge(self):
        """Removing an edge should be safe."""
        index = _make_index([("a::f", "b::g")])
        changes = [
            SimulatedChange(action="remove_edge", source="a::f", target="b::g"),
        ]
        result = simulate_changes(changes, index)
        assert result.safe

    def test_forbidden_pattern(self):
        """Edges matching forbidden patterns should be flagged."""
        index = _make_index([])
        changes = [
            SimulatedChange(action="add_edge", source="tests/a.py::f",
                           target="src/b.py::g"),
        ]
        result = simulate_changes(
            changes, index,
            check_forbidden=True,
            forbidden_patterns=[("tests/*", "src/*")],
        )
        assert not result.safe
        assert any(v.violation_type == "forbidden_path" for v in result.violations)


class TestSimulateAgentResponse:
    def test_empty_response(self):
        """Empty response should produce safe result."""
        index = _make_index([])
        result = simulate_agent_response({"repairs": []}, index)
        assert result.safe

    def test_connect_call_repair(self):
        """A connect_call repair should translate to add_edge."""
        index = _make_index([])
        response = {
            "repairs": [
                {
                    "node": "a.py::f",
                    "action": "connect_call",
                    "target": "b.py::g",
                    "reason": "test",
                }
            ]
        }
        result = simulate_agent_response(response, index)
        assert len(result.changes) == 1
        assert result.changes[0].action == "add_edge"

    def test_no_repairs_key(self):
        """Response without repairs key should be safe."""
        index = _make_index([])
        result = simulate_agent_response({}, index)
        assert result.safe
