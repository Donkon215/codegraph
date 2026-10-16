from __future__ import annotations

from click.testing import CliRunner

from codegraph import architecture_simulator
from codegraph.arch_schema import SystemArchitecture
from codegraph.cli import architecture as arch_cli
from codegraph.architecture_change import ArchitectureChange, ArchitectureOperation, OpType


class _StubSubsystemResult:
    def to_dict(self):
        return {"subsystem": "auth"}

    def format(self):
        return "stub-subsystem-result"


def test_subsystem_name_form_still_works(monkeypatch, tmp_path):
    monkeypatch.setattr(arch_cli, "find_project_root", lambda: tmp_path)
    monkeypatch.setattr(SystemArchitecture, "load", staticmethod(lambda root: object()))
    monkeypatch.setattr(
        architecture_simulator,
        "simulate_subsystem_addition",
        lambda name, deps, arch: _StubSubsystemResult(),
    )

    result = CliRunner().invoke(arch_cli.arch_simulate_cmd, ["auth"], obj={"verbose": False})

    assert result.exit_code == 0, result.output
    assert "stub-subsystem-result" in result.output


def test_plan_mode_prints_verdict(monkeypatch, tmp_path):
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(
        '[{"change": "add_edge", "node": "a::x", "target": "a::y"}]', encoding="utf-8"
    )
    monkeypatch.setattr(arch_cli, "find_project_root", lambda: tmp_path)
    monkeypatch.setattr(
        architecture_simulator,
        "simulate_changes",
        lambda root, changes: {
            "verdict": "REJECT",
            "reasons": ["adds 1 new cycle(s)"],
            "graph_note": "stub note",
        },
    )

    result = CliRunner().invoke(
        arch_cli.arch_simulate_cmd, ["--plan", str(plan_file)], obj={"verbose": False}
    )

    assert result.exit_code == 0, result.output
    assert "Verdict: REJECT" in result.output
    assert "adds 1 new cycle(s)" in result.output
    assert "Note: stub note" in result.output


def test_positional_plan_json_is_supported_without_breaking_subsystem_name(monkeypatch, tmp_path):
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(
        '[{"change": "add_edge", "node": "a::x", "target": "a::y"}]', encoding="utf-8"
    )
    monkeypatch.setattr(arch_cli, "find_project_root", lambda: tmp_path)
    calls = []
    monkeypatch.setattr(
        architecture_simulator,
        "simulate_changes",
        lambda root, changes: calls.append(changes) or {
            "verdict": "ACCEPT", "reasons": [], "graph_note": "plan graph"
        },
    )

    result = CliRunner().invoke(
        arch_cli.arch_simulate_cmd, [str(plan_file)], obj={"verbose": False}
    )

    assert result.exit_code == 0, result.output
    assert "Verdict: ACCEPT" in result.output
    assert len(calls) == 1


def test_canonical_architecture_change_is_accepted_as_plan(monkeypatch, tmp_path):
    plan_file = tmp_path / "canonical-plan.json"
    plan_file.write_text(ArchitectureChange(operations=[ArchitectureOperation(
        OpType.ADD_EDGE, source="a::one", target="b::two", edge_type="call",
    )]).to_json(), encoding="utf-8")
    monkeypatch.setattr(arch_cli, "find_project_root", lambda: tmp_path)
    calls = []
    monkeypatch.setattr(architecture_simulator, "simulate_changes", lambda root, changes: (
        calls.extend(changes) or {"verdict": "ACCEPT", "reasons": [], "graph_note": "ok"}
    ))

    result = CliRunner().invoke(
        arch_cli.arch_simulate_cmd, ["--plan", str(plan_file), "--json"], obj={"verbose": False}
    )

    assert result.exit_code == 0, result.output
    assert calls == [{"change": "add_edge", "node": "a::one", "target": "b::two"}]


