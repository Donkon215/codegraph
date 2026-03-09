"""Tests for codegraph.arch_diff — architecture diff engine."""

import json
import tempfile
from pathlib import Path

import pytest

from codegraph.arch_diff import (
    EdgeChange,
    NodeChange,
    MetricDelta,
    ArchDiffReport,
    diff_graphs,
    save_snapshot,
    diff_snapshots,
)


class TestEdgeChange:
    def test_to_dict(self):
        e = EdgeChange("a::f", "b::g", "added")
        d = e.to_dict()
        assert d["source"] == "a::f"
        assert d["change"] == "added"


class TestNodeChange:
    def test_to_dict(self):
        n = NodeChange("a::f", "a.py", "removed")
        d = n.to_dict()
        assert d["node_id"] == "a::f"
        assert d["file"] == "a.py"


class TestMetricDelta:
    def test_regression_flag(self):
        m = MetricDelta("edge_density", 1.0, 1.5, 0.5, regression=True)
        d = m.to_dict()
        assert d["regression"] is True
        assert d["delta"] == 0.5


class TestArchDiffReport:
    def test_empty_report(self):
        r = ArchDiffReport()
        assert not r.has_changes
        assert not r.has_regression

    def test_has_changes(self):
        r = ArchDiffReport(
            added_edges=[EdgeChange("a", "b", "added")]
        )
        assert r.has_changes

    def test_format(self):
        r = ArchDiffReport(
            added_nodes=[NodeChange("n1", "f1.py", "added")],
            removed_edges=[EdgeChange("a", "b", "removed")],
        )
        text = r.format()
        assert "+1" in text
        assert "-1" in text

    def test_to_dict_summary(self):
        r = ArchDiffReport(
            added_edges=[EdgeChange("a", "b", "added")],
            regressions=["Something bad"],
        )
        d = r.to_dict()
        assert d["summary"]["edges_added"] == 1
        assert d["summary"]["has_regression"] is True


class TestDiffGraphs:
    def test_no_changes(self):
        """Identical graphs should show no changes."""
        graph = {"nodes": [{"id": "a::f", "file": "a.py"}]}
        workflow = {"edges": [{"source": "a::f", "target": "b::g"}]}
        report = diff_graphs(graph, graph, workflow, workflow)
        assert len(report.added_nodes) == 0
        assert len(report.removed_nodes) == 0
        assert len(report.added_edges) == 0
        assert len(report.removed_edges) == 0

    def test_added_node(self):
        old_graph = {"nodes": [{"id": "a::f", "file": "a.py"}]}
        new_graph = {"nodes": [
            {"id": "a::f", "file": "a.py"},
            {"id": "b::g", "file": "b.py"},
        ]}
        workflow = {"edges": []}
        report = diff_graphs(old_graph, new_graph, workflow, workflow)
        assert len(report.added_nodes) == 1
        assert report.added_nodes[0].node_id == "b::g"

    def test_removed_node(self):
        old_graph = {"nodes": [
            {"id": "a::f", "file": "a.py"},
            {"id": "b::g", "file": "b.py"},
        ]}
        new_graph = {"nodes": [{"id": "a::f", "file": "a.py"}]}
        workflow = {"edges": []}
        report = diff_graphs(old_graph, new_graph, workflow, workflow)
        assert len(report.removed_nodes) == 1

    def test_added_edge(self):
        graph = {"nodes": [{"id": "a::f", "file": "a.py"}]}
        old_wf = {"edges": []}
        new_wf = {"edges": [{"source": "a::f", "target": "b::g"}]}
        report = diff_graphs(graph, graph, old_wf, new_wf)
        assert len(report.added_edges) == 1
        assert report.added_edges[0].source == "a::f"

    def test_removed_edge(self):
        graph = {"nodes": [{"id": "a::f", "file": "a.py"}]}
        old_wf = {"edges": [{"source": "a::f", "target": "b::g"}]}
        new_wf = {"edges": []}
        report = diff_graphs(graph, graph, old_wf, new_wf)
        assert len(report.removed_edges) == 1

    def test_new_cycle_detected(self):
        graph = {"nodes": [
            {"id": "a", "file": "a.py"},
            {"id": "b", "file": "b.py"},
        ]}
        old_wf = {"edges": [{"source": "a", "target": "b"}]}
        new_wf = {"edges": [
            {"source": "a", "target": "b"},
            {"source": "b", "target": "a"},
        ]}
        report = diff_graphs(graph, graph, old_wf, new_wf)
        assert len(report.new_cycles) >= 1
        assert any("cycle" in r.lower() for r in report.regressions)

    def test_resolved_cycle(self):
        graph = {"nodes": [
            {"id": "a", "file": "a.py"},
            {"id": "b", "file": "b.py"},
        ]}
        old_wf = {"edges": [
            {"source": "a", "target": "b"},
            {"source": "b", "target": "a"},
        ]}
        new_wf = {"edges": [{"source": "a", "target": "b"}]}
        report = diff_graphs(graph, graph, old_wf, new_wf)
        assert len(report.resolved_cycles) >= 1

    def test_metric_deltas_present(self):
        old_graph = {"nodes": [{"id": "a", "file": "a.py"}]}
        new_graph = {"nodes": [
            {"id": "a", "file": "a.py"},
            {"id": "b", "file": "b.py"},
            {"id": "c", "file": "c.py"},
        ]}
        workflow = {"edges": []}
        report = diff_graphs(old_graph, new_graph, workflow, workflow)
        metric_names = {m.metric for m in report.metric_deltas}
        assert "node_count" in metric_names
        assert "edge_count" in metric_names

    def test_empty_graphs(self):
        report = diff_graphs({"nodes": []}, {"nodes": []},
                             {"edges": []}, {"edges": []})
        assert not report.has_changes


