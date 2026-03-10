"""Tests for codegraph.multilevel — multi-level architecture analysis."""

import sqlite3
import tempfile
from pathlib import Path
from typing import List
from unittest.mock import MagicMock

import pytest

from codegraph.multilevel import (
    ModuleNode,
    ModuleEdge,
    ModuleGraph,
    SubsystemNode,
    SubsystemEdge,
    SubsystemGraph,
    MultiLevelSmell,
    MultiLevelReport,
    build_module_graph,
    build_subsystem_graph,
    analyze_multilevel,
    _infer_subsystem_mapping,
)
from codegraph.models.graph0 import Graph0, Graph0Node


def _make_graph0(nodes: List[dict]) -> Graph0:
    """Build a Graph0 with given node specs."""
    g = Graph0()
    for n in nodes:
        g0n = Graph0Node(
            id=n["id"],
            body_hash=n.get("body_hash", "abc123"),
            file=n.get("file", "a.py"),
            type=n.get("type", "function"),
            line=n.get("line", 1),
        )
        g.nodes.append(g0n)
    return g


def _make_index(callee_pairs: List[tuple]) -> MagicMock:
    """Build a mock IndexStore with callee data."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE callees (node_id TEXT, callee_id TEXT)")
    conn.executemany(
        "INSERT INTO callees VALUES (?, ?)", callee_pairs
    )
    conn.commit()

    mock = MagicMock()
    mock._conn = conn
    mock._get_conn.return_value = conn
    return mock


class TestModuleNode:
    def test_to_dict(self):
        mn = ModuleNode("a.py", function_count=5, fan_in=2, fan_out=3)
        d = mn.to_dict()
        assert d["file"] == "a.py"
        assert d["function_count"] == 5
        assert d["fan_in"] == 2
        assert d["fan_out"] == 3


class TestModuleGraph:
    def test_to_dict(self):
        mg = ModuleGraph(
            nodes=[ModuleNode("a.py", function_count=3)],
            edges=[ModuleEdge("a.py", "b.py", call_count=2)],
        )
        d = mg.to_dict()
        assert d["level"] == 2
        assert d["summary"]["total_modules"] == 1
        assert d["summary"]["total_edges"] == 1

    def test_empty_avg(self):
        mg = ModuleGraph()
        d = mg.to_dict()
        assert d["summary"]["avg_functions"] == 0

    def test_format(self):
        mg = ModuleGraph(
            nodes=[ModuleNode("a.py", fan_out=5)],
        )
        text = mg.format()
        assert "a.py" in text


class TestSubsystemNode:
    def test_to_dict(self):
        sn = SubsystemNode(
            name="core", module_count=3, function_count=20,
            internal_edges=10, cohesion=0.75,
            modules=["a.py", "b.py", "c.py"],
        )
        d = sn.to_dict()
        assert d["name"] == "core"
        assert d["cohesion"] == 0.75
        assert len(d["modules"]) == 3


class TestSubsystemGraph:
    def test_to_dict(self):
        sg = SubsystemGraph(
            nodes=[SubsystemNode("core")],
            edges=[SubsystemEdge("core", "models", edge_count=5)],
        )
        d = sg.to_dict()
        assert d["level"] == 3
        assert d["summary"]["total_subsystems"] == 1
        assert d["summary"]["total_edges"] == 1

    def test_format(self):
        sg = SubsystemGraph(
            nodes=[SubsystemNode("core", function_count=10, cohesion=0.8)],
        )
        text = sg.format()
        assert "core" in text
        assert "0.80" in text


class TestMultiLevelSmell:
    def test_to_dict(self):
        s = MultiLevelSmell(
            level=2, smell_type="god_module",
            severity="warning", entity="cli.py",
            metric_value=45, threshold=30,
        )
        d = s.to_dict()
        assert d["level_name"] == "module"
        assert d["smell_type"] == "god_module"
        assert d["metric_value"] == 45


class TestMultiLevelReport:
    def test_empty(self):
        r = MultiLevelReport()
        d = r.to_dict()
        assert d["summary"]["total_smells"] == 0

    def test_with_smells(self):
        r = MultiLevelReport(
            smells=[
                MultiLevelSmell(level=1, smell_type="god_function"),
                MultiLevelSmell(level=2, smell_type="god_module"),
                MultiLevelSmell(level=3, smell_type="low_cohesion"),
            ],
        )
        d = r.to_dict()
        assert d["summary"]["total_smells"] == 3
        assert d["summary"]["by_level"]["function"] == 1
        assert d["summary"]["by_level"]["module"] == 1
        assert d["summary"]["by_level"]["subsystem"] == 1

    def test_format(self):
        r = MultiLevelReport(
            smells=[
                MultiLevelSmell(level=1, smell_type="god_function",
                                description="Too many callees"),
            ],
        )
        text = r.format()
        assert "Function Level" in text
        assert "Too many callees" in text


class TestBuildModuleGraph:
    def test_basic(self):
        g0 = _make_graph0([
            {"id": "a.py::f1", "file": "a.py"},
            {"id": "a.py::f2", "file": "a.py"},
            {"id": "b.py::g1", "file": "b.py"},
        ])
        index = _make_index([
            ("a.py::f1", "b.py::g1"),
            ("a.py::f2", "b.py::g1"),
        ])
        mg = build_module_graph(g0, index)
        assert len(mg.nodes) == 2
        assert len(mg.edges) == 1
        assert mg.edges[0].source_file == "a.py"
        assert mg.edges[0].call_count == 2

        # Check fan-in/out
        a_node = [n for n in mg.nodes if n.file == "a.py"][0]
        b_node = [n for n in mg.nodes if n.file == "b.py"][0]
        assert a_node.fan_out == 1
        assert a_node.fan_in == 0
        assert b_node.fan_in == 1

    def test_same_file_edges_ignored(self):
        g0 = _make_graph0([
            {"id": "a.py::f1", "file": "a.py"},
            {"id": "a.py::f2", "file": "a.py"},
        ])
        index = _make_index([("a.py::f1", "a.py::f2")])
        mg = build_module_graph(g0, index)
        assert len(mg.edges) == 0  # same-file not counted


class TestBuildSubsystemGraph:
    def test_basic(self):
        g0 = _make_graph0([
            {"id": "core/a.py::f1", "file": "core/a.py"},
            {"id": "core/b.py::f2", "file": "core/b.py"},
            {"id": "models/c.py::g1", "file": "models/c.py"},
        ])
        index = _make_index([
            ("core/a.py::f1", "core/b.py::f2"),  # internal
            ("core/a.py::f1", "models/c.py::g1"),  # cross-subsystem
        ])
        mapping = {
            "core/a.py": "core",
            "core/b.py": "core",
            "models/c.py": "models",
        }
        sg = build_subsystem_graph(g0, index, mapping)
        assert len(sg.nodes) == 2

        core_node = [n for n in sg.nodes if n.name == "core"][0]
        assert core_node.internal_edges == 1
        assert core_node.external_edges_out == 1

        # Cross-subsystem edge
        cross = [e for e in sg.edges if e.source == "core" and e.target == "models"]
        assert len(cross) == 1
        assert cross[0].edge_count == 1


class TestAnalyzeMultilevel:
    def _make_data(self, n_funcs_per_module=5, n_modules=3):
        nodes = []
        callees = []
        for m in range(n_modules):
            for f in range(n_funcs_per_module):
                nid = f"mod{m}/file.py::func{f}"
                nodes.append({"id": nid, "file": f"mod{m}/file.py"})
        g0 = _make_graph0(nodes)
        index = _make_index(callees)
        return g0, index

    def test_no_smells_small_project(self):
        g0, index = self._make_data(n_funcs_per_module=3, n_modules=2)
        report = analyze_multilevel(g0, index)
        assert report.to_dict()["summary"]["total_smells"] == 0

    def test_god_module_detected(self):
        g0, index = self._make_data(n_funcs_per_module=35, n_modules=1)
        report = analyze_multilevel(g0, index, god_module_threshold=30)
        mod_smells = [s for s in report.smells if s.smell_type == "god_module"]
        assert len(mod_smells) == 1
        assert mod_smells[0].metric_value == 35

    def test_god_function_detected(self):
        nodes = [{"id": f"a.py::func{i}", "file": "a.py"} for i in range(25)]
        callees = [("a.py::func0", f"a.py::func{i}") for i in range(1, 25)]
        g0 = _make_graph0(nodes)
        index = _make_index(callees)

        report = analyze_multilevel(g0, index, god_function_threshold=20)
        func_smells = [s for s in report.smells if s.smell_type == "god_function"]
        assert len(func_smells) == 1
        assert func_smells[0].entity == "a.py::func0"


class TestInferSubsystemMapping:
    def test_basic(self):
        g0 = _make_graph0([
            {"id": "core/a.py::f", "file": "core/a.py"},
            {"id": "models/b.py::g", "file": "models/b.py"},
        ])
        mapping = _infer_subsystem_mapping(g0)
        assert mapping["core/a.py"] == "core"
        assert mapping["models/b.py"] == "models"

    def test_root_files(self):
        g0 = _make_graph0([
            {"id": "setup.py::main", "file": "setup.py"},
        ])
        mapping = _infer_subsystem_mapping(g0)
        assert mapping["setup.py"] == "root"
