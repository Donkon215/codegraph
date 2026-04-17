"""Tests for codegraph.copilot_intelligence module.

Tests cover: ScenarioReport, Decision, CopilotLoopReport,
and the builder functions scenario_context(), decide(), copilot_loop().
"""

from __future__ import annotations

import json

from codegraph.copilot_intelligence import (
    ComponentScenario,
    CopilotLoopReport,
    Decision,
    DecisionAlternative,
    ScenarioReport,
    SystemScenario,
    copilot_loop,
    decide,
    scenario_context,
)


def _setup_minimal_graph(tmp_path):
    """Create a minimal .codegraph tree for testing."""
    arch_dir = tmp_path / ".codegraph" / "architecture"
    graph_dir = tmp_path / ".codegraph" / "graphs"
    workflow_dir = tmp_path / ".codegraph" / "workflow"
    analysis_dir = tmp_path / ".codegraph" / "analysis"
    proofs_dir = tmp_path / ".codegraph" / "proofs"

    for d in (arch_dir, graph_dir, workflow_dir, analysis_dir, proofs_dir):
        d.mkdir(parents=True, exist_ok=True)

    graph_dir.joinpath("graph0.json").write_text(
        json.dumps({
            "graph_version": 2,
            "nodes": [
                {"id": "svc/order.py::OrderService", "body_hash": "x",
                 "file": "svc/order.py", "type": "class", "line": 1},
                {"id": "svc/order.py::OrderService::create", "body_hash": "y",
                 "file": "svc/order.py", "type": "function", "line": 10},
                {"id": "svc/payment.py::PaymentService", "body_hash": "z",
                 "file": "svc/payment.py", "type": "class", "line": 1},
                {"id": "svc/payment.py::PaymentService::charge", "body_hash": "w",
                 "file": "svc/payment.py", "type": "function", "line": 5},
            ],
        }),
        encoding="utf-8",
    )
    graph_dir.joinpath("graph1.json").write_text(
        json.dumps({
            "nodes": [
                {"id": "svc/order.py::OrderService", "intent": "service",
                 "layer": 3, "arch_layer": "service", "intent_body_hash": "y"},
            ]
        }),
        encoding="utf-8",
    )
    workflow_dir.joinpath("workflow.json").write_text(
        json.dumps({
            "edges": [
                {"source": "svc/order.py::OrderService::create",
                 "target": "svc/payment.py::PaymentService::charge",
                 "edge_type": "call"},
            ]
        }),
        encoding="utf-8",
    )
    arch_dir.joinpath("system.json").write_text(
        json.dumps({
            "subsystems": [
                {"name": "orders", "modules": ["svc/order.py"]},
                {"name": "payments", "modules": ["svc/payment.py"]},
            ],
            "edges": [
                {"source": "orders", "target": "payments"},
            ],
            "constraints": [
                {"source": "payments", "target": "orders",
                 "type": "forbidden_dependency", "reason": "no circular dep"},
            ],
        }),
        encoding="utf-8",
    )
    analysis_dir.joinpath("violations.json").write_text(
        json.dumps({
            "violations": [
                {"node": "svc/payment.py::PaymentService::charge",
                 "type": "layer_violation", "message": "crosses boundary"},
            ]
        }),
        encoding="utf-8",
    )
    proofs_dir.joinpath("latest_proof.json").write_text(
        json.dumps({"status": "PROVEN_SAFE"}), encoding="utf-8",
    )
    arch_dir.joinpath("architecture_patterns.json").write_text(
        json.dumps({
            "primary_pattern": "layered",
            "patterns": [{"architecture_type": "layered",
                          "confidence": 0.8, "consistency": 0.9}],
        }),
        encoding="utf-8",
    )
    arch_dir.joinpath("architecture_advice.json").write_text(
        json.dumps({
            "score": 0.72,
            "grade": "C",
            "smells": [
                {"entity": "svc/order.py::OrderService",
                 "smell_type": "god_class",
                 "severity": "medium",
                 "description": "Too many responsibilities"},
            ],
        }),
        encoding="utf-8",
    )
    return tmp_path


# ── ComponentScenario/SystemScenario dataclass tests ─────────────────


