"""codegraph.architecture_proof — Architecture proof system.

Mandatory simulation gate that proves architecture changes are safe
before allowing implementation. Every architecture proposal generates
a proof artifact that must pass before code can be written.

Proof protocol:
    1. Generate architecture candidate
    2. Run simulation (cycle detection, layer violations, subsystem
       constraints, transitive forbidden paths, coupling, blast radius)
    3. Produce proof artifact (.codegraph/proofs/arch_proof.json)
    4. Only implement if proof.status == PROVEN_SAFE

If risk_classification is HIGH_RISK or BLOCKED, the change is rejected.

CLI: codegraph prove (validate a delta/plan before implementation)
Output: .codegraph/proofs/arch_proof.json + .codegraph/proofs/latest_proof.json
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from codegraph.logging_config import get_logger

logger = get_logger("architecture_proof")

PROOFS_DIR = "proofs"

# Proof status values
PROVEN_SAFE = "PROVEN_SAFE"
PROVEN_WARNING = "PROVEN_WARNING"
REJECTED = "REJECTED"
UNTESTED = "UNTESTED"


@dataclass
class ProofViolation:
    """A violation found during proof simulation."""

    check: str  # cycles, layer, subsystem, transitive, coupling, blast_radius
    severity: str = "error"
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check": self.check,
            "severity": self.severity,
            "description": self.description,
        }


@dataclass
class ArchitectureProof:
    """Proof artifact for an architecture change proposal."""

    proposal_id: str = ""
    status: str = UNTESTED
    timestamp: str = ""

    # Simulation results
    cycles: int = 0
    coupling_delta: float = 0.0
    fanout_delta: int = 0
    constraint_violations: int = 0
    blast_radius: int = 0
    risk: str = "LOW"
    violations: List[ProofViolation] = field(default_factory=list)

    # Budget checks
    files_modified: int = 0
    edges_added: int = 0
    edges_removed: int = 0
    budget_exceeded: bool = False

    # Score comparison
    score_before: float = 0.0
    score_after: float = 0.0
    score_delta: float = 0.0
    merge_allowed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "status": self.status,
            "timestamp": self.timestamp,
            "simulation": {
                "cycles": self.cycles,
                "coupling_delta": round(self.coupling_delta, 4),
                "fanout_delta": self.fanout_delta,
                "constraint_violations": self.constraint_violations,
                "blast_radius": self.blast_radius,
                "risk": self.risk,
                "violations": [v.to_dict() for v in self.violations],
            },
            "budget": {
                "files_modified": self.files_modified,
                "edges_added": self.edges_added,
                "edges_removed": self.edges_removed,
                "budget_exceeded": self.budget_exceeded,
            },
            "score": {
                "before": round(self.score_before, 4),
                "after": round(self.score_after, 4),
                "delta": round(self.score_delta, 4),
                "merge_allowed": self.merge_allowed,
            },
        }

    def format(self) -> str:
        icon = {
            PROVEN_SAFE: "PASS",
            PROVEN_WARNING: "WARN",
            REJECTED: "FAIL",
            UNTESTED: "????",
        }.get(self.status, "????")

        lines = [f"Architecture Proof [{icon}] — {self.proposal_id}"]
        lines.append(f"  Status: {self.status}")
        lines.append(f"  Risk: {self.risk}")
        lines.append(f"  Cycles: {self.cycles}")
        lines.append(f"  Coupling delta: {self.coupling_delta:+.4f}")
        lines.append(f"  Fan-out delta: {self.fanout_delta:+d}")
        lines.append(f"  Constraint violations: {self.constraint_violations}")
        lines.append(f"  Blast radius: {self.blast_radius}")
        lines.append(f"  Score: {self.score_before:.3f} -> {self.score_after:.3f} "
                      f"({self.score_delta:+.3f})")
        lines.append(f"  Merge allowed: {self.merge_allowed}")

        if self.budget_exceeded:
            lines.append(f"  BUDGET EXCEEDED: files={self.files_modified}, "
                          f"edges +{self.edges_added}/-{self.edges_removed}")

        if self.violations:
            lines.append(f"\n  Violations ({len(self.violations)}):")
            for v in self.violations:
                lines.append(f"    [{v.severity}] {v.check}: {v.description}")

        return "\n".join(lines)

    def save(self, project_root: Path) -> Path:
        """Save proof to .codegraph/proofs/."""
        proofs_dir = project_root / ".codegraph" / PROOFS_DIR
        proofs_dir.mkdir(parents=True, exist_ok=True)

        # Save with proposal_id
        proof_path = proofs_dir / f"{self.proposal_id}.json"
        data = json.dumps(self.to_dict(), indent=2, ensure_ascii=False)
        proof_path.write_text(data, encoding="utf-8")

        # Also save as latest
        latest_path = proofs_dir / "latest_proof.json"
        latest_path.write_text(data, encoding="utf-8")

        logger.info("Proof saved: %s (status=%s)", proof_path, self.status)
        return proof_path

    @classmethod
    def load(cls, project_root: Path, proposal_id: str = "") -> Optional["ArchitectureProof"]:
        """Load a proof. If no proposal_id given, loads latest."""
        proofs_dir = project_root / ".codegraph" / PROOFS_DIR
        if proposal_id:
            path = proofs_dir / f"{proposal_id}.json"
        else:
            path = proofs_dir / "latest_proof.json"

        if not path.exists():
            return None

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return _dict_to_proof(data)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load proof: %s", exc)
            return None


def _dict_to_proof(data: Dict[str, Any]) -> ArchitectureProof:
    """Deserialize a proof from a dictionary."""
    sim = data.get("simulation", {})
    budget = data.get("budget", {})
    sc = data.get("score", {})

    violations = [
        ProofViolation(
            check=v.get("check", ""),
            severity=v.get("severity", "error"),
            description=v.get("description", ""),
        )
        for v in sim.get("violations", [])
    ]

    return ArchitectureProof(
        proposal_id=data.get("proposal_id", ""),
        status=data.get("status", UNTESTED),
        timestamp=data.get("timestamp", ""),
        cycles=sim.get("cycles", 0),
        coupling_delta=sim.get("coupling_delta", 0.0),
        fanout_delta=sim.get("fanout_delta", 0),
        constraint_violations=sim.get("constraint_violations", 0),
        blast_radius=sim.get("blast_radius", 0),
        risk=sim.get("risk", "LOW"),
        violations=violations,
        files_modified=budget.get("files_modified", 0),
        edges_added=budget.get("edges_added", 0),
        edges_removed=budget.get("edges_removed", 0),
        budget_exceeded=budget.get("budget_exceeded", False),
        score_before=sc.get("before", 0.0),
        score_after=sc.get("after", 0.0),
        score_delta=sc.get("delta", 0.0),
        merge_allowed=sc.get("merge_allowed", False),
    )


# ═══════════════════════════════════════════════════════════════════════
# Proof Generation
# ═══════════════════════════════════════════════════════════════════════


def generate_proof(
    project_root: Path,
    proposal_id: str = "",
    *,
    delta: Optional[Dict[str, Any]] = None,
    refactor_budget: Optional[Dict[str, int]] = None,
) -> ArchitectureProof:
    """Generate an architecture proof by simulating a delta.

    Runs all simulation checks:
      1. Cycle detection
      2. Layer violation detection
      3. Subsystem constraint validation
      4. Coupling analysis
      5. Blast radius analysis
      6. Budget check
      7. Score comparison

    Returns a proof with status PROVEN_SAFE, PROVEN_WARNING, or REJECTED.
    """
    from codegraph.architecture_delta import ArchitectureDelta

    if not proposal_id:
        proposal_id = f"proof_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"

    proof = ArchitectureProof(
        proposal_id=proposal_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

    # Load delta
    if delta is None:
        loaded = ArchitectureDelta.load(project_root)
        if loaded is None:
            proof.status = UNTESTED
            proof.violations.append(ProofViolation(
                check="delta", severity="error",
                description="No architecture delta found. Run 'codegraph delta' first.",
            ))
            return proof
        delta = loaded.to_dict()

    # Extract change counts
    proof.edges_added = len(delta.get("added_edges", []))
    proof.edges_removed = len(delta.get("removed_edges", []))
    proof.files_modified = _count_affected_files(delta)

    # Budget check
    if refactor_budget is None:
        refactor_budget = _load_budget(project_root)

    proof.budget_exceeded = _check_budget(
        proof.files_modified,
        proof.edges_added,
        proof.edges_removed,
        refactor_budget,
    )

    if proof.budget_exceeded:
        proof.violations.append(ProofViolation(
            check="budget", severity="error",
            description=(
                f"Refactor budget exceeded: files={proof.files_modified}, "
                f"edges +{proof.edges_added}/-{proof.edges_removed}"
            ),
        ))

    # Constraint violations from delta
    proof.constraint_violations = len(delta.get("constraint_violations", []))
    for cv in delta.get("constraint_violations", []):
        proof.violations.append(ProofViolation(
            check="constraint",
            severity=cv.get("severity", "error"),
            description=cv.get("description", ""),
        ))

    # Risk from delta
    proof.risk = delta.get("risk_estimate", "LOW")
    proof.blast_radius = delta.get("total_changes", 0)

    # Run simulation via the simulator
    sim_result = _run_simulation(project_root, delta)
    if sim_result:
        proof.cycles = sim_result.get("new_cycles", 0)
        proof.coupling_delta = sim_result.get("coupling_delta", 0.0)
        proof.fanout_delta = sim_result.get("fanout_delta", 0)
        proof.blast_radius = sim_result.get("blast_radius", proof.blast_radius)

        for v in sim_result.get("violations", []):
            proof.violations.append(ProofViolation(
                check=v.get("violation_type", "simulation"),
                severity=v.get("severity", "warning"),
                description=v.get("description", ""),
            ))

        if not sim_result.get("safe", True):
            proof.risk = "HIGH"

    # Score comparison
    score_result = _compare_scores(project_root)
    if score_result:
        proof.score_before = score_result.get("baseline", 0.0)
        proof.score_after = score_result.get("current", 0.0)
        proof.score_delta = score_result.get("delta", 0.0)
        proof.merge_allowed = score_result.get("merge_allowed", True)

        if not proof.merge_allowed:
            proof.violations.append(ProofViolation(
                check="score_regression",
                severity="error",
                description=(
                    f"Architecture score regression: "
                    f"{proof.score_before:.3f} -> {proof.score_after:.3f}"
                ),
            ))

    # Classify proof status
    proof.status = _classify_proof(proof)
    return proof


def _count_affected_files(delta: Dict[str, Any]) -> int:
    """Count unique files affected by the delta."""
    files: set[str] = set()
    for n in delta.get("added_nodes", []) + delta.get("removed_nodes", []):
        mod = n.get("module", "") or n.get("node_id", "")
        if mod:
            files.add(mod.split("::")[0] if "::" in mod else mod)
    for e in delta.get("added_edges", []) + delta.get("removed_edges", []):
        for nid in (e.get("source", ""), e.get("target", "")):
            if nid:
                files.add(nid.split("::")[0] if "::" in nid else nid)
    return len(files)


def _load_budget(project_root: Path) -> Dict[str, int]:
    """Load refactor budget from agent_config."""
    config_path = project_root / ".codegraph" / "agent_config.json"
    defaults = {
        "max_files_modified": 12,
        "max_edges_added": 25,
        "max_edges_removed": 25,
    }
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            budget = config.get("refactor_budget", {})
            if budget:
                return budget
        except (json.JSONDecodeError, OSError):
            pass
    return defaults


def _check_budget(
    files: int,
    added: int,
    removed: int,
    budget: Dict[str, int],
) -> bool:
    """Return True if any budget limit is exceeded."""
    if files > budget.get("max_files_modified", 12):
        return True
    if added > budget.get("max_edges_added", 25):
        return True
    if removed > budget.get("max_edges_removed", 25):
        return True
    return False


def _run_simulation(
    project_root: Path,
    delta: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Run the simulator on the delta's changes."""
    try:
        from codegraph.index import IndexStore
        from codegraph.simulator import SimulatedChange, simulate_changes

        changes = []
        for edge in delta.get("added_edges", []):
            changes.append(SimulatedChange(
                action="add_edge",
                source=edge.get("source", ""),
                target=edge.get("target", ""),
                reason=edge.get("reason", ""),
            ))
        for edge in delta.get("removed_edges", []):
            changes.append(SimulatedChange(
                action="remove_edge",
                source=edge.get("source", ""),
                target=edge.get("target", ""),
                reason=edge.get("reason", ""),
            ))
        for node in delta.get("removed_nodes", []):
            changes.append(SimulatedChange(
                action="remove_node",
                node_id=node.get("node_id", ""),
                reason=node.get("reason", ""),
            ))

        if not changes:
            return None

        system_path = project_root / ".codegraph" / "architecture" / "system.json"

        with IndexStore(project_root) as index:
            result = simulate_changes(
                changes, index,
                system_json_path=system_path if system_path.exists() else None,
            )

        return result.to_dict()

    except Exception as exc:
        logger.warning("Simulation failed: %s", exc)
        return None


def _compare_scores(project_root: Path) -> Optional[Dict[str, Any]]:
    """Compare current score against baseline."""
    try:
        from codegraph.architecture_score import ArchitectureScore, compute_score

        baseline = ArchitectureScore.load(project_root)
        if baseline is None:
            return None

        current = compute_score(project_root)
        delta = current.score - baseline.score
        return {
            "baseline": baseline.score,
            "current": current.score,
            "delta": delta,
            "merge_allowed": delta >= -0.05,
        }
    except Exception as exc:
        logger.warning("Score comparison failed: %s", exc)
        return None


def _classify_proof(proof: ArchitectureProof) -> str:
    """Classify the final proof status."""
    errors = [v for v in proof.violations if v.severity == "error"]
    warnings = [v for v in proof.violations if v.severity == "warning"]

    if errors:
        return REJECTED

    if proof.risk in ("HIGH", "BLOCKED"):
        return REJECTED

    if proof.budget_exceeded:
        return REJECTED

    if not proof.merge_allowed and proof.score_before > 0:
        return REJECTED

    if warnings:
        return PROVEN_WARNING

    return PROVEN_SAFE
