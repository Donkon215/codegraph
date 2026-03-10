"""Tests for codegraph.branch_executor — git branch execution."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from codegraph.branch_executor import (
    BranchMetrics,
    BranchState,
    BranchComparison,
    capture_metrics,
    compare_branches,
    load_branch_state,
    update_branch_status,
)


class TestBranchMetrics:
    def test_default_values(self):
        m = BranchMetrics()
        assert m.node_count == 0
        assert m.health_score == 0.0
        assert m.tests_passed is True

    def test_roundtrip(self):
        m = BranchMetrics(
            node_count=100, edge_count=200,
            policy_violations=3, cycles=1,
            health_score=0.85, test_count=50,
            fan_out_max=12, fan_in_max=8,
            coupling_avg=0.1234,
        )
        d = m.to_dict()
        assert d["node_count"] == 100
        assert d["health_score"] == 0.85
        assert d["coupling_avg"] == 0.1234

        restored = BranchMetrics.from_dict(d)
        assert restored.node_count == 100
        assert restored.edge_count == 200
        assert restored.fan_out_max == 12

    def test_from_dict_defaults(self):
        m = BranchMetrics.from_dict({})
        assert m.node_count == 0
        assert m.tests_passed is True


class TestBranchState:
    def test_minimal(self):
        s = BranchState(branch_name="codegraph/test")
        assert s.status == "created"
        assert s.base_branch == "master"

    def test_roundtrip(self):
        base_m = BranchMetrics(node_count=10)
        s = BranchState(
            branch_name="codegraph/feature-x",
            base_branch="master",
            status="validating",
            base_metrics=base_m,
            tasks_total=5,
            tasks_completed=2,
        )
        d = s.to_dict()
        assert d["branch_name"] == "codegraph/feature-x"
        assert d["status"] == "validating"
        assert d["base_metrics"]["node_count"] == 10

        restored = BranchState.from_dict(d)
        assert restored.branch_name == "codegraph/feature-x"
        assert restored.base_metrics is not None
        assert restored.base_metrics.node_count == 10

    def test_without_metrics(self):
        s = BranchState(branch_name="test")
        d = s.to_dict()
        assert "base_metrics" not in d
        assert "branch_metrics" not in d

        restored = BranchState.from_dict(d)
        assert restored.base_metrics is None


class TestBranchComparison:
    def test_to_dict(self):
        c = BranchComparison(
            base_branch="master",
            feature_branch="codegraph/test",
            health_delta=0.15,
            cycle_delta=-1,
            violation_delta=0,
            recommendation="merge",
        )
        d = c.to_dict()
        assert d["health_delta"] == 0.15
        assert d["recommendation"] == "merge"

    def test_format(self):
        c = BranchComparison(
            base_branch="master",
            feature_branch="codegraph/test",
            health_delta=-0.5,
            recommendation="reject",
        )
        text = c.format()
        assert "master" in text
        assert "reject" in text


class TestCompareBranches:
    def test_improvement_recommends_merge(self):
        base = BranchMetrics(
            cycles=3, policy_violations=5,
            health_score=0.5, coupling_avg=0.3,
        )
        branch = BranchMetrics(
            cycles=1, policy_violations=2,
            health_score=0.7, coupling_avg=0.2,
        )
        comp = compare_branches(base, branch)
        assert comp.recommendation == "merge"
        assert comp.cycle_delta == -2
        assert comp.violation_delta == -3

    def test_degradation_recommends_reject(self):
        base = BranchMetrics(
            cycles=0, policy_violations=0,
            health_score=0.9,
        )
        branch = BranchMetrics(
            cycles=3, policy_violations=5,
            health_score=0.3, tests_passed=False,
        )
        comp = compare_branches(base, branch)
        assert comp.recommendation == "reject"

    def test_mixed_recommends_review(self):
        base = BranchMetrics(cycles=0, policy_violations=2, health_score=0.7)
        branch = BranchMetrics(cycles=0, policy_violations=0, health_score=0.65)
        comp = compare_branches(base, branch)
        assert comp.recommendation == "review"

    def test_no_change_recommends_review(self):
        base = BranchMetrics(health_score=0.7)
        branch = BranchMetrics(health_score=0.7)
        comp = compare_branches(base, branch)
        assert comp.recommendation == "review"

    def test_custom_names(self):
        base = BranchMetrics()
        branch = BranchMetrics()
        comp = compare_branches(base, branch, base_name="main",
                                branch_name="codegraph/test")
        assert comp.base_branch == "main"
        assert comp.feature_branch == "codegraph/test"


class TestCaptureMetrics:
    def test_reads_graph_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            graphs_dir = root / ".codegraph" / "graphs"
            graphs_dir.mkdir(parents=True)
            wf_dir = root / ".codegraph" / "workflow"
            wf_dir.mkdir(parents=True)

            # Write mock graph0
            g0 = {"nodes": [{"id": "a::f"}, {"id": "b::g"}]}
            (graphs_dir / "graph0.json").write_text(
                json.dumps(g0), encoding="utf-8"
            )
            # Write mock workflow
            wf = {"edges": [
                {"source": "a::f", "target": "b::g"},
                {"source": "a::f", "target": "c::h"},
            ]}
            (wf_dir / "workflow.json").write_text(
                json.dumps(wf), encoding="utf-8"
            )

            metrics = capture_metrics(root)
            assert metrics.node_count == 2
            assert metrics.edge_count == 2
            assert metrics.fan_out_max == 2  # a::f has 2 outgoing

    def test_empty_project(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            metrics = capture_metrics(Path(tmpdir))
            assert metrics.node_count == 0


class TestLoadBranchState:
    def test_load_nonexistent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            assert load_branch_state(Path(tmpdir)) is None

    def test_load_existing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            git_dir = root / ".codegraph" / "git"
            git_dir.mkdir(parents=True)
            state = {
                "branch_name": "codegraph/test",
                "base_branch": "master",
                "status": "created",
            }
            (git_dir / "branch.json").write_text(
                json.dumps(state), encoding="utf-8"
            )
            loaded = load_branch_state(root)
            assert loaded is not None
            assert loaded.branch_name == "codegraph/test"


class TestUpdateBranchStatus:
    def test_update_status(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            git_dir = root / ".codegraph" / "git"
            git_dir.mkdir(parents=True)
            state = {
                "branch_name": "codegraph/test",
                "base_branch": "master",
                "status": "created",
            }
            (git_dir / "branch.json").write_text(
                json.dumps(state), encoding="utf-8"
            )

            update_branch_status(root, "validating")
            loaded = load_branch_state(root)
            assert loaded.status == "validating"
