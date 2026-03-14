"""Tests for codegraph.subsystem_extractor and architecture_decay."""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock

from codegraph.architecture_decay import detect_architecture_decay
from codegraph.models.graph0 import Graph0, Graph0Node
from codegraph.subsystem_extractor import (
    generate_subsystem_extraction_report,
    propose_refactor_suggestions,
)


def _make_graph0(nodes_data):
    nodes = [
        Graph0Node(id=node_id, body_hash="h", file=file_path, type=node_type, line=1)
        for node_id, file_path, node_type in nodes_data
    ]
    return Graph0(nodes=nodes)


def _make_index(callee_pairs=None, node_ids=None, test_links=None):
    mock = MagicMock()
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE nodes (node_id TEXT, id TEXT, file TEXT, type TEXT, line INTEGER)")
    conn.execute("CREATE TABLE callees (node_id TEXT, callee_id TEXT)")
    conn.execute("CREATE TABLE callers (node_id TEXT, caller_id TEXT)")
    conn.execute("CREATE TABLE tests (test_id TEXT, node_id TEXT)")

    for node_id in node_ids or []:
        conn.execute("INSERT INTO nodes VALUES (?, ?, '', '', 0)", (node_id, node_id))

    for source, target in callee_pairs or []:
        conn.execute("INSERT INTO callees VALUES (?, ?)", (source, target))
        conn.execute("INSERT INTO callers VALUES (?, ?)", (target, source))

    for test_id, node_id in test_links or []:
        conn.execute("INSERT INTO tests VALUES (?, ?)", (test_id, node_id))

    mock._get_conn.return_value = conn
    return mock


def test_decay_detects_extractable_subsystem():
    graph0 = _make_graph0([
        ("trading/data.py::load", "trading/data.py", "function"),
        ("trading/signal.py::compute", "trading/signal.py", "function"),
        ("trading/trade.py::execute", "trading/trade.py", "function"),
        ("app/main.py::run", "app/main.py", "function"),
    ])
    index = _make_index(
        callee_pairs=[
            ("trading/data.py::load", "trading/signal.py::compute"),
            ("trading/signal.py::compute", "trading/trade.py::execute"),
            ("app/main.py::run", "trading/data.py::load"),
        ]
    )

    report = detect_architecture_decay(graph0, index, fan_in_threshold=10, fan_out_threshold=10)
    assert len(report.extractable_subsystems) >= 1


def test_propose_refactor_suggestions_contains_extract_or_split_types():
    graph0 = _make_graph0([
        ("core/a.py::a", "core/a.py", "function"),
        ("core/b.py::b", "core/b.py", "function"),
        ("core/c.py::c", "core/c.py", "function"),
        ("outside/x.py::x", "outside/x.py", "function"),
    ])
    index = _make_index(
        callee_pairs=[
            ("core/a.py::a", "core/b.py::b"),
            ("core/b.py::b", "core/c.py::c"),
            ("outside/x.py::x", "core/a.py::a"),
        ]
    )

    suggestions = propose_refactor_suggestions(graph0, index)
    assert len(suggestions) >= 1
    assert any(suggestion.type in {"extract_subsystem", "split_module", "introduce_interface"}
               for suggestion in suggestions)


def test_generate_subsystem_extraction_report_simulates_suggestions():
    graph0 = _make_graph0([
        ("domain/a.py::a", "domain/a.py", "function"),
        ("domain/b.py::b", "domain/b.py", "function"),
        ("domain/c.py::c", "domain/c.py", "function"),
        ("api/entry.py::entry", "api/entry.py", "function"),
    ])
    index = _make_index(
        callee_pairs=[
            ("domain/a.py::a", "domain/b.py::b"),
            ("domain/b.py::b", "domain/c.py::c"),
            ("api/entry.py::entry", "domain/a.py::a"),
            ("domain/c.py::c", "api/entry.py::entry"),
        ]
    )

    report = generate_subsystem_extraction_report(graph0, index)
    assert "decay_report" in report
    assert "suggestions" in report
    assert len(report["suggestions"]) >= 1
    assert all("simulation_risk_level" in suggestion for suggestion in report["suggestions"]) 
