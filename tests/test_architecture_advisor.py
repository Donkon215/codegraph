"""Tests for codegraph.architecture_advisor."""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from codegraph.architecture_advisor import (
    ArchAdvice,
    ArchSmell,
    ArchSuggestion,
    advise_architecture,
    enrich_workflow_with_intents,
    save_enriched_workflow,
    _compute_grade,
    _compute_max_depth,
)
from codegraph.models.graph0 import Graph0, Graph0Node
from codegraph.models.graph1 import Graph1, Graph1Node
from codegraph.models.workflow import Workflow, WorkflowEdge


# ── Helpers ───────────────────────────────────────────────────────────

def _make_graph0(nodes_data):
    """Create a Graph0 from list of (id, file, type) tuples."""
    nodes = [
        Graph0Node(id=nid, body_hash="h", file=f, type=t, line=1)
        for nid, f, t in nodes_data
    ]
    return Graph0(nodes=nodes)


def _make_index(callee_pairs=None, node_ids=None):
    """Create a mock IndexStore with callee/callers/nodes tables."""
    mock = MagicMock()
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE nodes (node_id TEXT, file TEXT, type TEXT, line INTEGER)")
    conn.execute("CREATE TABLE callees (node_id TEXT, callee_id TEXT)")
    conn.execute("CREATE TABLE callers (node_id TEXT, caller_id TEXT)")

    if node_ids:
        for nid in node_ids:
            conn.execute("INSERT INTO nodes VALUES (?, '', '', 0)", (nid,))

    if callee_pairs:
        for src, tgt in callee_pairs:
            conn.execute("INSERT INTO callees VALUES (?, ?)", (src, tgt))
            conn.execute("INSERT INTO callers VALUES (?, ?)", (tgt, src))

    mock._get_conn.return_value = conn
    mock._conn = conn
    return mock


# ── ArchSmell ─────────────────────────────────────────────────────────

class TestArchSmell:
    def test_to_dict_minimal(self):
        s = ArchSmell(smell_type="cycle", description="A cycle")
        d = s.to_dict()
        assert d["smell_type"] == "cycle"
        assert d["severity"] == "warning"
        assert "node" not in d
        assert "nodes" not in d

    def test_to_dict_full(self):
        s = ArchSmell(
            smell_type="god_module",
            severity="error",
            node="file.py",
            nodes=["a", "b"],
            metric_value=50,
            threshold=30,
            description="Too large",
            suggestion="Split it",
        )
        d = s.to_dict()
        assert d["node"] == "file.py"
        assert d["nodes"] == ["a", "b"]
        assert d["metric_value"] == 50
        assert d["threshold"] == 30


# ── ArchSuggestion ───────────────────────────────────────────────────

class TestArchSuggestion:
    def test_to_dict(self):
        s = ArchSuggestion(
            action="split_module",
            target="big.py",
            reason="Too many nodes",
            priority=3,
            source_smell="god_module",
        )
        d = s.to_dict()
        assert d["action"] == "split_module"
        assert d["priority"] == 3


# ── ArchAdvice ────────────────────────────────────────────────────────

class TestArchAdvice:
    def test_to_dict(self):
        advice = ArchAdvice(score=0.85, grade="B", total_nodes=100)
        d = advice.to_dict()
        assert d["score"] == 0.85
        assert d["grade"] == "B"
        assert d["smells"] == []

    def test_format(self):
        advice = ArchAdvice(
            score=0.75,
            grade="C",
            total_nodes=200,
            total_edges=500,
            total_files=20,
            cycle_count=1,
            god_module_count=2,
        )
        text = advice.format()
        assert "C (75%)" in text
        assert "Cycles: 1" in text
        assert "God modules: 2" in text

    def test_save(self):
        advice = ArchAdvice(score=0.9, grade="A")
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            path = advice.save(root)
            assert path.exists()
            data = json.loads(path.read_text())
            assert data["grade"] == "A"


# ── _compute_grade ───────────────────────────────────────────────────

class TestComputeGrade:
    def test_grades(self):
        assert _compute_grade(0.95) == "A"
        assert _compute_grade(0.85) == "B"
        assert _compute_grade(0.75) == "C"
        assert _compute_grade(0.55) == "D"
        assert _compute_grade(0.3) == "F"


# ── advise_architecture ─────────────────────────────────────────────

