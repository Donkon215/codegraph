from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict


@dataclass
class SubsystemExperimentResult:
    branch: str
    score_before: float
    score_after: float
    proof_status: str
    accepted: bool
    details: Dict[str, Any]


def run_subsystem_experiment(
    project_root: Path,
    subsystem_name: str,
    *,
    execute: bool = False,
) -> SubsystemExperimentResult:
    branch = f"feature/architecture-refactor-{subsystem_name.lower().replace(' ', '-') }"

    score_before = _read_score(project_root)

    if execute:
        _run(["git", "checkout", "-b", branch], cwd=project_root)
        _run(["codegraph", "build"], cwd=project_root)
        _run(["codegraph", "analyze"], cwd=project_root)
        _run(["codegraph", "prove"], cwd=project_root)
        _run(["codegraph", "score", "--compare"], cwd=project_root)

    proof_status = _read_latest_proof_status(project_root)
    score_after = _read_score(project_root)
    accepted = (proof_status == "PROVEN_SAFE") and (score_after >= score_before)

    return SubsystemExperimentResult(
        branch=branch,
        score_before=score_before,
        score_after=score_after,
        proof_status=proof_status,
        accepted=accepted,
        details={
            "decision": "accept" if accepted else "discard",
            "subsystem": subsystem_name,
        },
    )


def _run(cmd: list[str], *, cwd: Path) -> None:
    subprocess.run(cmd, cwd=str(cwd), check=True)


def _read_score(project_root: Path) -> float:
    import json

    score_path = project_root / ".codegraph" / "architecture_score.json"
    if not score_path.exists():
        return 0.0
    try:
        score = json.loads(score_path.read_text(encoding="utf-8"))
    except Exception:
        return 0.0
    return float(score.get("score", 0.0))


def _read_latest_proof_status(project_root: Path) -> str:
    import json

    proof_path = project_root / ".codegraph" / "proofs" / "latest_proof.json"
    if not proof_path.exists():
        return "UNKNOWN"
    try:
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
    except Exception:
        return "UNKNOWN"
    return str(proof.get("status", "UNKNOWN"))
