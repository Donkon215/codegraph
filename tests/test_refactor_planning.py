"""Tests for codegraph.refactor_planner."""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock

from codegraph.dependency_inversion import DependencyInversionSuggestion
from codegraph.refactor_planner import generate_refactor_plans


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


def test_generates_cycle_and_inversion_plans():
    decay_report = {
        "cyclic_subsystems": [
            {"modules": ["a.py", "b.py", "c.py"], "size": 3},
        ]
    }
    detection_report = {"architecture_type": "layered", "confidence": 0.9}
    subsystem_clusters = [{"nodes": ["trading/data.py", "trading/signal.py", "trading/trade.py"]}]
    inversion = DependencyInversionSuggestion(
        source_node="controller.py",
        target_node="database.py",
        interface_name="IDataRepository",
        affected_nodes=["controller.py", "database.py", "IDataRepository"],
        score_delta=0.02,
        confidence=0.8,
    )
    index = _make_index(callee_pairs=[("controller.py::a", "database.py::b")])

    plans = generate_refactor_plans(
        architecture_decay_report=decay_report,
        architecture_detection_report=detection_report,
        subsystem_clusters=subsystem_clusters,
        index=index,
        dependency_inversions=[inversion],
    )
    assert len(plans) >= 2
    assert all(len(plan.steps) >= 2 for plan in plans)
    assert any(plan.problem_type == "cyclic_subsystem" for plan in plans)
    assert any(plan.problem_type == "dependency_inversion" for plan in plans)
