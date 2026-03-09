"""Snapshot tests for JSON output stability.

Task O-030: Verify JSON schema output stability.
"""

from __future__ import annotations

import json

import pytest

from codegraph.models.graph0 import Graph0, Graph0Node
from codegraph.models.graph1 import Graph1, Graph1Node
from codegraph.models.workflow import Workflow, WorkflowEdge


class TestGraph0Snapshot:
    """Verify Graph0 JSON structure is stable."""

    def test_structure_keys(self) -> None:
        g = Graph0()
        g.add_node(Graph0Node(id="a.py::f", body_hash="h", file="a.py", type="function", line=1))
        data = json.loads(g.to_json())
        assert "format_version" in data
        assert "graph_version" in data
        assert "nodes" in data
        assert "extracted_at" in data
        node = data["nodes"][0]
        assert set(node.keys()) >= {"id", "body_hash", "file", "type", "line"}

    def test_node_types_are_strings(self) -> None:
        g = Graph0()
        g.add_node(Graph0Node(id="a", body_hash="h", file="a.py", type="function", line=1))
        data = json.loads(g.to_json())
        assert isinstance(data["nodes"][0]["type"], str)


class TestGraph1Snapshot:
    """Verify Graph1 JSON structure is stable."""

    def test_structure_keys(self) -> None:
        g = Graph1()
        g.upsert_node(Graph1Node(id="a", intent="test intent", layer=3))
        data = json.loads(g.to_json())
        assert "format_version" in data
        assert "nodes" in data
        node = data["nodes"][0]
        assert set(node.keys()) >= {"id", "intent", "layer"}


class TestWorkflowSnapshot:
    """Verify Workflow JSON structure is stable."""

    def test_structure_keys(self) -> None:
        wf = Workflow()
        wf.add_edge(WorkflowEdge(source="a", target="b", edge_type="call", confidence="static"))
        data = json.loads(wf.to_json())
        assert "format_version" in data
        assert "edges" in data
        edge = data["edges"][0]
        assert set(edge.keys()) >= {"source", "target", "edge_type", "confidence"}


class TestSchemaSnapshot:
    """Verify JSON schemas exist and are parseable."""

    def test_graph0_schema(self) -> None:
        import importlib.resources as res
        text = (res.files("codegraph.schemas") / "graph0.schema.json").read_text(encoding="utf-8")
        data = json.loads(text)
        assert "properties" in data or "$schema" in data or "type" in data

    def test_workflow_schema(self) -> None:
        import importlib.resources as res
        text = (res.files("codegraph.schemas") / "workflow.schema.json").read_text(encoding="utf-8")
        data = json.loads(text)
        assert isinstance(data, dict)
