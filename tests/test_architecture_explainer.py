"""Tests for codegraph.architecture_explainer."""

from __future__ import annotations

from codegraph.architecture_explainer import (
    explain_architecture_pattern,
    explain_decay_report,
    explain_microservice_candidate,
    explain_refactor_plan,
    generate_explanations,
)


def test_explain_microservice_candidate_has_metrics_and_reasoning():
    candidate = {
        "subsystem_name": "trading_engine",
        "cohesion_score": 0.91,
        "coupling_score": 0.12,
        "api_surface": ["trading/api.py::handle"],
        "confidence": 0.88,
        "metrics": {"cluster_size": 3},
    }
    explanation = explain_microservice_candidate(candidate)
    assert explanation.subject == "trading_engine"
    assert "cohesion" in explanation.metrics
    assert explanation.recommendation_reason


def test_explain_refactor_plan_and_pattern_and_decay():
    plan = {
        "plan_id": "plan-1",
        "problem_type": "cyclic_subsystem",
        "steps": [{"step_number": 1}, {"step_number": 2}],
        "estimated_score_delta": 0.06,
        "confidence": 0.8,
    }
    pattern = {"architecture_type": "layered", "confidence": 0.9, "violations": [1, 2]}
    decay = {
        "god_modules": [{"module": "query.py"}],
        "cyclic_subsystems": [{"modules": ["a", "b"]}],
        "dead_subsystems": [],
        "coupling_index": 0.33,
    }

    plan_exp = explain_refactor_plan(plan)
    pattern_exp = explain_architecture_pattern(pattern)
    decay_exp = explain_decay_report(decay)

    assert plan_exp.analysis
    assert pattern_exp.subject.startswith("pattern:")
    assert decay_exp.metrics["god_modules"] >= 1


def test_generate_explanations_aggregates_outputs():
    explanations = generate_explanations(
        pattern_report={"architecture_type": "layered", "confidence": 0.9, "violations": []},
        decay_report={"god_modules": [], "cyclic_subsystems": [], "dead_subsystems": [], "coupling_index": 0.1},
        microservice_candidates=[
            {
                "subsystem_name": "payments",
                "cohesion_score": 0.85,
                "coupling_score": 0.1,
                "api_surface": ["payments/api.py::handle"],
                "confidence": 0.8,
                "metrics": {"cluster_size": 4},
            }
        ],
        refactor_plans=[
            {
                "plan_id": "plan-x",
                "problem_type": "dependency_inversion",
                "steps": [{"step_number": 1}],
                "estimated_score_delta": 0.03,
                "confidence": 0.7,
            }
        ],
    )
    assert len(explanations) >= 3
    assert all(explanation.subject for explanation in explanations)