class TestComponentScenario:
    def test_to_dict(self):
        s = ComponentScenario(
            component_id="svc/order.py",
            scenario_id="order_S1",
            description="Reduce fan-out",
            change_type="split",
            risk="medium",
        )
        d = s.to_dict()
        assert d["component_id"] == "svc/order.py"
        assert d["scenario_id"] == "order_S1"
        assert d["risk"] == "medium"


class TestSystemScenario:
    def test_to_dict(self):
        cs = ComponentScenario(
            component_id="svc/order.py",
            scenario_id="order_S1",
            description="test",
            change_type="split",
        )
        ss = SystemScenario(
            scenario_id="SYS-001",
            components=[cs],
            interaction_risk="medium",
            failure_propagation=["svc/order.py → svc/payment.py"],
        )
        d = ss.to_dict()
        assert d["scenario_id"] == "SYS-001"
        assert len(d["components"]) == 1
        assert d["interaction_risk"] == "medium"


# ── ScenarioReport tests ─────────────────────────────────────────────


class TestScenarioReport:
    def test_empty_report(self):
        r = ScenarioReport()
        d = r.to_dict()
        assert d["total_combinations"] == 0
        assert d["coverage_score"] == 0.0

    def test_format_returns_string(self):
        r = ScenarioReport()
        text = r.format()
        assert "Scenario Explosion Report" in text

    def test_scenario_context_with_graph(self, tmp_path):
        root = _setup_minimal_graph(tmp_path)
        report = scenario_context(root)
        d = report.to_dict()
        assert "component_scenarios" in d
        assert "system_scenarios" in d
        assert "next_steps" in d

    def test_scenario_context_with_targets(self, tmp_path):
        root = _setup_minimal_graph(tmp_path)
        report = scenario_context(
            root, target_components=["svc/order.py", "svc/payment.py"]
        )
        # At least baseline (S0) scenarios per component
        for comp_id, scenarios in report.component_scenarios.items():
            assert len(scenarios) >= 1
            assert any(s.change_type == "none" for s in scenarios)

    def test_scenario_context_empty_project(self, tmp_path):
        """No .codegraph at all — should return empty report gracefully."""
        report = scenario_context(tmp_path)
        assert report.total_combinations == 0

    def test_scenario_context_single_component(self, tmp_path):
        root = _setup_minimal_graph(tmp_path)
        report = scenario_context(root, target_components=["svc/order.py"])
        # Single component: system scenarios = component scenarios
        assert report.total_combinations == report.sampled_combinations

    def test_scenario_cross_product(self, tmp_path):
        root = _setup_minimal_graph(tmp_path)
        report = scenario_context(
            root, target_components=["svc/order.py", "svc/payment.py"]
        )
        if len(report.component_scenarios) >= 2:
            # Cross-product should produce at least some system scenarios
            expected_total = 1
            for scenarios in report.component_scenarios.values():
                expected_total *= len(scenarios)
            assert report.total_combinations == expected_total


# ── Decision tests ────────────────────────────────────────────────────


class TestDecision:
    def test_to_dict(self):
        d = Decision(
            decision_id="DEC-test",
            target="svc/order.py",
            action="fix_violations",
            reason="2 violations",
            confidence=0.85,
            risk="medium",
        )
        out = d.to_dict()
        assert out["decision_id"] == "DEC-test"
        assert out["confidence"] == 0.85

    def test_format_string(self):
        d = Decision(
            decision_id="DEC-test",
            target="svc/order.py",
            action="fix_violations",
            reason="2 violations",
        )
        text = d.format()
        assert "DEC-test" in text
        assert "fix_violations" in text

    def test_save_creates_file(self, tmp_path):
        d = Decision(decision_id="DEC-001", target="x", action="test")
        path = d.save(tmp_path)
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["decision_id"] == "DEC-001"

    def test_decide_with_violations(self, tmp_path):
        root = _setup_minimal_graph(tmp_path)
        d = decide(root, "svc/payment.py::PaymentService::charge")
        assert d.action == "fix_violations"
        assert d.risk in ("medium", "high")
        assert d.confidence > 0

    def test_decide_safe_target(self, tmp_path):
        root = _setup_minimal_graph(tmp_path)
        d = decide(root, "svc/order.py::OrderService")
        # Should still produce a valid decision
        assert d.decision_id.startswith("DEC-")
        assert d.next_steps

    def test_decide_includes_alternatives(self, tmp_path):
        root = _setup_minimal_graph(tmp_path)
        d = decide(root, "svc/payment.py::PaymentService::charge")
        assert len(d.alternatives) >= 1
        for alt in d.alternatives:
            assert alt.action
            assert alt.reason_rejected

    def test_decide_includes_postconditions(self, tmp_path):
        root = _setup_minimal_graph(tmp_path)
        d = decide(root, "svc/payment.py")
        assert any("codegraph build" in pc for pc in d.postconditions)

    def test_decide_nonexistent_target(self, tmp_path):
        root = _setup_minimal_graph(tmp_path)
        d = decide(root, "nonexistent/module.py")
        # Should still produce a decision (safe_to_edit fallback)
        assert d.decision_id