class TestAdviseArchitecture:
    def test_empty_graph(self):
        g0 = _make_graph0([])
        idx = _make_index()
        advice = advise_architecture(g0, idx)
        assert advice.total_nodes == 0
        assert advice.score > 0

    def test_detects_god_module(self):
        # Create 35 nodes in one file — exceeds threshold of 30
        nodes_data = [
            (f"big.py::func_{i}", "big.py", "function")
            for i in range(35)
        ]
        node_ids = [n[0] for n in nodes_data]
        g0 = _make_graph0(nodes_data)
        idx = _make_index(node_ids=node_ids)
        advice = advise_architecture(g0, idx, god_module_threshold=30)
        assert advice.god_module_count == 1
        god_smells = [s for s in advice.smells if s.smell_type == "god_module"]
        assert len(god_smells) == 1
        assert "big.py" in god_smells[0].node

    def test_detects_high_fan_in(self):
        # One node called by many others
        nodes_data = [
            ("hub.py::hub", "hub.py", "function"),
        ] + [
            (f"caller{i}.py::f", f"caller{i}.py", "function")
            for i in range(25)
        ]
        callee_pairs = [
            (f"caller{i}.py::f", "hub.py::hub")
            for i in range(25)
        ]
        node_ids = [n[0] for n in nodes_data]
        g0 = _make_graph0(nodes_data)
        idx = _make_index(callee_pairs=callee_pairs, node_ids=node_ids)
        advice = advise_architecture(g0, idx, fan_in_threshold=20)
        fan_in_smells = [s for s in advice.smells if s.smell_type == "high_fan_in"]
        assert len(fan_in_smells) >= 1

    def test_no_smells_clean_graph(self):
        nodes_data = [
            ("a.py::f1", "a.py", "function"),
            ("b.py::f2", "b.py", "function"),
        ]
        callee_pairs = [("a.py::f1", "b.py::f2")]
        node_ids = [n[0] for n in nodes_data]
        g0 = _make_graph0(nodes_data)
        idx = _make_index(callee_pairs=callee_pairs, node_ids=node_ids)
        advice = advise_architecture(g0, idx)
        # Clean graph should have high score
        assert advice.score >= 0.8

    def test_cycle_detection(self):
        nodes_data = [
            ("a.py::f", "a.py", "function"),
            ("b.py::g", "b.py", "function"),
        ]
        callee_pairs = [
            ("a.py::f", "b.py::g"),
            ("b.py::g", "a.py::f"),
        ]
        node_ids = [n[0] for n in nodes_data]
        g0 = _make_graph0(nodes_data)
        idx = _make_index(callee_pairs=callee_pairs, node_ids=node_ids)
        advice = advise_architecture(g0, idx)
        assert advice.cycle_count >= 1

    def test_score_reduces_with_issues(self):
        # Graph with god module + cycles = lower score
        nodes_data = [
            (f"big.py::func_{i}", "big.py", "function")
            for i in range(35)
        ]
        # Add cycle
        nodes_data.append(("x.py::a", "x.py", "function"))
        nodes_data.append(("y.py::b", "y.py", "function"))
        callee_pairs = [("x.py::a", "y.py::b"), ("y.py::b", "x.py::a")]
        node_ids = [n[0] for n in nodes_data]
        g0 = _make_graph0(nodes_data)
        idx = _make_index(callee_pairs=callee_pairs, node_ids=node_ids)
        advice = advise_architecture(g0, idx, god_module_threshold=30)
        assert advice.score < 0.9  # Penalized


# ── _compute_max_depth ───────────────────────────────────────────────

class TestComputeMaxDepth:
    def test_no_edges(self):
        idx = _make_index()
        assert _compute_max_depth(idx) == 0

    def test_chain(self):
        callee_pairs = [
            ("a", "b"), ("b", "c"), ("c", "d"),
        ]
        idx = _make_index(callee_pairs=callee_pairs)
        assert _compute_max_depth(idx) == 3


# ── enrich_workflow_with_intents ─────────────────────────────────────

class TestEnrichWorkflow:
    def test_basic_enrichment(self):
        wf = Workflow(edges=[
            WorkflowEdge(source="a.py::f", target="b.py::g"),
        ])
        g1 = Graph1(nodes=[
            Graph1Node(id="a.py::f", intent="Function f does X"),
            Graph1Node(id="b.py::g", intent="Function g does Y"),
        ])
        enriched = enrich_workflow_with_intents(wf, g1)
        dicts = enriched._enriched_edge_dicts
        assert dicts[0]["source_intent"] == "Function f does X"
        assert dicts[0]["target_intent"] == "Function g does Y"

    def test_missing_intents(self):
        wf = Workflow(edges=[
            WorkflowEdge(source="a.py::f", target="b.py::g"),
        ])
        g1 = Graph1(nodes=[])
        enriched = enrich_workflow_with_intents(wf, g1)
        dicts = enriched._enriched_edge_dicts
        assert "source_intent" not in dicts[0]
        assert "target_intent" not in dicts[0]

    def test_partial_intents(self):
        wf = Workflow(edges=[
            WorkflowEdge(source="a.py::f", target="b.py::g"),
        ])
        g1 = Graph1(nodes=[
            Graph1Node(id="a.py::f", intent="Does stuff"),
        ])
        enriched = enrich_workflow_with_intents(wf, g1)
        dicts = enriched._enriched_edge_dicts
        assert dicts[0]["source_intent"] == "Does stuff"
        assert "target_intent" not in dicts[0]


# ── save_enriched_workflow ───────────────────────────────────────────

class TestSaveEnrichedWorkflow:
    def test_creates_file(self):
        wf = Workflow(edges=[
            WorkflowEdge(source="a.py::f", target="b.py::g"),
        ])
        g1 = Graph1(nodes=[
            Graph1Node(id="a.py::f", intent="Func f"),
        ])
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            path = save_enriched_workflow(wf, g1, root)
            assert path.exists()
            data = json.loads(path.read_text())
            assert data["intent_enriched"] is True
            assert len(data["edges"]) == 1
            assert data["edges"][0].get("source_intent") == "Func f"
