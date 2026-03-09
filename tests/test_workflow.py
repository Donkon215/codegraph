"""Unit tests for workflow edge building and edge utilities.

Task O-008: Workflow edge construction.
"""

from __future__ import annotations

import pytest

from codegraph.models.workflow import (
    Workflow,
    WorkflowEdge,
    deduplicate_edges,
    compare_edges,
    best_edge_for,
    Confidence,
)


class TestEdgeBuilding:
    """Test edge construction from analysis data."""

    def test_simple_call_edge(self) -> None:
        e = WorkflowEdge(source="a", target="b", edge_type="call", confidence="static")
        assert e.source == "a"
        assert e.target == "b"

    def test_edge_with_source_detail(self) -> None:
        e = WorkflowEdge(source="a", target="b", source_detail="test_file.py")
        assert e.source_detail == "test_file.py"

    def test_conditional_edge(self) -> None:
        e = WorkflowEdge(source="a", target="b", conditional=True)
        assert e.conditional is True

    def test_edge_serialization(self) -> None:
        e = WorkflowEdge(source="a", target="b", edge_type="trace", confidence="runtime")
        d = e.to_dict()
        assert d["source"] == "a"
        assert d["edge_type"] == "trace"
        restored = WorkflowEdge.from_dict(d)
        assert restored == e


class TestEdgeDeduplication:
    """Test duplicate edge removal."""

    def test_removes_exact_duplicates(self) -> None:
        edges = [
            WorkflowEdge(source="a", target="b"),
            WorkflowEdge(source="a", target="b"),
        ]
        result = deduplicate_edges(edges)
        assert len(result) == 1

    def test_preserves_different_edges(self) -> None:
        edges = [
            WorkflowEdge(source="a", target="b"),
            WorkflowEdge(source="a", target="c"),
        ]
        result = deduplicate_edges(edges)
        assert len(result) == 2

    def test_preserves_order(self) -> None:
        edges = [
            WorkflowEdge(source="a", target="c"),
            WorkflowEdge(source="a", target="b"),
            WorkflowEdge(source="a", target="c"),
        ]
        result = deduplicate_edges(edges)
        assert result[0].target == "c"
        assert result[1].target == "b"


class TestEdgeConfidenceComparison:
    """Test edge confidence ranking."""

    def test_runtime_beats_static(self) -> None:
        e1 = WorkflowEdge(source="a", target="b", confidence="static")
        e2 = WorkflowEdge(source="a", target="b", confidence="runtime")
        best = compare_edges(e1, e2)
        assert best.confidence == "runtime"

    def test_static_beats_ai_inferred(self) -> None:
        e1 = WorkflowEdge(source="a", target="b", confidence="ai_inferred")
        e2 = WorkflowEdge(source="a", target="b", confidence="static")
        best = compare_edges(e1, e2)
        assert best.confidence == "static"

    def test_best_edge_for_multiple(self) -> None:
        edges = [
            WorkflowEdge(source="a", target="b", confidence="ai_inferred"),
            WorkflowEdge(source="a", target="b", confidence="runtime"),
            WorkflowEdge(source="a", target="b", confidence="static"),
        ]
        best = best_edge_for(edges)
        assert best.confidence == "runtime"

    def test_best_edge_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            best_edge_for([])


class TestWorkflowCollection:
    """Test Workflow collection operations."""

    def test_add_and_query(self) -> None:
        wf = Workflow()
        wf.add_edge(WorkflowEdge(source="a", target="b"))
        wf.add_edge(WorkflowEdge(source="a", target="c"))
        assert len(wf.get_edges_from("a")) == 2
        assert len(wf.get_edges_to("b")) == 1

    def test_dynamic_edges(self) -> None:
        wf = Workflow()
        wf.add_edge(WorkflowEdge(source="a", target="mod::*::method"))
        wf.add_edge(WorkflowEdge(source="a", target="b"))
        dynamic = wf.get_dynamic_edges()
        assert len(dynamic) == 1

    def test_json_roundtrip(self) -> None:
        wf = Workflow()
        wf.add_edge(WorkflowEdge(source="a", target="b", edge_type="trace", confidence="runtime"))
        wf.metadata["builder"] = "test"
        text = wf.to_json()
        restored = Workflow.from_json(text)
        assert len(restored.edges) == 1
        assert restored.edges[0].edge_type == "trace"
        assert restored.metadata.get("builder") == "test"
