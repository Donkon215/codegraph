"""Tests for codegraph.precommit — Pre-commit simulation gate."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from codegraph.precommit import (
    SimulationCheck,
    PreCommitReport,
    DEFAULT_THRESHOLDS,
    run_pre_commit_check,
    _check_metric,
    _load_baseline,
    _save_baseline,
    _compute_current_metrics,
)


# ── Data Classes ──────────────────────────────────────────────────────


class TestSimulationCheck:
    def test_basic(self):
        c = SimulationCheck(
            metric="score", before=0.7, after=0.65,
            delta=-0.05, status="block", threshold=-0.05,
        )
        d = c.to_dict()
        assert d["metric"] == "score"
        assert d["status"] == "block"
        assert d["delta"] == -0.05

    def test_pass_status(self):
        c = SimulationCheck(
            metric="coupling", before=0.3, after=0.3,
            delta=0.0, status="pass", threshold=0.1,
        )
        assert c.status == "pass"


class TestPreCommitReport:
    def test_empty_report(self):
        r = PreCommitReport()
        assert r.passed is True
        assert r.blocked == 0
        assert r.warnings == 0
        d = r.to_dict()
        assert d["passed"] is True

    def test_with_checks(self):
        r = PreCommitReport()
        r.checks.append(SimulationCheck(
            metric="score", before=0.7, after=0.65,
            delta=-0.05, status="block", threshold=-0.05,
        ))
        r.checks.append(SimulationCheck(
            metric="coupling", before=0.3, after=0.35,
            delta=0.05, status="warn", threshold=0.1,
        ))
        r.blocked = 1
        r.warnings = 1
        r.passed = False
        d = r.to_dict()
        assert d["passed"] is False
        assert len(d["checks"]) == 2

    def test_format(self):
        r = PreCommitReport()
        r.checks.append(SimulationCheck(
            metric="cycles", before=0, after=1,
            delta=1, status="block", threshold=1,
        ))
        r.blocked = 1
        r.passed = False
        text = r.format()
        assert "BLOCKED" in text
        assert "cycles" in text

    def test_format_passed(self):
        r = PreCommitReport()
        text = r.format()
        assert "PASSED" in text


# ── Check Metric ──────────────────────────────────────────────────────


class TestCheckMetric:
    def test_no_change(self):
        r = PreCommitReport()
        _check_metric(r, "score", {"score": 0.7}, {"score": 0.7}, -0.05, "block")
        assert len(r.checks) == 1
        assert r.checks[0].status == "pass"

    def test_worsening_blocks(self):
        r = PreCommitReport()
        _check_metric(r, "score", {"score": 0.7}, {"score": 0.6}, -0.05, "block")
        assert r.checks[0].status == "block"

    def test_warning(self):
        r = PreCommitReport()
        _check_metric(r, "coupling", {"coupling": 0.3}, {"coupling": 0.45}, 0.1, "warn", invert=True)
        assert r.checks[0].status == "warn"

    def test_inverted_metric(self):
        r = PreCommitReport()
        _check_metric(r, "coupling", {"coupling": 0.3}, {"coupling": 0.5}, 0.1, "warn", invert=True)
        assert r.checks[0].status == "warn"

    def test_within_threshold(self):
        r = PreCommitReport()
        _check_metric(r, "score", {"score": 0.7}, {"score": 0.68}, -0.05, "block")
        assert r.checks[0].status == "pass"


# ── Baseline ──────────────────────────────────────────────────────────


class TestBaseline:
    def test_save_and_load(self, tmp_path):
        metrics = {"score": 0.75, "coupling": 0.3}
        _save_baseline(tmp_path, metrics)
        loaded = _load_baseline(tmp_path)
        assert loaded["score"] == 0.75
        assert loaded["coupling"] == 0.3

    def test_load_missing(self, tmp_path):
        loaded = _load_baseline(tmp_path)
        assert loaded == {}


# ── Default Thresholds ────────────────────────────────────────────────


class TestDefaultThresholds:
    def test_has_required_metrics(self):
        assert "score" in DEFAULT_THRESHOLDS
        assert "coupling" in DEFAULT_THRESHOLDS
        assert "cycles" in DEFAULT_THRESHOLDS

    def test_score_is_negative(self):
        assert DEFAULT_THRESHOLDS["score"] < 0

    def test_coupling_is_positive(self):
        assert DEFAULT_THRESHOLDS["coupling"] > 0


# ── Integration ───────────────────────────────────────────────────────


class TestRunPreCommitCheck:
    def test_no_baseline_creates_one(self, tmp_path):
        # Create minimal .codegraph structure
        cg = tmp_path / ".codegraph"
        arch_dir = cg / "architecture"
        arch_dir.mkdir(parents=True)
        (arch_dir / "architecture_advice.json").write_text(
            json.dumps({"score": 0.7, "smells": []}))
        wf_dir = cg / "workflow"
        wf_dir.mkdir(parents=True)
        (wf_dir / "workflow.json").write_text(
            json.dumps({"edges": []}))

        report = run_pre_commit_check(tmp_path)
        assert report.passed is True
        # Baseline should now exist
        assert _load_baseline(tmp_path) != {}
