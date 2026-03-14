"""Tests for codegraph.architecture_detection."""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock

from codegraph.architecture_detection import (
    detect_architecture_patterns,
    detect_bidirectional_clusters,
    detect_layered_architecture,
    detect_pipeline_architecture,
)
from codegraph.models.graph0 import Graph0, Graph0Node


def _make_graph0(nodes_data):
    nodes = [
        Graph0Node(id=node_id, body_hash="h", file=file_path, type=node_type, line=1)
        for node_id, file_path, node_type in nodes_data
    ]
    return Graph0(nodes=nodes)


def _make_index(callee_pairs=None, node_ids=None):
    mock = MagicMock()
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE nodes (node_id TEXT, id TEXT, file TEXT, type TEXT, line INTEGER)")
    conn.execute("CREATE TABLE callees (node_id TEXT, callee_id TEXT)")
    conn.execute("CREATE TABLE callers (node_id TEXT, caller_id TEXT)")

    for node_id in node_ids or []:
        conn.execute("INSERT INTO nodes VALUES (?, ?, '', '', 0)", (node_id, node_id))

    for source, target in callee_pairs or []:
        conn.execute("INSERT INTO callees VALUES (?, ?)", (source, target))
        conn.execute("INSERT INTO callers VALUES (?, ?)", (target, source))

    mock._get_conn.return_value = conn
    return mock


def test_detect_layered_architecture():
    graph0 = _make_graph0([
        ("ui/view.py::render", "ui/view.py", "function"),
        ("service/logic.py::compute", "service/logic.py", "function"),
        ("database/repo.py::save", "database/repo.py", "function"),
    ])
    index = _make_index(
        callee_pairs=[
            ("ui/view.py::render", "service/logic.py::compute"),
            ("service/logic.py::compute", "database/repo.py::save"),
        ]
    )

    report = detect_layered_architecture(graph0, index)
    assert report["architecture_type"] == "layered"
    assert report["confidence"] > 0.5
    assert report["details"]["upward_violations"] == 0


def test_detect_pipeline_architecture():
    graph0 = _make_graph0([
        ("pipe/a.py::stage1", "pipe/a.py", "function"),
        ("pipe/b.py::stage2", "pipe/b.py", "function"),
        ("pipe/c.py::stage3", "pipe/c.py", "function"),
        ("pipe/d.py::stage4", "pipe/d.py", "function"),
    ])
    index = _make_index(
        callee_pairs=[
            ("pipe/a.py::stage1", "pipe/b.py::stage2"),
            ("pipe/b.py::stage2", "pipe/c.py::stage3"),
            ("pipe/c.py::stage3", "pipe/d.py::stage4"),
        ]
    )

    report = detect_pipeline_architecture(graph0, index)
    assert report["architecture_type"] == "pipeline"
    assert report["confidence"] >= 0.5


def test_detect_bidirectional_clusters():
    graph0 = _make_graph0([
        ("a.py::f", "a.py", "function"),
        ("b.py::g", "b.py", "function"),
    ])
    index = _make_index(
        callee_pairs=[
            ("a.py::f", "b.py::g"),
            ("b.py::g", "a.py::f"),
        ]
    )

    report = detect_bidirectional_clusters(graph0, index)
    assert report["architecture_type"] == "bidirectional"
    assert report["details"]["bidirectional_pairs"] >= 1
    assert len(report["violations"]) >= 1


def test_detect_architecture_patterns_returns_dominant_report():
    graph0 = _make_graph0([
        ("ui/view.py::render", "ui/view.py", "function"),
        ("service/logic.py::compute", "service/logic.py", "function"),
        ("database/repo.py::save", "database/repo.py", "function"),
    ])
    index = _make_index(
        callee_pairs=[
            ("ui/view.py::render", "service/logic.py::compute"),
            ("service/logic.py::compute", "database/repo.py::save"),
        ]
    )

    report = detect_architecture_patterns(graph0, index)
    assert "architecture_type" in report
    assert "confidence" in report
    assert "reports" in report
    assert report["architecture_type"] in {
        "layered",
        "event_driven",
        "pipeline",
        "bidirectional",
    }
