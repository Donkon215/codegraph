"""Tests for codegraph.arch_evolution — Architecture Evolution Engine."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from codegraph.arch_evolution import (
    EvolutionStage,
    EvolutionResult,
    EvolutionReport,
    run_evolution_cycle,
    run_evolution,
    save_evolution_report,
    _skip_remaining,
    _apply_memory_boost,
    _generate_evolution_recommendations,
)


# ── Data Classes ──────────────────────────────────────────────────────


class TestEvolutionStage:
    def test_basic(self):
        s = EvolutionStage(name="detect")
        assert s.status == "pending"
        d = s.to_dict()
        assert d["name"] == "detect"
        assert "details" not in d  # empty details omitted

    def test_with_details(self):
        s = EvolutionStage(name="mutate", status="passed",
                           details="3 candidates", metrics={"k": 1})
        d = s.to_dict()
        assert d["details"] == "3 candidates"
        assert d["metrics"]["k"] == 1


class TestEvolutionResult:
    def test_defaults(self):
        r = EvolutionResult()
        assert r.cycle == 1
        assert r.status == "pending"
        assert r.score_delta == 0.0

    def test_to_dict(self):
        r = EvolutionResult(
            cycle=2, status="improved",
            score_before=0.6, score_after=0.7, score_delta=0.1,
            selected_strategy="fan_out_reduction",
            selected_target="cli.py",
            stages=[EvolutionStage("detect", "passed")],
        )
        d = r.to_dict()
        assert d["cycle"] == 2
        assert d["score_delta"] == 0.1
        assert len(d["stages"]) == 1

    def test_format_improved(self):
        r = EvolutionResult(
            cycle=1, status="improved",
            score_before=0.5, score_after=0.6, score_delta=0.1,
            selected_strategy="module_split",
            stages=[
                EvolutionStage("detect", "passed", "2 smells"),
                EvolutionStage("record", "passed"),
            ],
        )
        text = r.format()
        assert "improved" in text
        assert "module_split" in text
        assert "0.500" in text

    def test_format_blocked(self):
        r = EvolutionResult(
            cycle=1, status="blocked",
            recommendations=["fix policies"],
            stages=[EvolutionStage("policy", "failed", "1 blocking")],
        )
        text = r.format()
        assert "blocked" in text
        assert "fix policies" in text


class TestEvolutionReport:
    def test_from_results_empty(self):
        report = EvolutionReport.from_results([])
        assert report.converged is False
        assert report.total_improvement == 0.0

    def test_from_results_converged(self):
        r1 = EvolutionResult(
            cycle=1, status="improved", score_delta=0.05,
            selected_strategy="fan_out_reduction",
        )
        r2 = EvolutionResult(cycle=2, status="no_change", score_delta=0.0)
        report = EvolutionReport.from_results([r1, r2])
        assert report.converged is True
        assert report.total_improvement == pytest.approx(0.05)
        assert report.strategies_used == ["fan_out_reduction"]

    def test_to_dict(self):
        r = EvolutionReport(
            cycles=[EvolutionResult(cycle=1, status="no_change")],
            total_improvement=0.01, converged=True,
        )
        d = r.to_dict()
        assert d["total_cycles"] == 1
        assert d["converged"] is True

    def test_format(self):
        report = EvolutionReport.from_results([
            EvolutionResult(cycle=1, status="improved", score_delta=0.03,
                            selected_strategy="cycle_break",
                            stages=[EvolutionStage("detect", "passed")]),
        ])
        text = report.format()
        assert "Evolution Report" in text
        assert "cycle_break" in text


# ── Helper Functions ──────────────────────────────────────────────────


class TestSkipRemaining:
    def test_skips_after_named_stage(self):
        result = EvolutionResult(stages=[
            EvolutionStage("detect", "passed"),
            EvolutionStage("memory", "pending"),
            EvolutionStage("mutate", "pending"),
        ])
        _skip_remaining(result, "detect")
        assert result.stages[0].status == "passed"
        assert result.stages[1].status == "skipped"
        assert result.stages[2].status == "skipped"

    def test_does_not_skip_already_set(self):
        result = EvolutionResult(stages=[
            EvolutionStage("detect", "passed"),
            EvolutionStage("memory", "failed"),
            EvolutionStage("mutate", "pending"),
        ])
        _skip_remaining(result, "detect")
        assert result.stages[1].status == "failed"  # not overwritten
        assert result.stages[2].status == "skipped"


class TestApplyMemoryBoost:
    def test_no_ranking(self):
        selected = {"strategy": "fan_out_reduction"}
        assert _apply_memory_boost(selected, []) is False

    def test_boost_applied(self):
        selected = {"strategy": "module_split"}
        ranking = [{"strategy": "module_split", "effectiveness": 0.8}]
        assert _apply_memory_boost(selected, ranking) is True

    def test_no_boost_low_effectiveness(self):
        selected = {"strategy": "cycle_break"}
        ranking = [{"strategy": "cycle_break", "effectiveness": 0.3}]
        assert _apply_memory_boost(selected, ranking) is False

    def test_no_boost_different_strategy(self):
        selected = {"strategy": "fan_out_reduction"}
        ranking = [{"strategy": "module_split", "effectiveness": 0.9}]
        assert _apply_memory_boost(selected, ranking) is False


class TestGenerateEvolutionRecommendations:
    def test_significant_improvement(self):
        r = EvolutionResult(status="improved", score_delta=0.1,
                            selected_strategy="module_split")
        recs = _generate_evolution_recommendations(r, [])
        assert any("another cycle" in r for r in recs)

    def test_blocked_recommendation(self):
        r = EvolutionResult(status="blocked")
        recs = _generate_evolution_recommendations(r, [])
        assert any("blocked" in r.lower() for r in recs)

    def test_suggests_effective_strategy(self):
        r = EvolutionResult(status="improved", score_delta=0.01,
                            selected_strategy="fan_out_reduction")
        ranking = [
            {"strategy": "module_split", "effectiveness": 0.85},
        ]
        recs = _generate_evolution_recommendations(r, ranking)
        assert any("module_split" in r for r in recs)

    def test_no_duplicate_current_strategy(self):
        r = EvolutionResult(status="improved", score_delta=0.01,
                            selected_strategy="module_split")
        ranking = [
            {"strategy": "module_split", "effectiveness": 0.85},
        ]
        recs = _generate_evolution_recommendations(r, ranking)
        # Should not suggest the strategy already selected
        assert not any("module_split" in r for r in recs)


# ── Integration Tests (mocked) ───────────────────────────────────────


class TestRunEvolutionCycleMocked:
    """Test evolution cycle with mocked external dependencies."""

    def _make_advice(self, smells=None, score=0.6):
        return {
            "score": score,
            "grade": "D",
            "smells": smells or [{"smell_type": "god_module"}],
            "modularity": 0.3,
            "coupling": 0.4,
            "cycles": 0,
        }

    def _make_search_result(self, strategy="module_split",
                             predicted=0.7, safe=True):
        return {
            "candidates": [
                {"strategy": strategy, "predicted_score": predicted},
            ],
            "selected": {
                "strategy": strategy,
                "predicted_score": predicted,
                "target_modules": ["cli.py"],
                "simulation_safe": safe,
            },
        }

    @patch("codegraph.arch_evolution._record_metrics_snapshot")
    @patch("codegraph.arch_evolution._record_to_memory")
    @patch("codegraph.arch_evolution._check_policies")
    @patch("codegraph.arch_evolution._get_strategy_ranking")
    @patch("codegraph.arch_evolution._run_arch_search")
    @patch("codegraph.arch_evolution._run_advisor")
    def test_full_success(self, mock_advisor, mock_search, mock_ranking,
                          mock_policies, mock_record, mock_snapshot):
        mock_advisor.return_value = self._make_advice(score=0.6)
        mock_search.return_value = self._make_search_result(predicted=0.7)
        mock_ranking.return_value = []
        mock_policies.return_value = {"violations": []}
        mock_record.return_value = None
        mock_snapshot.return_value = None

        result = run_evolution_cycle(Path("/tmp/test"), cycle=1)
        assert result.status == "improved"
        assert result.score_delta == pytest.approx(0.1)
        assert result.selected_strategy == "module_split"
        assert len(result.stages) == 7

    @patch("codegraph.arch_evolution._run_advisor")
    def test_no_smells(self, mock_advisor):
        mock_advisor.return_value = self._make_advice(smells=[], score=0.9)

        result = run_evolution_cycle(Path("/tmp/test"))
        assert result.status == "no_change"
        assert result.score_before == 0.9

    @patch("codegraph.arch_evolution._run_advisor")
    def test_advisor_failure(self, mock_advisor):
        mock_advisor.side_effect = RuntimeError("bork")

        result = run_evolution_cycle(Path("/tmp/test"))
        assert result.status == "failed"
        assert result.stages[0].status == "failed"

    @patch("codegraph.arch_evolution._get_strategy_ranking")
    @patch("codegraph.arch_evolution._run_arch_search")
    @patch("codegraph.arch_evolution._run_advisor")
    def test_no_safe_candidate(self, mock_advisor, mock_search, mock_ranking):
        mock_advisor.return_value = self._make_advice(score=0.5)
        mock_search.return_value = {"candidates": [{"strategy": "x"}],
                                     "selected": None}
        mock_ranking.return_value = []

        result = run_evolution_cycle(Path("/tmp/test"))
        assert result.status == "no_change"
        assert any("manual review" in r for r in result.recommendations)

    @patch("codegraph.arch_evolution._check_policies")
    @patch("codegraph.arch_evolution._get_strategy_ranking")
    @patch("codegraph.arch_evolution._run_arch_search")
    @patch("codegraph.arch_evolution._run_advisor")
    def test_policy_blocks(self, mock_advisor, mock_search,
                           mock_ranking, mock_policies):
        mock_advisor.return_value = self._make_advice(score=0.5)
        mock_search.return_value = self._make_search_result()
        mock_ranking.return_value = []
        mock_policies.return_value = {
            "violations": [{"action": "block", "policy_name": "gate"}],
        }

        result = run_evolution_cycle(Path("/tmp/test"))
        assert result.status == "blocked"
        assert result.policy_violations == 1

    @patch("codegraph.arch_evolution._check_policies")
    @patch("codegraph.arch_evolution._get_strategy_ranking")
    @patch("codegraph.arch_evolution._run_arch_search")
    @patch("codegraph.arch_evolution._run_advisor")
    def test_score_degradation_rejected(self, mock_advisor, mock_search,
                                         mock_ranking, mock_policies):
        mock_advisor.return_value = self._make_advice(score=0.7)
        mock_search.return_value = self._make_search_result(predicted=0.5)
        mock_ranking.return_value = []
        mock_policies.return_value = {"violations": []}

        result = run_evolution_cycle(Path("/tmp/test"))
        assert result.status == "blocked"
        assert result.score_delta < -0.02

    @patch("codegraph.arch_evolution._record_metrics_snapshot")
    @patch("codegraph.arch_evolution._record_to_memory")
    @patch("codegraph.arch_evolution._check_policies")
    @patch("codegraph.arch_evolution._get_strategy_ranking")
    @patch("codegraph.arch_evolution._run_arch_search")
    @patch("codegraph.arch_evolution._run_advisor")
    def test_dry_run_skips_record(self, mock_advisor, mock_search,
                                   mock_ranking, mock_policies,
                                   mock_record, mock_snapshot):
        mock_advisor.return_value = self._make_advice(score=0.6)
        mock_search.return_value = self._make_search_result(predicted=0.7)
        mock_ranking.return_value = []
        mock_policies.return_value = {"violations": []}

        result = run_evolution_cycle(Path("/tmp/test"), dry_run=True)
        mock_record.assert_not_called()
        mock_snapshot.assert_not_called()
        assert result.stages[-1].status == "skipped"

    @patch("codegraph.arch_evolution._check_policies")
    @patch("codegraph.arch_evolution._get_strategy_ranking")
    @patch("codegraph.arch_evolution._run_arch_search")
    @patch("codegraph.arch_evolution._run_advisor")
    def test_simulation_unsafe(self, mock_advisor, mock_search,
                                mock_ranking, mock_policies):
        mock_advisor.return_value = self._make_advice(score=0.6)
        mock_search.return_value = self._make_search_result(safe=False)
        mock_search.return_value["selected"]["simulation_safe"] = False
        mock_ranking.return_value = []
        mock_policies.return_value = {"violations": []}

        result = run_evolution_cycle(Path("/tmp/test"))
        assert result.status == "blocked"


class TestRunEvolution:
    @patch("codegraph.arch_evolution.run_evolution_cycle")
    def test_stops_on_no_change(self, mock_cycle):
        mock_cycle.return_value = EvolutionResult(
            cycle=1, status="no_change",
        )
        results = run_evolution(Path("/tmp/test"), max_cycles=5)
        assert len(results) == 1
        assert mock_cycle.call_count == 1

    @patch("codegraph.arch_evolution.run_evolution_cycle")
    def test_multiple_cycles(self, mock_cycle):
        mock_cycle.side_effect = [
            EvolutionResult(cycle=1, status="improved", score_delta=0.05),
            EvolutionResult(cycle=2, status="no_change"),
        ]
        results = run_evolution(Path("/tmp/test"), max_cycles=5)
        assert len(results) == 2

    @patch("codegraph.arch_evolution.run_evolution_cycle")
    def test_respects_max_cycles(self, mock_cycle):
        mock_cycle.return_value = EvolutionResult(
            cycle=1, status="improved", score_delta=0.01,
        )
        results = run_evolution(Path("/tmp/test"), max_cycles=2)
        assert len(results) == 2


# ── Save Report ───────────────────────────────────────────────────────


class TestSaveEvolutionReport:
    def test_save_and_load(self, tmp_path: Path):
        report = EvolutionReport.from_results([
            EvolutionResult(
                cycle=1, status="improved", score_delta=0.05,
                selected_strategy="module_split",
                stages=[EvolutionStage("detect", "passed")],
            ),
        ])
        path = save_evolution_report(tmp_path, report)
        assert path.exists()
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert loaded["total_cycles"] == 1
        assert loaded["strategies_used"] == ["module_split"]
