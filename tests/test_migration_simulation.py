"""Tests for migration simulation operations in codegraph.simulator."""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock

from codegraph.simulator import (
    simulate_dependency_inversion,
    simulate_layer_restructure,
    simulate_service_boundary,
    simulate_subsystem_extraction,
)


def _make_index(callee_pairs=None):
    mock = MagicMock()
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE nodes (node_id TEXT, id TEXT, file TEXT, type TEXT, line INTEGER)")
    conn.execute("CREATE TABLE callees (node_id TEXT, callee_id TEXT)")
    conn.execute("CREATE TABLE callers (node_id TEXT, caller_id TEXT)")
    for source, target in callee_pairs or []:
        conn.execute("INSERT INTO callees VALUES (?, ?)", (source, target))
        conn.execute("INSERT INTO callers VALUES (?, ?)", (target, source))
        conn.execute("INSERT INTO nodes VALUES (?, ?, '', '', 0)", (source, source))
        conn.execute("INSERT INTO nodes VALUES (?, ?, '', '', 0)", (target, target))
    mock._get_conn.return_value = conn
    return mock


def test_subsystem_extraction_simulation_returns_result():
    index = _make_index([
        ("trading/data.py::a", "trading/signal.py::b"),
        ("app/main.py::run", "trading/data.py::a"),
    ])
    result = simulate_subsystem_extraction(index, ["trading/data.py", "trading/signal.py"])
    assert hasattr(result, "before_score")
    assert hasattr(result, "after_score")
    assert isinstance(result.affected_nodes, list)


def test_layer_restructure_simulation_returns_result():
    index = _make_index([
        ("ui/view.py::render", "database/repo.py::save"),
    ])
    result = simulate_layer_restructure(index, "ui/view.py", "database/repo.py")
    assert result.layer_violations >= 0
    assert result.risk_level


def test_service_boundary_and_dependency_inversion_simulations():
    index = _make_index([
        ("controller/api.py::run", "database/repo.py::save"),
        ("app/main.py::run", "trading/data.py::a"),
    ])
    service_result = simulate_service_boundary(index, ["trading/data.py"])
    inversion_result = simulate_dependency_inversion(
        index,
        "controller/api.py",
        "database/repo.py",
        "IDataRepository",
    )
    assert service_result.summary
    assert inversion_result.summary
    assert inversion_result.affected_nodes
