from __future__ import annotations

from click.testing import CliRunner

from codegraph import architecture_simulator
from codegraph.arch_schema import SystemArchitecture
from codegraph.cli import architecture as arch_cli


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


def test_plan_mode_refuses_save_and_writes_nothing(monkeypatch, tmp_path):
    plan_file = tmp_path / "plan.json"
    plan_file.write_text('[{"change": "add_edge", "node": "a::x", "target": "a::y"}]', encoding="utf-8")
    monkeypatch.setattr(arch_cli, "find_project_root", lambda: tmp_path)

    result = CliRunner().invoke(
        arch_cli.arch_simulate_cmd, ["--plan", str(plan_file), "--save"], obj={"verbose": False}
    )

    assert result.exit_code != 0
    assert not (tmp_path / ".codegraph").exists()
