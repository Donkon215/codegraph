"""Unit tests for core data models.

Tasks O-003: Node ID generation, O-018: version staleness.
"""

from __future__ import annotations

import json

import pytest

from codegraph.models.graph0 import Graph0, Graph0Node, NodeType, CollisionResolver
from codegraph.models.graph1 import Graph1, Graph1Node, validate_intent
from codegraph.models.workflow import (
    Workflow, WorkflowEdge, EdgeType, Confidence,
    deduplicate_edges, compare_edges,
)
from codegraph.utils.ids import generate_node_id, normalize_path
from pathlib import Path


# ── O-003: Node ID Generation ─────────────────────────────────────────


class TestNodeIdGeneration:
    """Test file::class::function node ID construction."""

    def test_simple_function(self) -> None:
        nid = generate_node_id("module.py", func_name="func")
        assert nid == "module.py::func"

    def test_method(self) -> None:
        nid = generate_node_id("module.py", class_name="MyClass", func_name="method")
        assert nid == "module.py::MyClass::method"

    def test_module_level(self) -> None:
        nid = generate_node_id("module.py")
        assert nid == "module"

    def test_nested_path(self) -> None:
        nid = generate_node_id("src/utils/helper.py", func_name="do_stuff")
        assert nid == "src/utils/helper.py::do_stuff"

    def test_disambiguator(self) -> None:
        nid = generate_node_id("mod.py", func_name="f", disambiguator=2)
        assert nid == "mod.py::f[2]"

    def test_no_disambiguator_for_first(self) -> None:
        nid = generate_node_id("mod.py", func_name="f", disambiguator=1)
        assert nid == "mod.py::f"

    def test_class_only(self) -> None:
        nid = generate_node_id("mod.py", class_name="Cls")
        assert nid == "mod.py::Cls"

    def test_dotted_path(self) -> None:
        nid = generate_node_id("my.package.py", func_name="run")
        assert nid == "my.package.py::run"


class TestPathNormalization:
    """Test path normalization utilities."""

    def test_basic_normalization(self, tmp_path: Path) -> None:
        file = tmp_path / "src" / "mod.py"
        file.parent.mkdir(parents=True, exist_ok=True)
        file.touch()
        result = normalize_path(file, tmp_path)
        assert result == "src/mod.py"

    def test_outside_root_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="outside"):
            normalize_path(Path("/nonexistent/file.py"), tmp_path)


# ── Graph0 Model Tests ────────────────────────────────────────────────


class TestGraph0Node:
    """Test Graph0Node dataclass."""

    def test_create_valid_node(self) -> None:
        node = Graph0Node(id="mod.py::func", body_hash="abc123", file="mod.py", type="function", line=10)
        assert node.id == "mod.py::func"
        assert node.type == "function"

    def test_invalid_type_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid node type"):
            Graph0Node(id="x", body_hash="abc", file="x.py", type="invalid", line=1)

    def test_equality_by_id(self) -> None:
        n1 = Graph0Node(id="a", body_hash="111", file="a.py", type="function", line=1)
        n2 = Graph0Node(id="a", body_hash="222", file="a.py", type="function", line=2)
        assert n1 == n2

    def test_hash_by_id(self) -> None:
        n1 = Graph0Node(id="a", body_hash="111", file="a.py", type="function", line=1)
        n2 = Graph0Node(id="a", body_hash="222", file="a.py", type="function", line=2)
        assert hash(n1) == hash(n2)

    def test_serialization_roundtrip(self) -> None:
        node = Graph0Node(id="mod.py::f", body_hash="abc", file="mod.py", type="function", line=5)
        d = node.to_dict()
        restored = Graph0Node.from_dict(d)
        assert restored.id == node.id
        assert restored.body_hash == node.body_hash


