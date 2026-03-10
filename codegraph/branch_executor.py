"""codegraph.branch_executor — Git branch-based architecture execution.

Provides safe execution environments for architecture changes using
git branches. Each architecture change runs in its own branch sandbox,
enabling rollback, comparison, and testing before merge.

Lifecycle:
    create_branch → execute tasks → build → analyze → compare → merge/reject
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from codegraph.git_utils import get_current_commit, is_git_repo
from codegraph.logging_config import get_logger

logger = get_logger("branch_executor")

BRANCH_STATE_FILE = "branch.json"
BRANCH_METRICS_FILE = "branch_metrics.json"


@dataclass
class BranchMetrics:
    """Metrics captured on a branch for comparison."""

    node_count: int = 0
    edge_count: int = 0
    policy_violations: int = 0
    cycles: int = 0
    health_score: float = 0.0
    test_count: int = 0
    tests_passed: bool = True
    fan_out_max: int = 0
    fan_in_max: int = 0
    coupling_avg: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "policy_violations": self.policy_violations,
            "cycles": self.cycles,
            "health_score": round(self.health_score, 3),
            "test_count": self.test_count,
            "tests_passed": self.tests_passed,
            "fan_out_max": self.fan_out_max,
            "fan_in_max": self.fan_in_max,
            "coupling_avg": round(self.coupling_avg, 4),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> BranchMetrics:
        return cls(
            node_count=d.get("node_count", 0),
            edge_count=d.get("edge_count", 0),
            policy_violations=d.get("policy_violations", 0),
            cycles=d.get("cycles", 0),
            health_score=d.get("health_score", 0.0),
            test_count=d.get("test_count", 0),
            tests_passed=d.get("tests_passed", True),
            fan_out_max=d.get("fan_out_max", 0),
            fan_in_max=d.get("fan_in_max", 0),
            coupling_avg=d.get("coupling_avg", 0.0),
        )


@dataclass
class BranchState:
    """State of an architecture execution branch."""

    branch_name: str
    base_branch: str = "master"
    architecture_change: str = ""
    status: str = "created"  # created, implementing, validating, ready, merged, rejected
    created_at: str = ""
    base_metrics: Optional[BranchMetrics] = None
    branch_metrics: Optional[BranchMetrics] = None
    tasks_total: int = 0
    tasks_completed: int = 0
    commit_sha: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "branch_name": self.branch_name,
            "base_branch": self.base_branch,
            "architecture_change": self.architecture_change,
            "status": self.status,
            "tasks_total": self.tasks_total,
            "tasks_completed": self.tasks_completed,
        }
        if self.created_at:
            d["created_at"] = self.created_at
        if self.commit_sha:
            d["commit_sha"] = self.commit_sha
        if self.base_metrics:
            d["base_metrics"] = self.base_metrics.to_dict()
        if self.branch_metrics:
            d["branch_metrics"] = self.branch_metrics.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> BranchState:
        base_m = None
        if "base_metrics" in d:
            base_m = BranchMetrics.from_dict(d["base_metrics"])
        branch_m = None
        if "branch_metrics" in d:
            branch_m = BranchMetrics.from_dict(d["branch_metrics"])
        return cls(
            branch_name=d["branch_name"],
            base_branch=d.get("base_branch", "master"),
            architecture_change=d.get("architecture_change", ""),
            status=d.get("status", "created"),
            created_at=d.get("created_at", ""),
            base_metrics=base_m,
            branch_metrics=branch_m,
            tasks_total=d.get("tasks_total", 0),
            tasks_completed=d.get("tasks_completed", 0),
            commit_sha=d.get("commit_sha", ""),
        )


@dataclass
class BranchComparison:
    """Comparison between base and branch metrics."""

    base_branch: str
    feature_branch: str
    health_delta: float = 0.0
    cycle_delta: int = 0
    violation_delta: int = 0
    fan_out_delta: int = 0
    fan_in_delta: int = 0
    coupling_delta: float = 0.0
    recommendation: str = ""  # merge, reject, review

    def to_dict(self) -> Dict[str, Any]:
        return {
            "base_branch": self.base_branch,
            "feature_branch": self.feature_branch,
            "health_delta": round(self.health_delta, 3),
            "cycle_delta": self.cycle_delta,
            "violation_delta": self.violation_delta,
            "fan_out_delta": self.fan_out_delta,
            "fan_in_delta": self.fan_in_delta,
            "coupling_delta": round(self.coupling_delta, 4),
            "recommendation": self.recommendation,
        }

    def format(self) -> str:
        lines = [f"Branch Comparison: {self.base_branch} ↔ {self.feature_branch}"]
        lines.append(f"  Health:     {'+' if self.health_delta >= 0 else ''}{self.health_delta:.1f}")
        lines.append(f"  Cycles:     {'+' if self.cycle_delta >= 0 else ''}{self.cycle_delta}")
        lines.append(f"  Violations: {'+' if self.violation_delta >= 0 else ''}{self.violation_delta}")
        lines.append(f"  Fan-out:    {'+' if self.fan_out_delta >= 0 else ''}{self.fan_out_delta}")
        lines.append(f"  Coupling:   {'+' if self.coupling_delta >= 0 else ''}{self.coupling_delta:.4f}")
        lines.append(f"  Recommendation: {self.recommendation}")
        return "\n".join(lines)


# ── Branch Operations ──────────────────────────────────────────────────


def create_branch(
    project_root: Path,
    change_name: str,
    base_branch: str = "master",
) -> BranchState:
    """Create a new git branch for an architecture change.

    Returns the BranchState tracking this execution branch.
    """
    if not is_git_repo(project_root):
        raise RuntimeError(f"Not a git repository: {project_root}")

    branch_name = f"codegraph/{change_name}"
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    # Create and checkout the branch
    _run_git(project_root, ["checkout", "-b", branch_name])

    state = BranchState(
        branch_name=branch_name,
        base_branch=base_branch,
        architecture_change=change_name,
        status="created",
        created_at=now,
        commit_sha=get_current_commit(project_root) or "",
    )

    _save_branch_state(project_root, state)
    logger.info("Created architecture branch: %s", branch_name)
    return state


def get_current_branch(project_root: Path) -> str:
    """Get the name of the current git branch."""
    result = _run_git(project_root, ["rev-parse", "--abbrev-ref", "HEAD"])
    return result.strip()


def load_branch_state(project_root: Path) -> Optional[BranchState]:
    """Load the current branch execution state."""
    path = project_root / ".codegraph" / "git" / BRANCH_STATE_FILE
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    return BranchState.from_dict(json.loads(text))


def update_branch_status(project_root: Path, status: str) -> None:
    """Update the status of the current branch."""
    state = load_branch_state(project_root)
    if state:
        state.status = status
        _save_branch_state(project_root, state)


def capture_metrics(project_root: Path) -> BranchMetrics:
    """Capture current architecture metrics for comparison.

    Reads from .codegraph data files to gather metrics.
    """
    metrics = BranchMetrics()

    # Read graph0 for node count
    g0_path = project_root / ".codegraph" / "graphs" / "graph0.json"
    if g0_path.exists():
        g0 = json.loads(g0_path.read_text(encoding="utf-8"))
        metrics.node_count = len(g0.get("nodes", []))

    # Read workflow for edge count
    wf_path = project_root / ".codegraph" / "workflow" / "workflow.json"
    if wf_path.exists():
        wf = json.loads(wf_path.read_text(encoding="utf-8"))
        metrics.edge_count = len(wf.get("edges", []))

        # Compute fan-in/fan-out
        fan_in: Dict[str, int] = {}
        fan_out: Dict[str, int] = {}
        for e in wf.get("edges", []):
            src = e.get("source", "")
            tgt = e.get("target", "")
            fan_out[src] = fan_out.get(src, 0) + 1
            fan_in[tgt] = fan_in.get(tgt, 0) + 1
        if fan_out:
            metrics.fan_out_max = max(fan_out.values())
        if fan_in:
            metrics.fan_in_max = max(fan_in.values())

    # Read tasks for violation count
    tasks_path = project_root / ".codegraph" / "tasks" / "tasks.json"
    if tasks_path.exists():
        tasks = json.loads(tasks_path.read_text(encoding="utf-8"))
        for task in tasks.get("tasks", []):
            if task.get("task_id") == "policy_violation":
                metrics.policy_violations = len(task.get("nodes", []))

    return metrics


def compare_branches(
    base_metrics: BranchMetrics,
    branch_metrics: BranchMetrics,
    base_name: str = "base",
    branch_name: str = "branch",
) -> BranchComparison:
    """Compare metrics between base and feature branch.

    Returns a recommendation: merge, reject, or review.
    """
    comp = BranchComparison(
        base_branch=base_name,
        feature_branch=branch_name,
        health_delta=branch_metrics.health_score - base_metrics.health_score,
        cycle_delta=branch_metrics.cycles - base_metrics.cycles,
        violation_delta=branch_metrics.policy_violations - base_metrics.policy_violations,
        fan_out_delta=branch_metrics.fan_out_max - base_metrics.fan_out_max,
        fan_in_delta=branch_metrics.fan_in_max - base_metrics.fan_in_max,
        coupling_delta=branch_metrics.coupling_avg - base_metrics.coupling_avg,
    )

    # Decision logic
    blockers = 0
    improvements = 0

    if comp.cycle_delta > 0:
        blockers += 2  # new cycles are serious
    elif comp.cycle_delta < 0:
        improvements += 1

    if comp.violation_delta > 0:
        blockers += 1
    elif comp.violation_delta < 0:
        improvements += 1

    if comp.health_delta < -0.1:
        blockers += 1
    elif comp.health_delta > 0.05:
        improvements += 1

    if comp.coupling_delta > 0.1:
        blockers += 1
    elif comp.coupling_delta < -0.05:
        improvements += 1

    if not branch_metrics.tests_passed:
        blockers += 3  # tests must pass

    if blockers >= 2:
        comp.recommendation = "reject"
    elif blockers >= 1:
        comp.recommendation = "review"
    elif improvements >= 2:
        comp.recommendation = "merge"
    else:
        comp.recommendation = "review"

    return comp


def validate_branch(project_root: Path) -> BranchComparison:
    """Validate current branch against base metrics.

    Captures current metrics and compares against stored base metrics.
    Returns comparison with recommendation.
    """
    state = load_branch_state(project_root)
    if not state:
        raise RuntimeError("No branch state found. Use create_branch first.")

    branch_metrics = capture_metrics(project_root)
    state.branch_metrics = branch_metrics
    state.status = "validating"
    _save_branch_state(project_root, state)

    base_metrics = state.base_metrics or BranchMetrics()
    comparison = compare_branches(
        base_metrics, branch_metrics,
        base_name=state.base_branch,
        branch_name=state.branch_name,
    )

    # Save comparison
    metrics_path = project_root / ".codegraph" / "git" / BRANCH_METRICS_FILE
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.write_text(
        json.dumps(comparison.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    if comparison.recommendation == "merge":
        state.status = "ready"
    elif comparison.recommendation == "reject":
        state.status = "rejected"
    else:
        state.status = "ready"
    _save_branch_state(project_root, state)

    return comparison


def merge_branch(project_root: Path) -> bool:
    """Merge the current architecture branch back to base.

    Returns True if merge succeeded.
    """
    state = load_branch_state(project_root)
    if not state:
        raise RuntimeError("No branch state found.")

    current = get_current_branch(project_root)
    if current != state.branch_name:
        raise RuntimeError(
            f"Not on architecture branch. Current: {current}, expected: {state.branch_name}"
        )

    base = state.base_branch
    try:
        _run_git(project_root, ["checkout", base])
        _run_git(project_root, ["merge", state.branch_name])
        state.status = "merged"
        _save_branch_state(project_root, state)
        logger.info("Merged %s → %s", state.branch_name, base)
        return True
    except RuntimeError as exc:
        logger.error("Merge failed: %s", exc)
        _run_git(project_root, ["checkout", state.branch_name])
        return False


def discard_branch(project_root: Path) -> None:
    """Discard the current architecture branch."""
    state = load_branch_state(project_root)
    if not state:
        raise RuntimeError("No branch state found.")

    base = state.base_branch
    _run_git(project_root, ["checkout", base])
    _run_git(project_root, ["branch", "-D", state.branch_name])
    state.status = "rejected"

    # Clean up branch state file
    state_path = project_root / ".codegraph" / "git" / BRANCH_STATE_FILE
    if state_path.exists():
        state_path.unlink()

    logger.info("Discarded branch: %s", state.branch_name)


def list_architecture_branches(project_root: Path) -> List[str]:
    """List all codegraph architecture branches."""
    result = _run_git(project_root, ["branch", "--list", "codegraph/*"])
    branches = []
    for line in result.strip().splitlines():
        branch = line.strip().lstrip("* ")
        if branch:
            branches.append(branch)
    return branches


# ── Private Helpers ────────────────────────────────────────────────────


def _run_git(project_root: Path, args: List[str]) -> str:
    """Run a git command and return stdout."""
    result = subprocess.run(
        ["git"] + args,
        cwd=str(project_root),
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def _save_branch_state(project_root: Path, state: BranchState) -> None:
    """Save branch state to .codegraph/git/branch.json."""
    git_dir = project_root / ".codegraph" / "git"
    git_dir.mkdir(parents=True, exist_ok=True)
    path = git_dir / BRANCH_STATE_FILE
    path.write_text(
        json.dumps(state.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
