"""Tests for codegraph.dependency_inversion."""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock

from codegraph.dependency_inversion import suggest_dependency_inversions


def _make_index(callee_pairs=None):
    mock = MagicMock()
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE nodes (node_id TEXT, id TEXT, file TEXT, type TEXT, line INTEGER)")
    conn.execute("CREATE TABLE callees (node_id TEXT, callee_id TEXT)")
    conn.execute("CREATE TABLE callers (node_id TEXT, caller_id TEXT)")
    for source, target in callee_pairs or []:
        conn.execute("INSERT INTO callees VALUES (?, ?)", (source, target))
        conn.execute("INSERT INTO callers VALUES (?, ?)", (target, source))
    mock._get_conn.return_value = conn
    return mock


def test_detects_layer_inversion_and_suggests_interface():
    callee_pairs = [
        ("controller/api.py::run", "database/repo.py::save"),
        ("controller/api.py::run", "database/repo.py::load"),
        ("controller/other.py::sync", "database/repo.py::save"),
    ]
    index = _make_index(callee_pairs=callee_pairs)

    suggestions = suggest_dependency_inversions(
        index,
        fan_in_threshold=1,
        fan_out_threshold=1,
    )
    assert len(suggestions) >= 1
    first = suggestions[0]
    assert first.interface_name.startswith("I")
    assert first.source_node
    assert first.target_node
    assert first.confidence > 0.0