# ── CopilotLoopReport tests ──────────────────────────────────────────


class TestCopilotLoopReport:
    def test_to_dict(self):
        r = CopilotLoopReport(target="test", verdict="proceed")
        d = r.to_dict()
        assert d["target"] == "test"
        assert d["verdict"] == "proceed"
        assert "next_steps" in d

    def test_format_string(self):
        r = CopilotLoopReport(target="test", verdict="proceed")
        text = r.format()
        assert "proceed" in text

    def test_copilot_loop_full(self, tmp_path):
        root = _setup_minimal_graph(tmp_path)
        report = copilot_loop(root, "svc/payment.py::PaymentService::charge")
        assert report.verdict in ("proceed", "caution", "block")
        assert report.decision is not None
        assert len(report.iterations) >= 3  # hotspots + focus + decide
        assert report.next_steps

    def test_copilot_loop_safe_target(self, tmp_path):
        root = _setup_minimal_graph(tmp_path)
        report = copilot_loop(root, "svc/order.py::OrderService")
        assert report.verdict in ("proceed", "caution")

    def test_copilot_loop_with_simulate(self, tmp_path):
        root = _setup_minimal_graph(tmp_path)
        report = copilot_loop(
            root, "svc/order.py::OrderService", simulate=True
        )
        assert len(report.iterations) >= 4  # hotspots + focus + decide + simulate

    def test_copilot_loop_with_save(self, tmp_path):
        root = _setup_minimal_graph(tmp_path)
        report = copilot_loop(root, "svc/order.py", save=True)
        decisions_dir = root / ".codegraph" / "decisions"
        assert decisions_dir.exists()
        assert len(list(decisions_dir.glob("DEC-*.json"))) == 1

    def test_copilot_loop_nonexistent_target(self, tmp_path):
        root = _setup_minimal_graph(tmp_path)
        report = copilot_loop(root, "nonexistent/module.py")
        # Should complete without crashing; focus finds no nodes
        assert report.verdict in ("proceed", "caution", "block")

    def test_copilot_loop_to_dict_has_iterations(self, tmp_path):
        root = _setup_minimal_graph(tmp_path)
        report = copilot_loop(root, "svc/order.py")
        d = report.to_dict()
        assert len(d["iterations"]) >= 3
        assert all("step" in it for it in d["iterations"])
        assert all("status" in it for it in d["iterations"])


# ── suggested_next_steps integration tests ────────────────────────────


