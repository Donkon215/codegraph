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
    assert sim_iterations[0].status == "warning"                    # not "ok"
    assert sim_iterations[0].result["status"] == "not_simulated"
    assert calls == []                                              # no fabricated node id
    assert report.score_after == report.score_before                # no whole-score drop
    assert "Simulation skipped" in report.simulation["note"]        # the skip is recorded
    assert not any("Simulation" in step for step in report.next_steps)  # not an action item
