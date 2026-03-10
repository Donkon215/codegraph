"""Tests for codegraph.arch_viewer — HTML architecture dashboard generator."""

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from codegraph.arch_viewer import (
    generate_viewer,
    _build_system_data,
    _build_subsystem_data,
    _build_code_data,
    _build_stats,
    _escape_html,
)
from codegraph.arch_schema import (
    ArchComponent,
    ArchEdge,
    SubsystemDef,
    SystemArchitecture,
)
from codegraph.models.graph0 import Graph0, Graph0Node
from codegraph.models.graph1 import Graph1, Graph1Node
from codegraph.models.workflow import Workflow, WorkflowEdge


def _g0(nodes_data):
    """Create Graph0 from [(id, file, type)]."""
    return Graph0(
        nodes=[Graph0Node(id=n[0], body_hash="h", file=n[1], type=n[2], line=1) for n in nodes_data]
    )


def _g1(nodes_data):
    """Create Graph1 from [(id, intent)]."""
    return Graph1(
        nodes=[Graph1Node(id=n[0], intent=n[1]) for n in nodes_data]
    )


def _wf(edges_data):
    """Create Workflow from [(source, target)]."""
    return Workflow(
        edges=[WorkflowEdge(source=e[0], target=e[1]) for e in edges_data]
    )


def _make_mock_index():
    """Create a mock IndexStore."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE callees (node_id TEXT, callee_id TEXT)")
    conn.execute("CREATE TABLE nodes (node_id TEXT, id TEXT, file TEXT, type TEXT)")
    mock = MagicMock()
    mock._get_conn.return_value = conn
    mock._conn = conn
    return mock


class TestBuildSystemData:
    def test_auto_detection(self):
        g0 = _g0([
            ("src/main.py::main", "src/main.py", "function"),
            ("lib/utils.py::helper", "lib/utils.py", "function"),
        ])
        wf = _wf([("src/main.py::main", "lib/utils.py::helper")])
        data = _build_system_data(g0, wf, None)
        assert len(data["nodes"]) >= 2
        node_ids = [n["id"] for n in data["nodes"]]
        assert "src" in node_ids
        assert "lib" in node_ids

    def test_with_architecture(self):
        g0 = _g0([("a.py::f", "a.py", "function")])
        wf = _wf([])
        arch = SystemArchitecture(
            name="test",
            subsystems=[SubsystemDef(name="core", description="Core logic")],
            edges=[ArchEdge(source="core", target="data")],
        )
        data = _build_system_data(g0, wf, arch)
        assert any(n["id"] == "core" for n in data["nodes"])
        assert any(e["type"] == "expected" for e in data["edges"])


class TestBuildSubsystemData:
    def test_auto_detection(self):
        g0 = _g0([
            ("src/a.py::f", "src/a.py", "function"),
            ("src/b.py::g", "src/b.py", "function"),
        ])
        index = _make_mock_index()
        data = _build_subsystem_data(g0, index, None)
        assert "src" in data
        assert len(data["src"]["components"]) == 2

    def test_with_architecture(self):
        g0 = _g0([("a.py::f", "a.py", "function")])
        arch = SystemArchitecture(
            name="test",
            subsystems=[
                SubsystemDef(
                    name="core",
                    components=[
                        ArchComponent(name="main", module="a.py", description="Entry"),
                    ],
                    edges=[ArchEdge(source="main", target="util")],
                ),
            ],
        )
        index = _make_mock_index()
        data = _build_subsystem_data(g0, index, arch)
        assert "core" in data
        assert len(data["core"]["components"]) == 1
        assert data["core"]["components"][0]["description"] == "Entry"


class TestBuildCodeData:
    def test_basic(self):
        g0 = _g0([
            ("a.py::f", "a.py", "function"),
            ("b.py::g", "b.py", "function"),
            ("c.py::h", "c.py", "function"),  # no edges
        ])
        g1 = _g1([("a.py::f", "Does something"), ("b.py::g", "")])
        wf = _wf([("a.py::f", "b.py::g")])
        data = _build_code_data(g0, g1, wf)
        # Only nodes with edges are included
        node_ids = [n["id"] for n in data["nodes"]]
        assert "a.py::f" in node_ids
        assert "b.py::g" in node_ids
        assert "c.py::h" not in node_ids
        assert len(data["edges"]) == 1

    def test_intent_attached(self):
        g0 = _g0([("a.py::f", "a.py", "function"), ("b.py::g", "b.py", "function")])
        g1 = _g1([("a.py::f", "My intent")])
        wf = _wf([("a.py::f", "b.py::g")])
        data = _build_code_data(g0, g1, wf)
        f_node = next(n for n in data["nodes"] if n["id"] == "a.py::f")
        assert f_node["intent"] == "My intent"


class TestBuildStats:
    def test_basic_stats(self):
        g0 = _g0([("a.py::f", "a.py", "function"), ("b.py::g", "b.py", "function")])
        wf = _wf([("a.py::f", "b.py::g")])
        stats = _build_stats(g0, wf, None)
        assert stats["total_nodes"] == 2
        assert stats["total_edges"] == 1
        assert stats["total_files"] == 2

    def test_with_architecture(self):
        g0 = _g0([("a.py::f", "a.py", "function")])
        wf = _wf([])
        arch = SystemArchitecture(name="myapp", subsystems=[SubsystemDef(name="core")])
        stats = _build_stats(g0, wf, arch)
        assert stats["architecture_name"] == "myapp"
        assert stats["subsystem_count"] == 1


class TestEscapeHtml:
    def test_escapes(self):
        assert _escape_html("<b>test</b>") == "&lt;b&gt;test&lt;/b&gt;"
        assert _escape_html('say "hello"') == "say &quot;hello&quot;"
        assert _escape_html("a & b") == "a &amp; b"


class TestGenerateViewer:
    def test_generates_html_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            g0 = _g0([
                ("src/main.py::main", "src/main.py", "function"),
                ("src/utils.py::helper", "src/utils.py", "function"),
            ])
            g1 = _g1([("src/main.py::main", "entry point")])
            wf = _wf([("src/main.py::main", "src/utils.py::helper")])
            index = _make_mock_index()

            path = generate_viewer(root, g0, g1, wf, index)
            assert path.exists()
            content = path.read_text(encoding="utf-8")
            assert "<!DOCTYPE html>" in content
            assert "cytoscape" in content
            assert "Codegraph Architecture" in content

    def test_custom_output_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "custom" / "view.html"
            g0 = _g0([("a.py::f", "a.py", "function")])
            g1 = _g1([])
            wf = _wf([])
            index = _make_mock_index()

            path = generate_viewer(root, g0, g1, wf, index, output_path=out)
            assert path == out
            assert out.exists()

    def test_with_architecture(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            g0 = _g0([("a.py::f", "a.py", "function")])
            g1 = _g1([])
            wf = _wf([])
            arch = SystemArchitecture(
                name="TestProject",
                subsystems=[SubsystemDef(name="core")],
            )
            index = _make_mock_index()

            path = generate_viewer(
                root, g0, g1, wf, index, architecture=arch
            )
            content = path.read_text(encoding="utf-8")
            assert "TestProject" in content
