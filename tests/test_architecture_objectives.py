"""Tests for codegraph.architecture_objectives."""

import pytest

from codegraph.architecture_objectives import (
    CandidateMetrics,
    ObjectiveWeights,
    ScoredCandidate,
    adjust_weights_from_memory,
    compute_objective_score,
    reject_degrading_candidates,
    score_candidates,
)


class TestObjectiveWeights:
    def test_defaults(self):
        w = ObjectiveWeights()
        assert w.modularity == 0.4
        assert w.coupling_reduction == 0.3
        assert w.cycle_reduction == 0.2
        assert w.maintainability == 0.1

    def test_normalize(self):
        w = ObjectiveWeights(0.8, 0.6, 0.4, 0.2)
        n = w.normalize()
        total = n.modularity + n.coupling_reduction + n.cycle_reduction + n.maintainability
        assert abs(total - 1.0) < 1e-9

    def test_normalize_zero(self):
        w = ObjectiveWeights(0, 0, 0, 0)
        n = w.normalize()
        assert n.modularity == 0.4  # defaults

    def test_to_dict_roundtrip(self):
        w = ObjectiveWeights(0.5, 0.2, 0.2, 0.1)
        d = w.to_dict()
        w2 = ObjectiveWeights.from_dict(d)
        assert w2.modularity == w.modularity
        assert w2.coupling_reduction == w.coupling_reduction

    def test_from_dict_missing_keys(self):
        w = ObjectiveWeights.from_dict({})
        assert w.modularity == 0.4  # defaults


class TestComputeObjectiveScore:
    def test_perfect_metrics(self):
        m = CandidateMetrics(1.0, 1.0, 1.0, 1.0)
        score, breakdown = compute_objective_score(m)
        assert abs(score - 1.0) < 1e-9

    def test_zero_metrics(self):
        m = CandidateMetrics(0, 0, 0, 0)
        score, breakdown = compute_objective_score(m)
        assert score == 0.0

    def test_custom_weights(self):
        m = CandidateMetrics(1.0, 0.0, 0.0, 0.0)
        w = ObjectiveWeights(1.0, 0.0, 0.0, 0.0)
        score, breakdown = compute_objective_score(m, w)
        assert abs(score - 1.0) < 1e-9
        assert breakdown["coupling_reduction"] == 0.0

    def test_breakdown_sums_to_total(self):
        m = CandidateMetrics(0.7, 0.5, 0.3, 0.8)
        score, breakdown = compute_objective_score(m)
        assert abs(score - sum(breakdown.values())) < 1e-9


class TestScoreCandidates:
    def test_ranks_by_score(self):
        candidates = [
            {
                "candidate_id": "c1",
                "strategy": "module_split",
                "target_modules": ["a.py"],
                "predicted_score": 0.6,
                "predicted_coupling": 0.3,
                "predicted_cycles": 0,
            },
            {
                "candidate_id": "c2",
                "strategy": "cycle_break",
                "target_modules": ["b.py"],
                "predicted_score": 0.9,
                "predicted_coupling": 0.1,
                "predicted_cycles": 0,
            },
        ]
        baseline = {"score": 0.5, "coupling": 0.5, "cycles": 2}
        scored = score_candidates(candidates, baseline)
        assert scored[0].candidate_id == "c2"
        assert scored[0].objective_score > scored[1].objective_score

    def test_empty_candidates(self):
        assert score_candidates([], {"score": 0.5, "coupling": 0.5, "cycles": 0}) == []

    def test_scored_candidate_to_dict(self):
        sc = ScoredCandidate(
            candidate_id="x",
            strategy="module_split",
            target_modules=["a.py"],
            metrics=CandidateMetrics(0.5, 0.5, 0.5, 0.5),
            objective_score=0.5,
            score_breakdown={"modularity": 0.2},
        )
        d = sc.to_dict()
        assert d["candidate_id"] == "x"
        assert "objective_score" in d
        assert "metrics" in d


class TestRejectDegradingCandidates:
    def test_filters_below_baseline(self):
        scored = [
            ScoredCandidate("c1", "split", [], CandidateMetrics(0.8, 0, 0, 0), 0.8),
            ScoredCandidate("c2", "break", [], CandidateMetrics(0.3, 0, 0, 0), 0.3),
        ]
        result = reject_degrading_candidates(scored, baseline_score=0.5)
        assert len(result) == 1
        assert result[0].candidate_id == "c1"

    def test_keeps_near_baseline(self):
        scored = [
            ScoredCandidate("c1", "split", [], CandidateMetrics(0.49, 0, 0, 0), 0.49),
        ]
        # 0.49 >= 0.5 * 0.98 = 0.49 → kept
        result = reject_degrading_candidates(scored, baseline_score=0.5)
        assert len(result) == 1

    def test_empty_input(self):
        assert reject_degrading_candidates([], 0.5) == []


class TestAdjustWeightsFromMemory:
    def test_no_history(self):
        w = ObjectiveWeights()
        result = adjust_weights_from_memory(w, [])
        assert result.modularity == w.modularity

    def test_boosts_effective_strategy(self):
        w = ObjectiveWeights()
        history = [
            {"strategy": "cycle_break", "effectiveness": 0.9},
        ]
        result = adjust_weights_from_memory(w, history)
        # cycle_break maps to cycle_reduction, should be boosted
        assert result.cycle_reduction > w.normalize().cycle_reduction

    def test_multiple_strategies(self):
        w = ObjectiveWeights()
        history = [
            {"strategy": "module_split", "effectiveness": 0.8},
            {"strategy": "fan_out_reduction", "effectiveness": 0.7},
        ]
        result = adjust_weights_from_memory(w, history)
        # Both modularity and coupling_reduction should be boosted
        norm = w.normalize()
        assert result.modularity > norm.modularity or result.coupling_reduction > norm.coupling_reduction

    def test_unknown_strategy_ignored(self):
        w = ObjectiveWeights()
        history = [{"strategy": "unknown_strategy", "effectiveness": 1.0}]
        result = adjust_weights_from_memory(w, history)
        norm = w.normalize()
        assert abs(result.modularity - norm.modularity) < 1e-9