class TestGraph0:
    """Test Graph0 collection."""

    def test_add_and_get_node(self) -> None:
        g = Graph0()
        node = Graph0Node(id="a", body_hash="h", file="a.py", type="function", line=1)
        g.add_node(node)
        assert g.get_node("a") == node

    def test_duplicate_add_raises(self) -> None:
        g = Graph0()
        node = Graph0Node(id="a", body_hash="h", file="a.py", type="function", line=1)
        g.add_node(node)
        with pytest.raises(ValueError, match="Duplicate"):
            g.add_node(node)

    def test_remove_node(self) -> None:
        g = Graph0()
        g.add_node(Graph0Node(id="a", body_hash="h", file="a.py", type="function", line=1))
        g.remove_node("a")
        assert g.get_node("a") is None

    def test_get_nodes_by_file(self) -> None:
        g = Graph0()
        g.add_node(Graph0Node(id="a.py::f1", body_hash="h1", file="a.py", type="function", line=1))
        g.add_node(Graph0Node(id="a.py::f2", body_hash="h2", file="a.py", type="function", line=5))
        g.add_node(Graph0Node(id="b.py::f3", body_hash="h3", file="b.py", type="function", line=1))
        assert len(g.get_nodes_by_file("a.py")) == 2

    def test_json_roundtrip(self) -> None:
        g = Graph0()
        g.add_node(Graph0Node(id="a.py::f", body_hash="h", file="a.py", type="function", line=1))
        text = g.to_json()
        restored = Graph0.from_json(text)
        assert len(restored.nodes) == 1
        assert restored.get_node("a.py::f") is not None


class TestCollisionResolver:
    """Test node ID collision resolver."""

    def test_first_occurrence_unchanged(self) -> None:
        cr = CollisionResolver()
        assert cr.resolve("x") == "x"

    def test_second_occurrence_disambiguated(self) -> None:
        cr = CollisionResolver()
        cr.resolve("x")
        assert cr.resolve("x") == "x[2]"

    def test_third_occurrence(self) -> None:
        cr = CollisionResolver()
        cr.resolve("x")
        cr.resolve("x")
        assert cr.resolve("x") == "x[3]"


# ── Graph1 Model Tests ────────────────────────────────────────────────


class TestGraph1Node:
    """Test Graph1Node dataclass."""

    def test_update_intent(self) -> None:
        node = Graph1Node(id="a", intent="old", intent_version=1)
        node.update_intent("new intent", "agent")
        assert node.intent == "new intent"
        assert node.intent_version == 2
        assert node.intent_author == "agent"

    def test_equality_by_id(self) -> None:
        n1 = Graph1Node(id="a", intent="x")
        n2 = Graph1Node(id="a", intent="y")
        assert n1 == n2


class TestIntentValidation:
    """Test intent quality validation."""

    def test_empty_intent_fails(self) -> None:
        ok, warnings = validate_intent("")
        assert not ok

    def test_short_intent_warns(self) -> None:
        ok, warnings = validate_intent("hi")
        assert ok
        assert any("short" in w for w in warnings)

    def test_good_intent_ok(self) -> None:
        ok, warnings = validate_intent("Parse the input file and extract all function nodes")
        assert ok
        assert len(warnings) == 0

    def test_bad_pattern_warns(self) -> None:
        ok, warnings = validate_intent("Helper utility for processing data stuff")
        assert ok
        assert len(warnings) > 0


class TestGraph1:
    """Test Graph1 collection."""

    def test_upsert_new(self) -> None:
        g = Graph1()
        g.upsert_node(Graph1Node(id="a", intent="test"))
        assert g.get_node("a") is not None

    def test_upsert_updates(self) -> None:
        g = Graph1()
        g.upsert_node(Graph1Node(id="a", intent="v1", intent_author="user"))
        g.upsert_node(Graph1Node(id="a", intent="v2", intent_author="agent"))
        assert g.get_node("a").intent == "v2"

    def test_missing_intents(self) -> None:
        g = Graph1()
        g.upsert_node(Graph1Node(id="a", intent="has intent"))
        g.upsert_node(Graph1Node(id="b", intent=""))
        missing = g.get_nodes_missing_intent()
        assert "b" in missing
        assert "a" not in missing

    def test_stale_nodes(self) -> None:
        g = Graph1()
        g.upsert_node(Graph1Node(id="alive"))
        g.upsert_node(Graph1Node(id="dead"))
        stale = g.get_stale_nodes(frozenset({"alive"}))
        assert "dead" in stale


