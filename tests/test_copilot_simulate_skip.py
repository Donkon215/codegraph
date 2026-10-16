"""The copilot must not invent function-level node ids.

_try_simulate used to pass f"{target}::*" for any target without "::". That id can never
resolve in the index, so such plans were answered with a verdict built on a fake node.
"""

from __future__ import annotations

from types import SimpleNamespace

from codegraph.copilot_intelligence import _try_simulate


def _decision(target_evidence: str = "") -> SimpleNamespace:
    evidence = [f"Callee: {target_evidence}"] if target_evidence else []
    return SimpleNamespace(action="safe_to_edit", evidence=evidence, target="")


def test_target_without_separator_is_not_simulated(monkeypatch, tmp_path):
    calls = []

    def _record(*args, **kwargs):
        calls.append((args, kwargs))
        return {"status": "simulated", "score_delta": 0.0}

    monkeypatch.setattr("codegraph.architecture_simulator.simulate_change", _record)

    result = _try_simulate(tmp_path, "payments", _decision())

    assert calls == []  # the simulator was never called, so no fake node was built
    assert result["status"] == "not_simulated"
    assert "payments" in result["reason"]
    assert "score_delta" not in result  # a skipped run must not carry a delta of 0


def test_real_function_id_is_simulated_with_that_id(monkeypatch, tmp_path):
    calls = []

    def _record(project_root, node, change, target):
        calls.append({"node": node, "change": change, "target": target})
        return {"status": "simulated", "score_delta": 0.0, "predicted_subsystem_score": 0.5}

    monkeypatch.setattr("codegraph.architecture_simulator.simulate_change", _record)

    result = _try_simulate(tmp_path, "src/foo.py::foo", _decision("src/bar.py::bar"))

    assert calls == [{"node": "src/foo.py::foo", "change": "add_edge", "target": "src/bar.py::bar"}]
    assert result["status"] == "simulated"


def test_copilot_loop_skipped_simulation_is_a_warning_not_a_drop(tmp_path, monkeypatch):
    # End to end through copilot_loop, not just _try_simulate.
    from codegraph.copilot_intelligence import copilot_loop
    from tests.test_copilot_intelligence import _setup_minimal_graph

    root = _setup_minimal_graph(tmp_path)
    calls = []
    monkeypatch.setattr(
        "codegraph.architecture_simulator.simulate_change",
        lambda *args, **kwargs: calls.append(kwargs) or {},
    )

    report = copilot_loop(root, "svc/order.py", simulate=True)

    sim_iterations = [it for it in report.iterations if it.step == "simulate"]
    assert len(sim_iterations) == 1
    assert sim_iterations[0].status == "skipped"                   # never ran: not ok, not a failure
    assert report.verdict != "proceed"                              # a skip cannot support proceed
    assert sim_iterations[0].result["status"] == "not_simulated"
    assert calls == []                                              # no fabricated node id
    assert report.score_after == report.score_before                # no whole-score drop
    assert "Simulation skipped" in report.simulation["note"]        # the skip is recorded
    assert not any("did not run" in step for step in report.next_steps)  # reason stays in the note


def _loop(tmp_path, monkeypatch, sim_return, simulate):
    from codegraph.copilot_intelligence import copilot_loop
    from tests.test_copilot_intelligence import _setup_minimal_graph

    root = _setup_minimal_graph(tmp_path)
    if sim_return is not None:
        monkeypatch.setattr(
            "codegraph.architecture_simulator.simulate_change",
            lambda *args, **kwargs: dict(sim_return),
        )
    return copilot_loop(root, "svc/order.py::OrderService", simulate=simulate)


def test_predicted_drop_blocks_the_verdict(tmp_path, monkeypatch):
    report = _loop(tmp_path, monkeypatch, {
        "status": "simulated",
        "score_delta": -0.2,
        "predicted_subsystem_score": 0.1,
        "baseline_subsystem_score": 0.3,
    }, simulate=True)

    step = next(it for it in report.iterations if it.step == "simulate")
    assert step.status == "warning"
    assert report.verdict == "block"


def test_clean_simulation_leaves_verdict_unchanged(tmp_path, monkeypatch):
    without_sim = _loop(tmp_path / "base", monkeypatch, None, simulate=False)
    with_sim = _loop(tmp_path / "sim", monkeypatch, {
        "status": "simulated",
        "score_delta": 0.0,
        "predicted_subsystem_score": 0.3,
        "baseline_subsystem_score": 0.3,
    }, simulate=True)

    step = next(it for it in with_sim.iterations if it.step == "simulate")
    assert step.status == "ok"
    assert with_sim.verdict == without_sim.verdict


def test_skipped_simulation_caps_proceed_at_caution(tmp_path, monkeypatch):
    without_sim = _loop(tmp_path / "base", monkeypatch, None, simulate=False)
    skipped = _loop(tmp_path / "skip", monkeypatch, {
        "status": "not_simulated",
        "reason": "no function-level node id",
    }, simulate=True)

    step = next(it for it in skipped.iterations if it.step == "simulate")
    assert step.status == "skipped"
    assert without_sim.verdict == "proceed"  # premise: this fixture is the case being tested
    assert skipped.verdict == "caution"
