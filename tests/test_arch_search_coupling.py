from __future__ import annotations

from codegraph.arch_search import ArchCandidate, score_candidates


def _candidate(predicted_coupling: float, predicted_score: float = 0.0) -> ArchCandidate:
    candidate = ArchCandidate(candidate_id="c", strategy="split", description="d")
    candidate.simulated = True
    candidate.predicted_coupling = predicted_coupling
    candidate.predicted_score = predicted_score
    return candidate


def _composite(candidate: ArchCandidate, baseline_coupling: float = 0.4) -> float:
    score_candidates(
        [candidate],
        baseline_score=0.5,
        baseline_modularity=0.5,
        baseline_coupling=baseline_coupling,
        baseline_god_modules=0,
        baseline_cycles=0,
    )
    return candidate.composite_score


def test_legacy_predicted_score_field_does_not_affect_ranking():
    # predicted_score used to hold a coupling value and leak into the score.
    assert _composite(_candidate(0.2, predicted_score=0.0)) == _composite(_candidate(0.2, predicted_score=0.99))


def test_coupling_reduction_scores_higher_than_increase():
    lower = _composite(_candidate(0.2))
    higher = _composite(_candidate(0.6))

    assert lower > higher
