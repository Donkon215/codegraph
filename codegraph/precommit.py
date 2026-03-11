"""codegraph.precommit — Pre-commit / pre-merge simulation gate.

Runs architecture simulation before allowing commits/merges.
Checks that the proposed change does not degrade key architecture metrics.

Usage:
    codegraph pre-commit           # check before commit
    codegraph pre-commit --strict  # block on any warning

Can be used as a Git pre-commit hook:
    #!/bin/sh
    codegraph pre-commit || exit 1
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from codegraph.logging_config import get_logger

logger = get_logger("precommit")


# ═══════════════════════════════════════════════════════════════════════
# Simulation Result
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class SimulationCheck:
    """A single metric check result."""

    metric: str
    before: float
    after: float
    delta: float
    status: str  # pass, warn, block
    threshold: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metric": self.metric,
            "before": round(self.before, 3),
            "after": round(self.after, 3),
            "delta": round(self.delta, 3),
            "status": self.status,
        }


@dataclass
class PreCommitReport:
    """Result of pre-commit simulation gate."""

    checks: List[SimulationCheck] = field(default_factory=list)
    passed: bool = True
    blocked: bool = False
    warnings: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "blocked": self.blocked,
            "warnings": self.warnings,
            "checks": [c.to_dict() for c in self.checks],
        }

    def format(self) -> str:
        status = "PASSED" if self.passed else "BLOCKED"
        lines = [f"Pre-commit Simulation: {status}"]

        for c in self.checks:
            icon = {"pass": "✓", "warn": "⚠", "block": "✗"}.get(
                c.status, "?")
            lines.append(
                f"  {icon} {c.metric}: {c.before:.3f} → {c.after:.3f} "
                f"({c.delta:+.3f})"
            )

        if self.warnings:
            lines.append(f"\n  {self.warnings} warning(s)")
        if self.blocked:
            lines.append("\n  Commit blocked — fix architecture issues first")

        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# Metric Thresholds
# ═══════════════════════════════════════════════════════════════════════

DEFAULT_THRESHOLDS = {
    "score": -0.05,          # block if score drops > 5%
    "coupling": 0.1,         # warn if coupling increases > 10%
    "modularity": -0.1,      # warn if modularity drops > 10%
    "fan_out_max": 5,         # warn if max fan-out increases > 5
    "cycles": 1,              # block if new cycles appear
    "god_modules": 1,         # warn if new god modules appear
}


# ═══════════════════════════════════════════════════════════════════════
# Core Check
# ═══════════════════════════════════════════════════════════════════════


def run_pre_commit_check(
    project_root: Path,
    *,
    strict: bool = False,
) -> PreCommitReport:
    """Run architecture simulation gate before commit.

    Compares current metrics against the last recorded baseline.
    If metrics degrade beyond thresholds, the check fails.

    Args:
        project_root: Project root directory.
        strict: If True, warnings also block the commit.

    Returns:
        PreCommitReport with pass/block status and details.
    """
    report = PreCommitReport()

    baseline = _load_baseline(project_root)
    current = _compute_current_metrics(project_root)

    if not baseline:
        # No baseline → first run, just record and pass
        _save_baseline(project_root, current)
        report.checks.append(SimulationCheck(
            metric="baseline", before=0, after=0, delta=0,
            status="pass",
        ))
        return report

    # Check each metric
    _check_metric(report, "score", baseline, current,
                  DEFAULT_THRESHOLDS["score"], "block")
    _check_metric(report, "coupling", baseline, current,
                  DEFAULT_THRESHOLDS["coupling"], "warn", invert=True)
    _check_metric(report, "modularity", baseline, current,
                  DEFAULT_THRESHOLDS["modularity"], "warn")
    _check_metric(report, "fan_out_max", baseline, current,
                  DEFAULT_THRESHOLDS["fan_out_max"], "warn", invert=True)
    _check_metric(report, "cycles", baseline, current,
                  DEFAULT_THRESHOLDS["cycles"], "block", invert=True)
    _check_metric(report, "god_modules", baseline, current,
                  DEFAULT_THRESHOLDS["god_modules"], "warn", invert=True)

    # Determine overall status
    for c in report.checks:
        if c.status == "block":
            report.blocked = True
            report.passed = False
        elif c.status == "warn":
            report.warnings += 1
            if strict:
                report.passed = False

    # Update baseline if passed
    if report.passed:
        _save_baseline(project_root, current)

    return report


def _check_metric(
    report: PreCommitReport,
    metric: str,
    baseline: Dict[str, float],
    current: Dict[str, float],
    threshold: float,
    fail_action: str,
    *,
    invert: bool = False,
) -> None:
    """Check a single metric against threshold.

    Args:
        invert: If True, positive delta is bad (e.g., coupling increase).
    """
    before = baseline.get(metric, 0.0)
    after = current.get(metric, 0.0)
    delta = after - before

    if invert:
        violated = delta > abs(threshold)
    else:
        violated = delta < threshold  # negative threshold = decrease is bad

    status = fail_action if violated else "pass"
    report.checks.append(SimulationCheck(
        metric=metric, before=before, after=after,
        delta=delta, status=status, threshold=threshold,
    ))


# ═══════════════════════════════════════════════════════════════════════
# Baseline Management
# ═══════════════════════════════════════════════════════════════════════


def _load_baseline(project_root: Path) -> Dict[str, float]:
    """Load last known good metrics baseline."""
    path = project_root / ".codegraph" / "baselines" / "metrics_baseline.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_baseline(project_root: Path, metrics: Dict[str, float]) -> None:
    """Save current metrics as the new baseline."""
    path = project_root / ".codegraph" / "baselines" / "metrics_baseline.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _compute_current_metrics(project_root: Path) -> Dict[str, float]:
    """Compute current architecture metrics from available data."""
    metrics: Dict[str, float] = {}

    # Try to get metrics from health report
    health_path = project_root / ".codegraph" / "health" / "health_report.json"
    if health_path.exists():
        try:
            data = json.loads(health_path.read_text(encoding="utf-8"))
            metrics["score"] = data.get("overall_score", 0.0)
            metrics["coupling"] = data.get("coupling", 0.0)
            metrics["modularity"] = data.get("modularity", 0.0)
        except (json.JSONDecodeError, OSError):
            pass

    # Try to get metrics from advisor
    advice_path = (project_root / ".codegraph" / "architecture"
                   / "architecture_advice.json")
    if advice_path.exists():
        try:
            data = json.loads(advice_path.read_text(encoding="utf-8"))
            metrics.setdefault("score", data.get("score", 0.0))
            smells = data.get("smells", [])
            metrics["cycles"] = sum(
                1 for s in smells if s.get("smell_type") == "cycle"
            )
            metrics["god_modules"] = sum(
                1 for s in smells if s.get("smell_type") == "god_module"
            )
        except (json.JSONDecodeError, OSError):
            pass

    # Try to compute fan-out from workflow
    wf_path = project_root / ".codegraph" / "workflow" / "workflow.json"
    if wf_path.exists():
        try:
            data = json.loads(wf_path.read_text(encoding="utf-8"))
            edges = data.get("edges", [])
            fan_out: Dict[str, int] = {}
            for e in edges:
                src = e.get("source", "")
                fan_out[src] = fan_out.get(src, 0) + 1
            metrics["fan_out_max"] = max(fan_out.values()) if fan_out else 0
        except (json.JSONDecodeError, OSError):
            pass

    return metrics