def test_save_prediction_persists_graph_and_blocks_predicted_layer_violation(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from codegraph.architecture_graph import ArchitectureGraph
    from codegraph.architecture_scoring import MultiAxisArchitectureScore

    plan_file = tmp_path / "plan.json"
    plan_file.write_text(
        '[{"change":"add_edge","node":"storage/model.py","target":"api/service.py"}]',
        encoding="utf-8",
    )
    current = ArchitectureGraph(nodes=[
        {"id": "storage/model.py", "file": "storage/model.py"},
        {"id": "api/service.py", "file": "api/service.py"},
    ])
    monkeypatch.setattr(arch_cli, "find_project_root", lambda: tmp_path)
    monkeypatch.setattr(architecture_simulator, "simulate_changes", lambda root, changes: {
        "verdict": "ACCEPT", "reasons": [], "graph_note": "ok",
    })
    monkeypatch.setattr(ArchitectureGraph, "load", classmethod(lambda cls, root: current))
    monkeypatch.setattr("codegraph.architecture_health.compute_architecture_health",
                        lambda graph: SimpleNamespace(to_dict=lambda: {"cycles": 0}))
    monkeypatch.setattr("codegraph.architecture_scoring.compute_architecture_index",
                        lambda root, architecture_graph: MultiAxisArchitectureScore(0.8, "B"))

    result = CliRunner().invoke(
        arch_cli.arch_simulate_cmd,
        ["--plan", str(plan_file), "--save-prediction", "--json"],
        obj={"verbose": False},
    )

    assert result.exit_code == 0, result.output
    payload = __import__("json").loads(result.output)
    assert payload["verdict"] == "REJECT"
    assert payload["predicted_checks"]["layer"]["violations"]
    assert len(payload["predicted_checks"]["new_layer_violations"]) == 1
    assert (tmp_path / ".codegraph" / "predicted_graph.json").is_file()


def test_arch_plan_can_emit_canonical_change_consumable_by_simulate(monkeypatch, tmp_path):
    import json

    from codegraph.arch_planner import ArchPlan, PlannedTask
    from codegraph.arch_schema import SystemArchitecture

    class _Store:
        def __init__(self, root):
            pass

        def load_graph0(self):
            return object()

    class _Index:
        def __init__(self, root):
            pass

        def close(self):
            pass

    output_file = tmp_path / "architecture-change.json"
    plan = ArchPlan(tasks=[PlannedTask(
        task_type="connect_call", source="a::caller", target="b::callee",
    )])
    monkeypatch.setattr(arch_cli, "_resolve_root", lambda ctx: tmp_path)
    monkeypatch.setattr(SystemArchitecture, "load", staticmethod(lambda root: object()))
    monkeypatch.setattr(arch_cli, "GraphStore", _Store)
    monkeypatch.setattr(arch_cli, "IndexService", _Index)
    monkeypatch.setattr("codegraph.arch_planner.plan_architecture", lambda arch, graph, index: plan)

    result = CliRunner().invoke(
        arch_cli.arch_plan_cmd,
        ["--change", "--output", str(output_file)],
        obj={"verbose": False},
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(output_file.read_text(encoding="utf-8"))
    payload_change = __import__("codegraph.architecture_change", fromlist=["ArchitectureChange"]).ArchitectureChange.from_dict(payload)
    payload_change.validate()
    assert arch_cli._canonical_change_simulation_plan(payload) == [
        {"change": "add_edge", "node": "a::caller", "target": "b::callee"},
    ]


def test_compile_human_intent_emits_a_canonical_plan_accepted_by_arch_simulate(monkeypatch, tmp_path):
    import json

    from codegraph.arch_schema import SystemArchitecture
    from codegraph.architecture_compiler import ArchitecturePlan, CompiledChange

    plan_file = tmp_path / "intent-change.json"
    compiled = ArchitecturePlan(
        intent="add billing subsystem",
        changes=[
            CompiledChange("add_subsystem", subsystem="billing"),
            CompiledChange("add_component", subsystem="billing", module_path="billing/api.py"),
            CompiledChange("add_edge", subsystem="billing", target_subsystem="models"),
            CompiledChange("add_constraint", subsystem="models", target_subsystem="billing",
                           constraint_type="forbidden"),
        ],
    )
    monkeypatch.setattr(arch_cli, "find_project_root", lambda: tmp_path)
    monkeypatch.setattr(SystemArchitecture, "load", staticmethod(lambda root: object()))
    monkeypatch.setattr("codegraph.architecture_compiler.compile_intent", lambda intent, arch: compiled)
    result = CliRunner().invoke(
        arch_cli.compile_cmd,
        ["add billing subsystem", "--change", "--output", str(plan_file)],
        obj={"verbose": False},
    )
    assert result.exit_code == 0, result.output

    canonical = json.loads(plan_file.read_text(encoding="utf-8"))
    assert canonical["operations"]
    monkeypatch.setattr(arch_cli, "find_project_root", lambda: tmp_path)
    monkeypatch.setattr(architecture_simulator, "simulate_changes", lambda root, changes: {
        "status": "review", "simulated": False, "function_checks_available": False,
        "verdict": "REVIEW", "reasons": ["empty edge plan"], "graph_note": "components need fuller simulation",
    })
    result = CliRunner().invoke(
        arch_cli.arch_simulate_cmd, ["--plan", str(plan_file), "--json"], obj={"verbose": False}
    )

    assert result.exit_code == 0, result.output
    assert '"canonical_operations"' in result.output
    assert "add_component" in result.output


def test_invalid_canonical_architecture_plan_fails_cleanly(monkeypatch, tmp_path):
    plan_file = tmp_path / "invalid-change.json"
    plan_file.write_text('{"operations":[{"op":"add_edge"}]}', encoding="utf-8")
    monkeypatch.setattr(arch_cli, "find_project_root", lambda: tmp_path)

    result = CliRunner().invoke(
        arch_cli.arch_simulate_cmd, ["--plan", str(plan_file)], obj={"verbose": False}
    )

    assert result.exit_code != 0
    assert "Invalid ArchitectureChange plan" in result.output


def test_partial_simulation_with_safe_proof_is_recorded_as_review(monkeypatch, tmp_path):
    import json

    from codegraph.architecture_proof import PROVEN_SAFE, ArchitectureProof

    plan_file = tmp_path / "review-plan.json"
    plan_file.write_text('[{"change":"add_edge","node":"a","target":"b"}]', encoding="utf-8")
    monkeypatch.setattr(arch_cli, "find_project_root", lambda: tmp_path)
    monkeypatch.setattr(architecture_simulator, "simulate_changes", lambda root, changes: {
        "verdict": "REVIEW", "reasons": ["function checks skipped"], "graph_note": "partial",
    })
    monkeypatch.setattr(
        "codegraph.architecture_proof.generate_proof",
        lambda root, delta: ArchitectureProof(proposal_id="partial-plan", status=PROVEN_SAFE),
    )

    result = CliRunner().invoke(
        arch_cli.arch_simulate_cmd,
        ["--plan", str(plan_file), "--proof", "--json"],
        obj={"verbose": False},
    )

    assert result.exit_code == 0, result.output
    outcome_data = json.loads((tmp_path / ".codegraph" / "memory" / "proposal_outcomes.json").read_text(encoding="utf-8"))
    assert outcome_data["proposals"][0]["outcome"] == "review"
    assert json.loads(result.output)["proposal_feedback"]["accepted"] == 0


def test_plan_mode_refuses_save_and_writes_nothing(monkeypatch, tmp_path):
    plan_file = tmp_path / "plan.json"
    plan_file.write_text('[{"change": "add_edge", "node": "a::x", "target": "a::y"}]', encoding="utf-8")
    monkeypatch.setattr(arch_cli, "find_project_root", lambda: tmp_path)

    result = CliRunner().invoke(
        arch_cli.arch_simulate_cmd, ["--plan", str(plan_file), "--save"], obj={"verbose": False}
    )

    assert result.exit_code != 0
    assert not (tmp_path / ".codegraph").exists()


def test_plan_proof_gate_records_proof_and_can_reject(monkeypatch, tmp_path):
    import json

    from codegraph.architecture_proof import REJECTED, ArchitectureProof

    plan_file = tmp_path / "plan.json"
    plan_file.write_text(
        '[{"change": "add_edge", "node": "a::x", "target": "a::y"}]', encoding="utf-8"
    )
    monkeypatch.setattr(arch_cli, "find_project_root", lambda: tmp_path)
    monkeypatch.setattr(
        architecture_simulator,
        "simulate_changes",
        lambda root, changes: {
            "verdict": "ACCEPT", "reasons": [], "graph_note": "stub note"
        },
    )
    proof = ArchitectureProof(proposal_id="plan-proof", status=REJECTED)
    calls = []
    monkeypatch.setattr(
        "codegraph.architecture_proof.generate_proof",
        lambda root, delta: calls.append(delta) or proof,
    )

    result = CliRunner().invoke(
        arch_cli.arch_simulate_cmd,
        [str(plan_file), "--proof", "--json"],
        obj={"verbose": False},
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["verdict"] == "REJECT"
    assert payload["proof"]["status"] == REJECTED
    assert calls[0]["added_edges"] == [{"source": "a::x", "target": "a::y"}]
    assert (tmp_path / ".codegraph" / "proofs" / "plan-proof.json").exists()
    memory = json.loads(
        (tmp_path / ".codegraph" / "memory" / "proposal_outcomes.json").read_text(encoding="utf-8")
    )
    assert memory["proposals"][0]["outcome"] == "rejected"
    assert payload["proposal_feedback"]["rejected"] == 1