class TestSaveSnapshot:
    def test_save_creates_dir(self, tmp_path):
        """Snapshot should create directory and copy files."""
        graphs_dir = tmp_path / ".codegraph" / "graphs"
        graphs_dir.mkdir(parents=True)
        workflow_dir = tmp_path / ".codegraph" / "workflow"
        workflow_dir.mkdir(parents=True)

        (graphs_dir / "graph0.json").write_text(
            json.dumps({"nodes": []}), encoding="utf-8"
        )
        (workflow_dir / "workflow.json").write_text(
            json.dumps({"edges": []}), encoding="utf-8"
        )

        snap_dir = save_snapshot(tmp_path, "v1")
        assert snap_dir.exists()
        assert (snap_dir / "graph0.json").exists()
        assert (snap_dir / "workflow.json").exists()


class TestDiffSnapshots:
    def test_diff_from_snapshot(self, tmp_path):
        """End-to-end: save snapshot, change graph, diff."""
        graphs_dir = tmp_path / ".codegraph" / "graphs"
        graphs_dir.mkdir(parents=True)
        workflow_dir = tmp_path / ".codegraph" / "workflow"
        workflow_dir.mkdir(parents=True)

        # Initial state
        old_graph = {"nodes": [{"id": "a", "file": "a.py"}]}
        old_wf = {"edges": []}
        (graphs_dir / "graph0.json").write_text(
            json.dumps(old_graph), encoding="utf-8"
        )
        (workflow_dir / "workflow.json").write_text(
            json.dumps(old_wf), encoding="utf-8"
        )

        # Save snapshot
        save_snapshot(tmp_path, "baseline")

        # Update current state
        new_graph = {"nodes": [
            {"id": "a", "file": "a.py"},
            {"id": "b", "file": "b.py"},
        ]}
        new_wf = {"edges": [{"source": "a", "target": "b"}]}
        (graphs_dir / "graph0.json").write_text(
            json.dumps(new_graph), encoding="utf-8"
        )
        (workflow_dir / "workflow.json").write_text(
            json.dumps(new_wf), encoding="utf-8"
        )

        # Diff
        report = diff_snapshots(tmp_path, "baseline")
        assert len(report.added_nodes) == 1
        assert len(report.added_edges) == 1
