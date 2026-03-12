"""codegraph.pipeline_orchestrator — Full pipeline orchestration engine.

Enforces the mandatory architecture evolution pipeline as a state machine:

    BUILD → ANALYZE → ADVISOR → DELTA → CONTEXT → SIMULATE → PROVE
    → IMPLEMENT → TEST → SCORE_COMPARE → MERGE_DECISION

Each step produces a structured result with a ``next_action`` field,
so the agent follows state transitions rather than a procedural script.

State machine transitions:
    command → result → next_action

Failure handling:
    SIMULATION_FAIL → discard candidate → try next
    TEST_FAIL       → revert commit → repair
    SCORE_DROP      → revert architecture change → stop

CLI command: codegraph pipeline (full orchestrated pipeline)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from codegraph.logging_config import get_logger

logger = get_logger("pipeline_orchestrator")


# ═══════════════════════════════════════════════════════════════════════
# Pipeline States
# ═══════════════════════════════════════════════════════════════════════


class PipelineState(str, Enum):
    """States in the architecture evolution pipeline."""

    IDLE = "idle"
    BUILD = "build"
    ANALYZE = "analyze"
    ADVISOR = "advisor"
    DELTA = "delta"
    CONTEXT = "context"
    SIMULATE = "simulate"
    PROVE = "prove"
    IMPLEMENT = "implement"
    TEST = "test"
    SCORE_COMPARE = "score_compare"
    MERGE_DECISION = "merge_decision"
    CONVERGED = "converged"
    FAILED = "failed"
    BLOCKED = "blocked"


# State transition table: current_state → next_state on success
STATE_TRANSITIONS: Dict[PipelineState, PipelineState] = {
    PipelineState.IDLE: PipelineState.BUILD,
    PipelineState.BUILD: PipelineState.ANALYZE,
    PipelineState.ANALYZE: PipelineState.ADVISOR,
    PipelineState.ADVISOR: PipelineState.DELTA,
    PipelineState.DELTA: PipelineState.CONTEXT,
    PipelineState.CONTEXT: PipelineState.SIMULATE,
    PipelineState.SIMULATE: PipelineState.PROVE,
    PipelineState.PROVE: PipelineState.IMPLEMENT,
    PipelineState.IMPLEMENT: PipelineState.TEST,
    PipelineState.TEST: PipelineState.SCORE_COMPARE,
    PipelineState.SCORE_COMPARE: PipelineState.MERGE_DECISION,
    PipelineState.MERGE_DECISION: PipelineState.CONVERGED,
}

# Failure transitions
FAILURE_TRANSITIONS: Dict[PipelineState, PipelineState] = {
    PipelineState.SIMULATE: PipelineState.BLOCKED,
    PipelineState.PROVE: PipelineState.BLOCKED,
    PipelineState.TEST: PipelineState.ANALYZE,   # retry after test fix
    PipelineState.SCORE_COMPARE: PipelineState.BLOCKED,
}


# ═══════════════════════════════════════════════════════════════════════
# Step Result
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class StepResult:
    """Result of a single pipeline step."""

    state: str
    status: str  # success, failed, warning, skipped
    next_action: str = ""
    reason: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "state": self.state,
            "status": self.status,
            "next_action": self.next_action,
        }
        if self.reason:
            d["reason"] = self.reason
        if self.data:
            d["data"] = self.data
        if self.timestamp:
            d["timestamp"] = self.timestamp
        return d


@dataclass
class PipelineReport:
    """Complete report of a pipeline execution."""

    steps: List[StepResult] = field(default_factory=list)
    final_state: str = "idle"
    started_at: str = ""
    completed_at: str = ""
    success: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "final_state": self.final_state,
            "success": self.success,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "steps": [s.to_dict() for s in self.steps],
            "step_count": len(self.steps),
        }

    def format(self) -> str:
        icon = "PASS" if self.success else "FAIL"
        lines = [f"Pipeline Report [{icon}]"]
        lines.append(f"  Final state: {self.final_state}")
        lines.append(f"  Steps: {len(self.steps)}")
        for step in self.steps:
            s_icon = {"success": "+", "failed": "X", "warning": "!",
                      "skipped": "o"}.get(step.status, "?")
            line = f"    [{s_icon}] {step.state}"
            if step.reason:
                line += f": {step.reason}"
            if step.next_action:
                line += f" -> {step.next_action}"
            lines.append(line)
        return "\n".join(lines)

    def save(self, project_root: Path) -> Path:
        path = project_root / ".codegraph" / "pipeline_report.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return path


# ═══════════════════════════════════════════════════════════════════════
# Pipeline Execution
# ═══════════════════════════════════════════════════════════════════════


def run_pipeline(
    project_root: Path,
    *,
    dry_run: bool = False,
    max_retries: int = 2,
) -> PipelineReport:
    """Execute the full architecture evolution pipeline.

    Follows the state machine from BUILD through MERGE_DECISION.
    Each step returns a result with ``next_action``.
    On failure, follows FAILURE_TRANSITIONS to recover or stop.
    """
    report = PipelineReport(
        started_at=datetime.now(timezone.utc).isoformat(),
    )

    state = PipelineState.BUILD
    retries = 0

    while state not in (PipelineState.CONVERGED, PipelineState.FAILED,
                        PipelineState.BLOCKED):
        step = _execute_step(project_root, state, dry_run=dry_run)
        report.steps.append(step)

        if step.status == "success":
            next_state = STATE_TRANSITIONS.get(state)
            if next_state:
                state = next_state
            else:
                state = PipelineState.CONVERGED
            retries = 0

        elif step.status == "failed":
            fallback = FAILURE_TRANSITIONS.get(state, PipelineState.FAILED)
            if fallback == state and retries >= max_retries:
                state = PipelineState.FAILED
            elif fallback == state:
                retries += 1
            else:
                state = fallback
                retries = 0

        elif step.status == "skipped":
            # Skip to next state
            next_state = STATE_TRANSITIONS.get(state)
            if next_state:
                state = next_state
            else:
                state = PipelineState.CONVERGED

        elif step.status == "warning":
            # Continue but record warning
            next_state = STATE_TRANSITIONS.get(state)
            if next_state:
                state = next_state
            else:
                state = PipelineState.CONVERGED

    report.final_state = state.value
    report.success = state == PipelineState.CONVERGED
    report.completed_at = datetime.now(timezone.utc).isoformat()

    return report


def _execute_step(
    project_root: Path,
    state: PipelineState,
    dry_run: bool = False,
) -> StepResult:
    """Execute a single pipeline step."""
    now = datetime.now(timezone.utc).isoformat()

    handlers = {
        PipelineState.BUILD: _step_build,
        PipelineState.ANALYZE: _step_analyze,
        PipelineState.ADVISOR: _step_advisor,
        PipelineState.DELTA: _step_delta,
        PipelineState.CONTEXT: _step_context,
        PipelineState.SIMULATE: _step_simulate,
        PipelineState.PROVE: _step_prove,
        PipelineState.IMPLEMENT: _step_implement,
        PipelineState.TEST: _step_test,
        PipelineState.SCORE_COMPARE: _step_score_compare,
        PipelineState.MERGE_DECISION: _step_merge_decision,
    }

    handler = handlers.get(state)
    if handler is None:
        return StepResult(
            state=state.value, status="failed",
            reason=f"No handler for state {state.value}",
            timestamp=now,
        )

    try:
        result = handler(project_root, dry_run=dry_run)
        result.timestamp = now
        return result
    except Exception as exc:
        logger.error("Step %s failed: %s", state.value, exc)
        return StepResult(
            state=state.value, status="failed",
            reason=str(exc), timestamp=now,
        )


# ═══════════════════════════════════════════════════════════════════════
# Step Handlers
# ═══════════════════════════════════════════════════════════════════════


def _step_build(root: Path, dry_run: bool = False) -> StepResult:
    """Build the graph."""
    from codegraph.extractor import extract_and_save_graph0
    from codegraph.workflow import build_and_save_workflow

    try:
        g0 = extract_and_save_graph0(root)
        node_count = len(g0.nodes) if hasattr(g0, 'nodes') else 0

        wf = build_and_save_workflow(root)
        edge_count = len(wf.edges) if hasattr(wf, 'edges') else 0

        return StepResult(
            state="build", status="success",
            next_action="analyze",
            reason=f"Graph built: {node_count} nodes, {edge_count} edges",
            data={"nodes": node_count, "edges": edge_count},
        )
    except Exception as exc:
        return StepResult(
            state="build", status="failed",
            reason=f"Build failed: {exc}",
        )


def _step_analyze(root: Path, dry_run: bool = False) -> StepResult:
    """Run analysis."""
    from codegraph.analyzer import run_analysis
    from codegraph.extractor import load_graph0
    from codegraph.index import IndexStore
    from codegraph.workflow import load_workflow

    try:
        graph0 = load_graph0(root)
        workflow = load_workflow(root)

        with IndexStore(root) as index:
            report = run_analysis(graph0, workflow, index, project_root=root)

        violations = len(report.violations) if hasattr(report, 'violations') else 0
        tasks = len(report.tasks) if hasattr(report, 'tasks') else 0

        return StepResult(
            state="analyze", status="success",
            next_action="advisor",
            reason=f"Analysis complete: {violations} violations, {tasks} tasks",
            data={"violations": violations, "tasks": tasks},
        )
    except Exception as exc:
        return StepResult(
            state="analyze", status="failed",
            reason=f"Analysis failed: {exc}",
        )


def _step_advisor(root: Path, dry_run: bool = False) -> StepResult:
    """Run architecture advisor."""
    from codegraph.architecture_advisor import advise_architecture
    from codegraph.extractor import load_graph0
    from codegraph.index import IndexStore

    try:
        graph0 = load_graph0(root)

        with IndexStore(root) as index:
            advice = advise_architecture(graph0, index, project_root=root)

        smells = len(advice.smells) if hasattr(advice, 'smells') else 0
        score = advice.score if hasattr(advice, 'score') else 0.0

        if smells == 0:
            return StepResult(
                state="advisor", status="skipped",
                next_action="delta",
                reason="No architectural smells detected — already clean",
                data={"smells": 0, "score": score},
            )

        return StepResult(
            state="advisor", status="success",
            next_action="delta",
            reason=f"Advisor: {smells} smells, score={score:.3f}",
            data={"smells": smells, "score": score},
        )
    except Exception as exc:
        return StepResult(
            state="advisor", status="failed",
            reason=f"Advisor failed: {exc}",
        )


def _step_delta(root: Path, dry_run: bool = False) -> StepResult:
    """Generate architecture delta."""
    from codegraph.architecture_delta import generate_architecture_delta

    try:
        delta = generate_architecture_delta(root)

        if not delta.has_changes:
            return StepResult(
                state="delta", status="skipped",
                next_action="context",
                reason="No changes to apply",
            )

        delta.save(root)

        return StepResult(
            state="delta", status="success",
            next_action="context",
            reason=f"Delta: {delta.total_changes} changes, risk={delta.risk_estimate}",
            data=delta.to_dict(),
        )
    except Exception as exc:
        return StepResult(
            state="delta", status="failed",
            reason=f"Delta generation failed: {exc}",
        )


def _step_context(root: Path, dry_run: bool = False) -> StepResult:
    """Build Copilot context."""
    from codegraph.copilot_context_builder import build_enriched_context

    try:
        ctx = build_enriched_context(root)
        ctx.save(root)

        return StepResult(
            state="context", status="success",
            next_action="simulate",
            reason="Copilot context generated",
            data={"subsystems": len(ctx.base_context.subsystems)},
        )
    except Exception as exc:
        return StepResult(
            state="context", status="failed",
            reason=f"Context build failed: {exc}",
        )


def _step_simulate(root: Path, dry_run: bool = False) -> StepResult:
    """Run architecture simulation gate."""
    from codegraph.architecture_delta import ArchitectureDelta

    delta = ArchitectureDelta.load(root)
    if delta is None or not delta.has_changes:
        return StepResult(
            state="simulate", status="skipped",
            next_action="prove",
            reason="No delta to simulate",
        )

    risk = delta.risk_estimate
    violations = len(delta.constraint_violations)

    if risk in ("HIGH", "BLOCKED"):
        return StepResult(
            state="simulate", status="failed",
            next_action="blocked",
            reason=f"Simulation gate REJECTED: risk={risk}, "
                   f"violations={violations}",
            data={"risk": risk, "violations": violations},
        )

    status = "warning" if risk == "MEDIUM" else "success"
    return StepResult(
        state="simulate", status=status,
        next_action="prove",
        reason=f"Simulation: risk={risk}, violations={violations}",
        data={"risk": risk, "violations": violations},
    )


def _step_prove(root: Path, dry_run: bool = False) -> StepResult:
    """Generate architecture proof."""
    from codegraph.architecture_proof import (
        PROVEN_SAFE, PROVEN_WARNING, REJECTED, generate_proof,
    )

    try:
        proof = generate_proof(root)
        proof.save(root)

        if proof.status == REJECTED:
            return StepResult(
                state="prove", status="failed",
                next_action="blocked",
                reason=f"Proof REJECTED: {len(proof.violations)} violations, "
                       f"risk={proof.risk}",
                data=proof.to_dict(),
            )

        status = "warning" if proof.status == PROVEN_WARNING else "success"
        return StepResult(
            state="prove", status=status,
            next_action="implement",
            reason=f"Proof: {proof.status}",
            data=proof.to_dict(),
        )
    except Exception as exc:
        return StepResult(
            state="prove", status="failed",
            reason=f"Proof generation failed: {exc}",
        )


def _step_implement(root: Path, dry_run: bool = False) -> StepResult:
    """Implementation step (placeholder — actual implementation is done by Copilot)."""
    if dry_run:
        return StepResult(
            state="implement", status="skipped",
            next_action="test",
            reason="Dry run — skipping implementation",
        )

    return StepResult(
        state="implement", status="success",
        next_action="test",
        reason="Implementation ready — Copilot applies changes",
    )


def _step_test(root: Path, dry_run: bool = False) -> StepResult:
    """Run tests."""
    import subprocess

    if dry_run:
        return StepResult(
            state="test", status="skipped",
            next_action="score_compare",
            reason="Dry run — skipping tests",
        )

    try:
        result = subprocess.run(
            ["py", "-m", "pytest", "tests/", "-x", "--tb=short", "-q"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=300,
        )

        if result.returncode == 0:
            # Extract pass count from output
            last_line = result.stdout.strip().split("\n")[-1] if result.stdout else ""
            return StepResult(
                state="test", status="success",
                next_action="score_compare",
                reason=f"Tests passed: {last_line}",
            )
        else:
            return StepResult(
                state="test", status="failed",
                reason=f"Tests failed (exit {result.returncode})",
                data={"stderr": result.stderr[:500] if result.stderr else ""},
            )
    except subprocess.TimeoutExpired:
        return StepResult(
            state="test", status="failed",
            reason="Tests timed out (300s)",
        )
    except Exception as exc:
        return StepResult(
            state="test", status="failed",
            reason=f"Test execution failed: {exc}",
        )


def _step_score_compare(root: Path, dry_run: bool = False) -> StepResult:
    """Compare architecture score against baseline."""
    from codegraph.architecture_score import ArchitectureScore, compare_scores, compute_score

    try:
        current = compute_score(root)
        baseline = ArchitectureScore.load(root)

        if baseline is None:
            # No baseline — save current as baseline
            current.save(root)
            return StepResult(
                state="score_compare", status="success",
                next_action="merge_decision",
                reason=f"No baseline — saved current score {current.score:.3f} "
                       f"({current.grade}) as baseline",
                data=current.to_dict(),
            )

        comparison = compare_scores(baseline, current)

        if not comparison["merge_allowed"]:
            return StepResult(
                state="score_compare", status="failed",
                next_action="blocked",
                reason=(
                    f"Architecture score regression: "
                    f"{comparison['baseline_score']:.3f} -> "
                    f"{comparison['current_score']:.3f} "
                    f"(delta={comparison['delta']:+.3f})"
                ),
                data=comparison,
            )

        # Update baseline if improved
        if comparison["improved"]:
            current.save(root)

        return StepResult(
            state="score_compare", status="success",
            next_action="merge_decision",
            reason=(
                f"Score: {comparison['baseline_score']:.3f} -> "
                f"{comparison['current_score']:.3f} "
                f"({comparison['delta']:+.3f}) — "
                f"{'improved' if comparison['improved'] else 'stable'}"
            ),
            data=comparison,
        )
    except Exception as exc:
        return StepResult(
            state="score_compare", status="failed",
            reason=f"Score comparison failed: {exc}",
        )


def _step_merge_decision(root: Path, dry_run: bool = False) -> StepResult:
    """Make the final merge decision."""
    from codegraph.architecture_proof import ArchitectureProof, PROVEN_SAFE, PROVEN_WARNING

    proof = ArchitectureProof.load(root)

    if proof and proof.status not in (PROVEN_SAFE, PROVEN_WARNING):
        return StepResult(
            state="merge_decision", status="failed",
            reason=f"Merge blocked — proof status: {proof.status}",
        )

    if dry_run:
        return StepResult(
            state="merge_decision", status="success",
            next_action="converged",
            reason="Dry run — merge would be allowed",
        )

    return StepResult(
        state="merge_decision", status="success",
        next_action="converged",
        reason="Merge allowed — all gates passed",
    )