class TestSuggestedNextSteps:
    def test_focus_to_dict_has_next_steps(self, tmp_path):
        from codegraph.copilot_context_builder import focus_context

        root = _setup_minimal_graph(tmp_path)
        ctx = focus_context(root, "svc/payment.py::PaymentService::charge")
        d = ctx.to_dict()
        assert "suggested_next_steps" in d
        assert len(d["suggested_next_steps"]) >= 1

    def test_hotspot_to_dict_has_next_steps(self, tmp_path):
        from codegraph.copilot_context_builder import hotspot_context

        root = _setup_minimal_graph(tmp_path)
        report = hotspot_context(root)
        d = report.to_dict()
        assert "suggested_next_steps" in d

    def test_scope_to_dict_has_next_steps(self, tmp_path):
        from codegraph.copilot_context_builder import scope_context

        root = _setup_minimal_graph(tmp_path)
        ctx = scope_context(root, "orders")
        d = ctx.to_dict()
        assert "suggested_next_steps" in d

    def test_focus_next_steps_for_violations(self, tmp_path):
        from codegraph.copilot_context_builder import focus_context

        root = _setup_minimal_graph(tmp_path)
        ctx = focus_context(root, "svc/payment.py::PaymentService::charge")
        d = ctx.to_dict()
        # When violations exist, should suggest decide command
        steps = d["suggested_next_steps"]
        assert any("decide" in s or "build" in s for s in steps)

    def test_scenario_report_has_next_steps(self, tmp_path):
        root = _setup_minimal_graph(tmp_path)
        report = scenario_context(root,
                                  target_components=["svc/order.py"])
        d = report.to_dict()
        assert "next_steps" in d

    def test_decision_has_next_steps(self, tmp_path):
        root = _setup_minimal_graph(tmp_path)
        d = decide(root, "svc/order.py")
        assert len(d.next_steps) >= 1


# ── Round 3: Scenario Pruning/Ranking ────────────────────────────────


class TestScenarioPruning:
    def test_rank_and_prune_reduces(self, tmp_path):
        from codegraph.copilot_intelligence import _rank_and_prune_scenarios

        cs = ComponentScenario(
            component_id="x", scenario_id="x_S0",
            description="baseline", change_type="none", risk="low",
        )
        scenarios = [
            SystemScenario(scenario_id=f"SYS-{i}", components=[cs],
                           interaction_risk="low",
                           failure_propagation=[])
            for i in range(50)
        ]
        pruned = _rank_and_prune_scenarios(scenarios, max_keep=10)
        assert len(pruned) <= 10

    def test_rank_prefers_high_risk(self, tmp_path):
        from codegraph.copilot_intelligence import _rank_and_prune_scenarios

        lo = ComponentScenario(
            component_id="a", scenario_id="a_S0",
            description="safe", change_type="none", risk="low",
        )
        hi = ComponentScenario(
            component_id="b", scenario_id="b_S1",
            description="risky split", change_type="split", risk="high",
        )
        ss_low = SystemScenario(scenario_id="SYS-lo", components=[lo],
                                interaction_risk="low",
                                failure_propagation=[])
        ss_high = SystemScenario(scenario_id="SYS-hi", components=[hi],
                                 interaction_risk="high",
                                 failure_propagation=["a → b"])
        pruned = _rank_and_prune_scenarios([ss_low, ss_high], max_keep=1)
        assert len(pruned) == 1
        assert pruned[0].scenario_id == "SYS-hi"

    def test_scenario_context_applies_pruning(self, tmp_path):
        root = _setup_minimal_graph(tmp_path)
        report = scenario_context(
            root,
            target_components=["svc/order.py", "svc/payment.py"],
            max_combinations=5,
        )
        assert len(report.system_scenarios) <= 5


# ── Round 3: Memory-Influenced Decisions ─────────────────────────────