# ── Workflow Model Tests ───────────────────────────────────────────────


class TestWorkflowEdge:
    """Test WorkflowEdge dataclass."""

    def test_equality(self) -> None:
        e1 = WorkflowEdge(source="a", target="b", edge_type="call", confidence="static")
        e2 = WorkflowEdge(source="a", target="b", edge_type="call", confidence="static")
        assert e1 == e2

    def test_inequality(self) -> None:
        e1 = WorkflowEdge(source="a", target="b")
        e2 = WorkflowEdge(source="a", target="c")
        assert e1 != e2

    def test_dynamic_edge(self) -> None:
        e = WorkflowEdge(source="a", target="mod::*::method")
        assert e.is_dynamic()


class TestWorkflow:
    """Test Workflow collection."""

    def test_add_edge(self) -> None:
        wf = Workflow()
        added = wf.add_edge(WorkflowEdge(source="a", target="b"))
        assert added
        assert len(wf.edges) == 1

    def test_no_duplicate(self) -> None:
        wf = Workflow()
        wf.add_edge(WorkflowEdge(source="a", target="b"))
        added = wf.add_edge(WorkflowEdge(source="a", target="b"))
        assert not added
        assert len(wf.edges) == 1

    def test_get_edges_from(self) -> None:
        wf = Workflow()
        wf.add_edge(WorkflowEdge(source="a", target="b"))
        wf.add_edge(WorkflowEdge(source="a", target="c"))
        assert len(wf.get_edges_from("a")) == 2

    def test_remove_edge(self) -> None:
        wf = Workflow()
        wf.add_edge(WorkflowEdge(source="a", target="b"))
        wf.remove_edge("a", "b")
        assert len(wf.edges) == 0

    def test_json_roundtrip(self) -> None:
        wf = Workflow()
        wf.add_edge(WorkflowEdge(source="a", target="b"))
        text = wf.to_json()
        restored = Workflow.from_json(text)
        assert len(restored.edges) == 1


class TestEdgeDeduplication:
    """Test edge dedup utility."""

    def test_removes_duplicates(self) -> None:
        edges = [
            WorkflowEdge(source="a", target="b"),
            WorkflowEdge(source="a", target="b"),
            WorkflowEdge(source="a", target="c"),
        ]
        result = deduplicate_edges(edges)
        assert len(result) == 2


class TestConfidence:
    """Test confidence level ordering."""

    def test_ordering(self) -> None:
        assert Confidence.RUNTIME > Confidence.STATIC
        assert Confidence.STATIC > Confidence.AI_INFERRED
        assert Confidence.TEST > Confidence.STATIC

    def test_edge_comparison(self) -> None:
        e1 = WorkflowEdge(source="a", target="b", confidence="static")
        e2 = WorkflowEdge(source="a", target="b", confidence="runtime")
        best = compare_edges(e1, e2)
        assert best.confidence == "runtime"


class TestNodeType:
    """Test NodeType enum."""

    def test_callable(self) -> None:
        assert NodeType.FUNCTION.is_callable()
        assert NodeType.METHOD.is_callable()
        assert not NodeType.CLASS.is_callable()
        assert not NodeType.MODULE.is_callable()


# ── O-018: Version Staleness ──────────────────────────────────────────


class TestVersionStaleness:
    """Test graph_version validation for agent responses."""

    def test_matching_version(self) -> None:
        """Matching versions should be accepted."""
        g = Graph0(graph_version=5)
        assert g.graph_version == 5

    def test_version_increments(self) -> None:
        g = Graph0(graph_version=1)
        g.graph_version += 1
        assert g.graph_version == 2
