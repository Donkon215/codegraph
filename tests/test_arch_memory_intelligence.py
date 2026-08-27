"""Tests for codegraph.arch_memory_intelligence — memory intelligence layer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from codegraph.architecture_memory import (
    DecisionRecord,
    ExperimentRecord,
    ArchitectureMemory,
    load_memory,
    save_memory,
)
from codegraph.arch_memory_intelligence import (
    MetricsSnapshot,
    StrategyScore,
    ArchPattern,
    MemoryIntelligenceReport,
    analyze_memory,
    load_metrics_history,
    mine_patterns,
    record_metrics_snapshot,
    score_strategies,
    generate_recommendations,
    get_strategy_ranking,
    save_strategy_scores,
)


# ── Helpers ────────────────────────────────────────────────────────────


def _setup_memory(
    tmp_path: Path,
    decisions: list[DecisionRecord] | None = None,
    experiments: list[ExperimentRecord] | None = None,
) -> ArchitectureMemory:
    """Create and persist an ArchitectureMemory in tmp_path."""
    mem = ArchitectureMemory(
        decisions=decisions or [],
        experiments=experiments or [],
    )
    save_memory(tmp_path, mem)
    return mem


def _make_codegraph_dirs(tmp_path: Path) -> None:
    (tmp_path / ".codegraph" / "memory").mkdir(parents=True, exist_ok=True)


# ── MetricsSnapshot ───────────────────────────────────────────────────


class TestMetricsSnapshot:
    def test_round_trip(self):
        snap = MetricsSnapshot(
            timestamp="2026-01-01T00:00:00Z",
            score=0.75, grade="C", modularity=0.4,
        )
        d = snap.to_dict()
        restored = MetricsSnapshot.from_dict(d)
        assert restored.score == 0.75
        assert restored.grade == "C"

    def test_defaults(self):
        snap = MetricsSnapshot(timestamp="t")
        assert snap.score == 0.0
        assert snap.trigger == ""


# ── StrategyScore ──────────────────────────────────────────────────────


class TestStrategyScore:
    def test_round_trip(self):
        s = StrategyScore(
            strategy="module_split", times_used=5,
            times_succeeded=4, effectiveness=0.8,
        )
        d = s.to_dict()
        restored = StrategyScore.from_dict(d)
        assert restored.strategy == "module_split"
        assert restored.effectiveness == 0.8

    def test_to_dict_rounding(self):
        s = StrategyScore(
            strategy="x", avg_score_improvement=0.12345678,
        )
        d = s.to_dict()
        assert d["avg_score_improvement"] == 0.1235


# ── Pattern Mining ─────────────────────────────────────────────────────


class TestMinePatterns:
    def test_empty_memory(self):
        mem = ArchitectureMemory()
        patterns = mine_patterns(mem)
        assert patterns == []

    def test_mines_tag_patterns(self):
        mem = ArchitectureMemory(decisions=[
            DecisionRecord(decision_id="d1", decision="split cli",
                         reason="too big", result="success",
                         health_delta=0.05, tags=["refactor"]),
            DecisionRecord(decision_id="d2", decision="split apply",
                         reason="god module", result="success",
                         health_delta=0.03, tags=["refactor"]),
        ])
        patterns = mine_patterns(mem)
        refactor_patterns = [p for p in patterns
                             if "refactor" in p.tags]
        assert len(refactor_patterns) == 1
        assert refactor_patterns[0].frequency == 2
        assert refactor_patterns[0].avg_impact > 0

    def test_mines_experiment_patterns(self):
        mem = ArchitectureMemory(experiments=[
            ExperimentRecord(
                experiment_id="e1", branch_name="fix-cycles",
                description="break cycles", outcome="merged",
                health_before=0.5, health_after=0.7,
            ),
        ])
        patterns = mine_patterns(mem)
        exp_patterns = [p for p in patterns if "experiment" in p.tags]
        assert len(exp_patterns) == 1
        assert exp_patterns[0].avg_impact == pytest.approx(0.2)


# ── Strategy Scoring ──────────────────────────────────────────────────


class TestScoreStrategies:
    def test_empty_memory(self):
        mem = ArchitectureMemory()
        scores = score_strategies(mem)
        assert scores == []

    def test_scores_from_decisions(self):
        mem = ArchitectureMemory(decisions=[
            DecisionRecord(decision_id="d1", decision="split module",
                         reason="god module", result="success",
                         health_delta=0.05, tags=["module_split"]),
            DecisionRecord(decision_id="d2", decision="split another module",
                         reason="god module", result="success",
                         health_delta=0.03, tags=["module_split"]),
        ])
        scores = score_strategies(mem)
        assert len(scores) >= 1
        split_score = next(s for s in scores if s.strategy == "module_split")
        assert split_score.times_used == 2
        assert split_score.times_succeeded == 2
        assert split_score.effectiveness > 0.5

    def test_scores_from_experiments(self):
        mem = ArchitectureMemory(experiments=[
            ExperimentRecord(
                experiment_id="e1",
                branch_name="codegraph/refactor-fan-out",
                description="fan out reduction in cli",
                outcome="merged",
                health_before=0.5, health_after=0.6,
            ),
        ])
        scores = score_strategies(mem)
        # Should infer "refactor" strategy from branch name
        assert len(scores) >= 1


# ── Record Metrics ─────────────────────────────────────────────────────


class TestRecordMetrics:
    def test_record_and_load(self, tmp_path: Path):
        _make_codegraph_dirs(tmp_path)
        snap = record_metrics_snapshot(
            tmp_path, score=0.7, grade="C", modularity=0.4,
            trigger="test",
        )
        assert snap.score == 0.7

        history = load_metrics_history(tmp_path)
        assert len(history) == 1
        assert history[0].grade == "C"

    def test_append_multiple(self, tmp_path: Path):
        _make_codegraph_dirs(tmp_path)
        record_metrics_snapshot(tmp_path, score=0.5, grade="D")
        record_metrics_snapshot(tmp_path, score=0.6, grade="C")
        record_metrics_snapshot(tmp_path, score=0.7, grade="B")

        history = load_metrics_history(tmp_path)
        assert len(history) == 3
        assert history[-1].score == 0.7


# ── Recommendations ───────────────────────────────────────────────────


class TestRecommendations:
    def test_empty_data(self):
        recs = generate_recommendations(ArchitectureMemory(), [], [])
        assert any("No architecture decisions" in r for r in recs)

    def test_trend_up(self):
        history = [
            MetricsSnapshot(timestamp="t1", score=0.5),
            MetricsSnapshot(timestamp="t2", score=0.6),
            MetricsSnapshot(timestamp="t3", score=0.7),
        ]
        recs = generate_recommendations(ArchitectureMemory(), history, [])
        assert any("trending up" in r for r in recs)

    def test_trend_down(self):
        history = [
            MetricsSnapshot(timestamp="t1", score=0.7),
            MetricsSnapshot(timestamp="t2", score=0.6),
            MetricsSnapshot(timestamp="t3", score=0.5),
        ]
        recs = generate_recommendations(ArchitectureMemory(), history, [])
        assert any("trending down" in r for r in recs)

    def test_effective_strategy(self):
        scores = [
            StrategyScore(strategy="module_split", times_used=5,
                          times_succeeded=4, effectiveness=0.8),
        ]
        recs = generate_recommendations(ArchitectureMemory(), [], scores)
        assert any("module_split" in r for r in recs)


# ── Full Pipeline ──────────────────────────────────────────────────────


class TestAnalyzeMemory:
    def test_empty_project(self, tmp_path: Path):
        _make_codegraph_dirs(tmp_path)
        _setup_memory(tmp_path)
        report = analyze_memory(tmp_path)
        assert isinstance(report, MemoryIntelligenceReport)
        assert len(report.strategy_scores) == 0

    def test_with_data(self, tmp_path: Path):
        _make_codegraph_dirs(tmp_path)
        _setup_memory(tmp_path, decisions=[
            DecisionRecord(decision_id="d1", decision="test",
                         reason="r", result="success",
                         health_delta=0.1, tags=["module_split"]),
            DecisionRecord(decision_id="d2", decision="test2",
                         reason="r", result="success",
                         health_delta=0.05, tags=["module_split"]),
        ])
        report = analyze_memory(tmp_path)
        assert len(report.strategy_scores) >= 1
        assert len(report.patterns) >= 1


# ── Report Formatting ─────────────────────────────────────────────────


class TestReportFormatting:
    def test_format_empty(self):
        report = MemoryIntelligenceReport()
        text = report.format()
        assert "Architecture Memory Intelligence" in text

    def test_to_dict(self):
        report = MemoryIntelligenceReport()
        d = report.to_dict()
        assert "summary" in d
        assert d["summary"]["strategies_analyzed"] == 0


# ── Save Strategy Scores ──────────────────────────────────────────────


class TestSaveStrategyScores:
    def test_save_and_verify(self, tmp_path: Path):
        _make_codegraph_dirs(tmp_path)
        scores = [
            StrategyScore(strategy="test", effectiveness=0.5),
        ]
        path = save_strategy_scores(tmp_path, scores)
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert len(data) == 1