class TestMemoryIntegration:
    def test_load_memory_patterns_no_file(self, tmp_path):
        from codegraph.copilot_intelligence import _load_memory_patterns
        # No agent_memory.json → returns empty list
        patterns = _load_memory_patterns(tmp_path)
        assert patterns == []

    def test_load_memory_patterns_with_data(self, tmp_path):
        from codegraph.copilot_intelligence import _load_memory_patterns
        mem_dir = tmp_path / ".codegraph"
        mem_dir.mkdir(parents=True, exist_ok=True)
        mem_dir.joinpath("agent_memory.json").write_text(json.dumps({
            "patterns": [
                {"pattern_id": "p1", "task_type": "policy_violation",
                 "action_taken": "fix", "node_pattern": "*",
                 "success_count": 5, "last_used": "2025-01-01"},
            ],
            "conventions": [],
            "stats": {"total_repairs": 10, "successful_repairs": 8,
                      "failed_repairs": 2, "last_run": "2025-01-01"},
            "notes": [],
        }), encoding="utf-8")
        patterns = _load_memory_patterns(tmp_path)
        assert len(patterns) == 1
        assert patterns[0]["task_type"] == "policy_violation"

    def test_confidence_adjustment_boost(self):
        from codegraph.copilot_intelligence import _memory_confidence_adjustment
        patterns = [
            {"task_type": "policy_violation", "success_count": 12},
        ]
        adj = _memory_confidence_adjustment(patterns, "fix_violations")
        assert adj > 0  # Should boost

    def test_confidence_adjustment_penalize(self):
        from codegraph.copilot_intelligence import _memory_confidence_adjustment
        patterns = [
            {"task_type": "policy_violation", "success_count": 0},
        ]
        adj = _memory_confidence_adjustment(patterns, "fix_violations")
        assert adj < 0  # Should penalize

    def test_confidence_adjustment_no_match(self):
        from codegraph.copilot_intelligence import _memory_confidence_adjustment
        patterns = [
            {"task_type": "orphan", "success_count": 5},
        ]
        # "fix_violations" maps to "policy_violation", no orphan match
        adj = _memory_confidence_adjustment(patterns, "fix_violations")
        assert adj == 0.0

    def test_confidence_adjustment_empty(self):
        from codegraph.copilot_intelligence import _memory_confidence_adjustment
        assert _memory_confidence_adjustment([], "fix_violations") == 0.0


# ── Round 3: Query Engine Integration ────────────────────────────────


class TestQueryEnrichment:
    def test_query_enrich_no_index(self, tmp_path):
        from codegraph.copilot_intelligence import _query_enrich
        from codegraph.copilot_context_builder import FocusContext
        root = _setup_minimal_graph(tmp_path)
        # No index store — should return empty insights gracefully
        focus = FocusContext(target="svc/order.py", nodes=[], edges=[])
        insights = _query_enrich(root, "svc/order.py", focus)
        assert isinstance(insights, dict)


# ── Round 3: Deep Simulation ─────────────────────────────────────────


class TestDeepSimulation:
    def test_deep_simulate_returns_structure(self, tmp_path):
        from codegraph.copilot_intelligence import _deep_simulate
        from codegraph.copilot_context_builder import FocusContext
        root = _setup_minimal_graph(tmp_path)
        focus = FocusContext(
            target="svc/order.py",
            nodes=[{"id": "svc/order.py::OrderService"}],
            edges=[],
        )
        result = _deep_simulate(root, "svc/order.py", focus)
        assert "data_flow_edges_affected" in result
        assert "failure_chains" in result
        assert "state_transitions" in result
        assert "side_effects" in result

    def test_deep_simulate_with_data_flow(self, tmp_path):
        from codegraph.copilot_intelligence import _deep_simulate
        from codegraph.copilot_context_builder import FocusContext
        root = _setup_minimal_graph(tmp_path)
        # Add data_flow edges to workflow
        wf_path = root / ".codegraph" / "workflow" / "workflow.json"
        wf = json.loads(wf_path.read_text(encoding="utf-8"))
        wf["edges"].append({
            "source": "svc/order.py::OrderService::create",
            "target": "svc/payment.py::PaymentService::charge",
            "edge_type": "data_flow",
        })
        wf["edges"].append({
            "source": "svc/order.py::OrderService::create",
            "target": "svc/payment.py::PaymentService::charge",
            "edge_type": "side_effect",
        })
        wf_path.write_text(json.dumps(wf), encoding="utf-8")

        focus = FocusContext(
            target="svc/order.py",
            nodes=[{"id": "svc/order.py::OrderService::create"}],
            edges=[],
        )
        result = _deep_simulate(root, "svc/order.py", focus)
        assert result["data_flow_edges_affected"] >= 1
        assert len(result["side_effects"]) >= 1

    def test_deep_simulate_empty_project(self, tmp_path):
        from codegraph.copilot_intelligence import _deep_simulate
        from codegraph.copilot_context_builder import FocusContext
        focus = FocusContext(target="x", nodes=[], edges=[])
        result = _deep_simulate(tmp_path, "x", focus)
        assert result["data_flow_edges_affected"] == 0
        assert result["failure_chains"] == []


# ── Round 3: Confidence Calibration ──────────────────────────────────


