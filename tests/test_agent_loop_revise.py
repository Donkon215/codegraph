"""Issue #37 — rejected plans are revised using simulation feedback.

Unit tests drive the attribution logic with a stubbed gate; the end-to-end
test runs the real loop on a throwaway project:
plan -> simulate (REJECT) -> revise -> simulate (gate passes) -> save
prediction -> implement -> rebuild -> reconcile predicted vs actual.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from codegraph.architecture_simulator import revise_rejected_changes

CODEGRAPH = Path(__file__).resolve().parents[1]

APP_A = "app/a.py::fa"
APP_B = "app/b.py::fb"
APP_C = "app/c.py::fc"


# ── attribution logic ──────────────────────────────────────────────────


def _stub(monkeypatch, verdicts_by_change):
    """Fake gate: REJECT only for the changes named in the mapping."""
    import codegraph.architecture_simulator as sim

    def fake(project_root, changes):
        rejected = [
            change for change in changes
            if verdicts_by_change.get(change["node"]) == "REJECT"
        ]
        verdict = "REJECT" if rejected else "REVIEW"
        reasons = [f"{c['node']} rejected" for c in rejected]
        return {"verdict": verdict, "reasons": reasons or ["score unchanged"]}

    monkeypatch.setattr(sim, "simulate_changes", fake)


def test_no_rejection_leaves_plan_untouched(monkeypatch) -> None:
    _stub(monkeypatch, {})
    changes = [{"change": "add_edge", "node": APP_C, "target": APP_A}]

    remaining, dropped, result = revise_rejected_changes(None, changes)

    assert remaining == changes
    assert dropped == []
    assert result["verdict"] == "REVIEW"
    assert "unattributed_reject" not in result


def test_single_offender_is_dropped_with_its_reasons(monkeypatch) -> None:
    _stub(monkeypatch, {APP_B: "REJECT"})
    changes = [
        {"change": "add_edge", "node": APP_C, "target": APP_A},
        {"change": "add_edge", "node": APP_B, "target": APP_A},
    ]

    remaining, dropped, result = revise_rejected_changes(None, changes)

    assert [c["node"] for c in remaining] == [APP_C]
    assert len(dropped) == 1
    assert dropped[0]["change"]["node"] == APP_B
    assert dropped[0]["reasons"] == [f"{APP_B} rejected"]
    assert result["verdict"] == "REVIEW"


def test_combination_reject_is_not_guessed(monkeypatch) -> None:
    """No single change is rejected, so nothing is cut and the caller is told."""
    import codegraph.architecture_simulator as sim

    def fake(project_root, changes):
        return {
            "verdict": "REJECT" if len(changes) > 1 else "REVIEW",
            "reasons": ["adds 1 new cycle(s)"],
        }

    monkeypatch.setattr(sim, "simulate_changes", fake)
    changes = [
        {"change": "add_edge", "node": APP_B, "target": APP_C},
        {"change": "add_edge", "node": APP_C, "target": APP_B},
    ]

    remaining, dropped, result = revise_rejected_changes(None, changes)

    assert remaining == changes
    assert dropped == []
    assert result["unattributed_reject"] is True


def test_dropping_every_change_terminates(monkeypatch) -> None:
    _stub(monkeypatch, {APP_B: "REJECT", APP_C: "REJECT"})
    changes = [
        {"change": "add_edge", "node": APP_B, "target": APP_A},
        {"change": "add_edge", "node": APP_C, "target": APP_A},
    ]

    remaining, dropped, result = revise_rejected_changes(None, changes)

    assert remaining == []
    assert len(dropped) == 2
    # An empty plan is REVIEW, never ACCEPT — revision must not invent success.
    assert result["verdict"] == "REVIEW"


# ── end to end ─────────────────────────────────────────────────────────


def _env() -> dict:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(CODEGRAPH)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _cg(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        [sys.executable, "-m", "codegraph", *args], cwd=cwd, capture_output=True,
        text=True, encoding="utf-8", errors="replace", env=_env(), timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def test_agent_loop_revises_rejected_plan_then_verifies_prediction() -> None:
    from codegraph.architecture_reconcile import reconcile_project
    from codegraph.architecture_simulator import simulate_changes

    with tempfile.TemporaryDirectory(prefix=".test_agent_loop_", dir=CODEGRAPH) as folder:
        repo = Path(folder)
        (repo / "app").mkdir()
        (repo / "pyproject.toml").write_text(
            "[project]\nname='loop-fixture'\n", encoding="utf-8",
        )
        (repo / "app" / "a.py").write_text("def fa():\n    return 1\n", encoding="utf-8")
        (repo / "app" / "b.py").write_text(
            "from app.a import fa\n\n\ndef fb():\n    return fa()\n", encoding="utf-8",
        )
        (repo / "app" / "c.py").write_text("def fc():\n    return 2\n", encoding="utf-8")
        _cg(repo, "build")

        # fb -> fa reverses the existing fa <- fb edge, so the gate rejects it.
        plan = [
            {"change": "add_edge", "node": APP_B, "target": APP_A},
            {"change": "add_edge", "node": APP_C, "target": APP_A},
        ]
        rejected = simulate_changes(repo, plan)
        assert rejected["verdict"] == "REJECT", rejected["reasons"]
        plan_path = repo / "plan.json"
        plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")

        # The real command consumes the rejection, runs the proof gate for the
        # revised plan, and returns the plan handed to the implementation worker.
        output = json.loads(_cg(
            repo, "arch-simulate", "--plan", str(plan_path), "--revise-rejected",
            "--save-prediction", "--proof", "--json",
        ))
        assert output["revision"]["original_verdict"] == "REJECT"
        assert [entry["change"]["node"] for entry in output["revision"]["dropped_changes"]] == [APP_B]
        assert output["revision"]["dropped_changes"][0]["reasons"]
        remaining = output["revised_plan"]
        assert [change["node"] for change in remaining] == [APP_C]
        assert output["verdict"] != "REJECT", output["reasons"]
        assert output["proof"]["status"] == "PROVEN_SAFE", output["proof"]

        # Implement the approved change, then rebuild.
        (repo / "app" / "c.py").write_text(
            "from app.a import fa\n\n\ndef fc():\n    return fa()\n", encoding="utf-8",
        )
        _cg(repo, "build")

        report = reconcile_project(repo)
        assert report["matches"] is True, json.dumps(report, indent=2)
        assert report["actual_node_count"] > 0
