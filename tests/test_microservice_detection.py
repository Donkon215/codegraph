"""Tests for codegraph.microservice_detector."""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock

from codegraph.microservice_detector import detect_microservice_candidates
from codegraph.models.graph0 import Graph0, Graph0Node


def _make_graph0(nodes_data):
    nodes = [
        Graph0Node(id=node_id, body_hash="h", file=file_path, type=node_type, line=1)
        for node_id, file_path, node_type in nodes_data
    ]
    return Graph0(nodes=nodes)


def _make_index(callee_pairs=None, test_links=None):
    mock = MagicMock()
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE nodes (node_id TEXT, id TEXT, file TEXT, type TEXT, line INTEGER)")
    conn.execute("CREATE TABLE callees (node_id TEXT, callee_id TEXT)")
    conn.execute("CREATE TABLE callers (node_id TEXT, caller_id TEXT)")
    conn.execute("CREATE TABLE tests (test_id TEXT, node_id TEXT)")

    for source, target in callee_pairs or []:
        conn.execute("INSERT INTO callees VALUES (?, ?)", (source, target))
        conn.execute("INSERT INTO callers VALUES (?, ?)", (target, source))

    for test_id, node_id in test_links or []:
        conn.execute("INSERT INTO tests VALUES (?, ?)", (test_id, node_id))

    mock._get_conn.return_value = conn
    return mock


def test_detects_microservice_candidate_on_cohesive_cluster():
    graph0 = _make_graph0([
        ("trading/data.py::load_data", "trading/data.py", "function"),
        ("trading/signal.py::compute_signal", "trading/signal.py", "function"),
        ("trading/trade.py::execute_trade", "trading/trade.py", "function"),
        ("app/main.py::run", "app/main.py", "function"),
    ])
    index = _make_index(
        callee_pairs=[
            ("trading/data.py::load_data", "trading/signal.py::compute_signal"),
            ("trading/signal.py::compute_signal", "trading/trade.py::execute_trade"),
            ("trading/trade.py::execute_trade", "trading/signal.py::compute_signal"),
            ("app/main.py::run", "trading/data.py::load_data"),
        ],
        test_links=[("tests/test_trading.py::test_flow", "trading/signal.py::compute_signal")],
    )

    candidates = detect_microservice_candidates(
        graph0,
        index,
        cluster_size_threshold=1,
        cohesion_threshold=0.5,
        coupling_threshold=0.8,
    )
    assert len(candidates) >= 1
    candidate = candidates[0]
    assert candidate.subsystem_name
    assert len(candidate.nodes) >= 2
    assert candidate.cohesion_score > 0.0
    assert candidate.coupling_score >= 0.0
    assert len(candidate.api_surface) >= 1