class TestConfidenceCalibration:
    def test_record_prediction_creates_file(self, tmp_path):
        from codegraph.copilot_intelligence import _record_prediction
        _record_prediction(
            tmp_path,
            decision_id="DEC-test",
            predicted_action="fix_violations",
            predicted_risk="medium",
            predicted_confidence=0.8,
            predicted_score_delta=0.02,
        )
        cal_path = tmp_path / ".codegraph" / "calibration" / "confidence_calibration.json"
        assert cal_path.exists()
        records = json.loads(cal_path.read_text(encoding="utf-8"))
        assert len(records) == 1
        assert records[0]["decision_id"] == "DEC-test"
        assert records[0]["outcome"] == "pending"

    def test_record_prediction_appends(self, tmp_path):
        from codegraph.copilot_intelligence import _record_prediction
        for i in range(3):
            _record_prediction(
                tmp_path,
                decision_id=f"DEC-{i}",
                predicted_action="fix",
                predicted_risk="low",
                predicted_confidence=0.9,
                predicted_score_delta=0.01,
            )
        cal_path = tmp_path / ".codegraph" / "calibration" / "confidence_calibration.json"
        records = json.loads(cal_path.read_text(encoding="utf-8"))
        assert len(records) == 3

    def test_resolve_prediction(self, tmp_path):
        from codegraph.copilot_intelligence import (
            _record_prediction, resolve_prediction,
        )
        _record_prediction(
            tmp_path,
            decision_id="DEC-resolve",
            predicted_action="fix_violations",
            predicted_risk="medium",
            predicted_confidence=0.8,
            predicted_score_delta=0.02,
        )
        found = resolve_prediction(
            tmp_path, "DEC-resolve",
            actual_score_delta=0.03,
            outcome="success",
        )
        assert found is True
        cal_path = tmp_path / ".codegraph" / "calibration" / "confidence_calibration.json"
        records = json.loads(cal_path.read_text(encoding="utf-8"))
        assert records[0]["outcome"] == "success"
        assert records[0]["actual_score_delta"] == 0.03

    def test_resolve_prediction_not_found(self, tmp_path):
        from codegraph.copilot_intelligence import resolve_prediction
        found = resolve_prediction(
            tmp_path, "DEC-missing",
            actual_score_delta=0.0,
            outcome="failure",
        )
        assert found is False

    def test_calibrate_confidence_no_data(self, tmp_path):
        from codegraph.copilot_intelligence import calibrate_confidence
        result = calibrate_confidence(tmp_path)
        assert result["status"] == "no_data"

    def test_calibrate_confidence_all_pending(self, tmp_path):
        from codegraph.copilot_intelligence import (
            _record_prediction, calibrate_confidence,
        )
        _record_prediction(
            tmp_path,
            decision_id="DEC-p1",
            predicted_action="fix",
            predicted_risk="low",
            predicted_confidence=0.9,
            predicted_score_delta=0.01,
        )
        result = calibrate_confidence(tmp_path)
        assert result["status"] == "all_pending"

    def test_calibrate_confidence_with_resolved(self, tmp_path):
        from codegraph.copilot_intelligence import (
            _record_prediction, resolve_prediction, calibrate_confidence,
        )
        _record_prediction(
            tmp_path,
            decision_id="DEC-c1",
            predicted_action="fix_violations",
            predicted_risk="medium",
            predicted_confidence=0.85,
            predicted_score_delta=0.02,
        )
        resolve_prediction(
            tmp_path, "DEC-c1",
            actual_score_delta=0.025,
            outcome="success",
        )
        result = calibrate_confidence(tmp_path)
        assert result["status"] == "calibrated"
        assert result["accuracy"] == 1.0
        assert result["mean_absolute_error"] is not None

    def test_copilot_loop_save_records_prediction(self, tmp_path):
        root = _setup_minimal_graph(tmp_path)
        report = copilot_loop(root, "svc/order.py", save=True)
        cal_path = root / ".codegraph" / "calibration" / "confidence_calibration.json"
        assert cal_path.exists()
        records = json.loads(cal_path.read_text(encoding="utf-8"))
        assert len(records) >= 1
        assert records[0]["outcome"] == "pending"
