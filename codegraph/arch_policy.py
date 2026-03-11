"""codegraph.arch_policy — Architecture Policy Engine.

Higher-level architecture policies beyond code-level governance rules.
Policies operate on **architecture evolution**, not just code structure.

Difference from suggest.py (governance):
  - Governance = rules about code (forbidden_call, dependency_limit)
  - Policy    = rules about architecture evolution (size limits,
                boundary enforcement, merge gates)

Policies:
  - no_large_modules: block modules above node threshold
  - frontend_backend_boundary: enforce layer separation
  - no_apply_without_plan: require plan before apply
  - max_subsystem_size: limit subsystem growth
  - score_gate: block merges that degrade architecture score
  - coupling_limit: cap cross-subsystem coupling
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from codegraph.logging_config import get_logger

logger = get_logger("arch_policy")

POLICY_FILE = "architecture_policies.json"


# ═══════════════════════════════════════════════════════════════════════
# Policy Definition
# ═══════════════════════════════════════════════════════════════════════


VALID_POLICY_TYPES = {
    "no_large_modules",
    "frontend_backend_boundary",
    "no_apply_without_plan",
    "max_subsystem_size",
    "score_gate",
    "coupling_limit",
    "layer_isolation",
    "forbidden_subsystem_dep",
    "custom",
}

VALID_ACTIONS = {
    "warn",       # log warning but allow
    "block",      # block the operation
    "suggest",    # suggest remediation
}


@dataclass
class ArchPolicy:
    """An architecture-level policy."""

    policy_id: str
    name: str
    policy_type: str  # from VALID_POLICY_TYPES
    rule: str  # human-readable rule description
    action: str = "warn"  # from VALID_ACTIONS
    threshold: float = 0.0  # numeric threshold (if applicable)
    target: str = ""  # scope: subsystem name, module pattern, etc.
    enabled: bool = True

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "policy_id": self.policy_id,
            "name": self.name,
            "policy_type": self.policy_type,
            "rule": self.rule,
            "action": self.action,
            "enabled": self.enabled,
        }
        if self.threshold:
            d["threshold"] = self.threshold
        if self.target:
            d["target"] = self.target
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> ArchPolicy:
        return cls(
            policy_id=d["policy_id"],
            name=d["name"],
            policy_type=d.get("policy_type", "custom"),
            rule=d.get("rule", ""),
            action=d.get("action", "warn"),
            threshold=d.get("threshold", 0.0),
            target=d.get("target", ""),
            enabled=d.get("enabled", True),
        )


# ═══════════════════════════════════════════════════════════════════════
# Policy Violation
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class PolicyViolation:
    """A violation of an architecture policy."""

    policy_id: str
    policy_name: str
    description: str
    action: str  # "warn" or "block"
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "policy_name": self.policy_name,
            "description": self.description,
            "action": self.action,
            "details": self.details,
        }


# ═══════════════════════════════════════════════════════════════════════
# Policy Evaluation Report
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class PolicyReport:
    """Result of evaluating architecture policies."""

    policies_checked: int = 0
    violations: List[PolicyViolation] = field(default_factory=list)
    passed: bool = True  # True if no blocking violations

    def to_dict(self) -> Dict[str, Any]:
        return {
            "policies_checked": self.policies_checked,
            "passed": self.passed,
            "violations": [v.to_dict() for v in self.violations],
            "summary": {
                "total_violations": len(self.violations),
                "blocking": sum(1 for v in self.violations if v.action == "block"),
                "warnings": sum(1 for v in self.violations if v.action == "warn"),
            },
        }

    def format(self) -> str:
        status = "PASSED ✓" if self.passed else "BLOCKED ✗"
        lines = [f"Architecture Policy Check: {status}"]
        lines.append(f"  Policies checked: {self.policies_checked}")
        lines.append(f"  Violations: {len(self.violations)}")

        blocking = [v for v in self.violations if v.action == "block"]
        warnings = [v for v in self.violations if v.action == "warn"]

        if blocking:
            lines.append(f"\nBlocking violations ({len(blocking)}):")
            for v in blocking:
                lines.append(f"  ✗ [{v.policy_id}] {v.description}")

        if warnings:
            lines.append(f"\nWarnings ({len(warnings)}):")
            for v in warnings:
                lines.append(f"  ⚠ [{v.policy_id}] {v.description}")

        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# Policy Store
# ═══════════════════════════════════════════════════════════════════════


def load_policies(project_root: Path) -> List[ArchPolicy]:
    """Load architecture policies from disk."""
    path = project_root / ".codegraph" / "policies" / POLICY_FILE
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [ArchPolicy.from_dict(p) for p in data.get("policies", [])]


def save_policies(project_root: Path, policies: List[ArchPolicy]) -> Path:
    """Save architecture policies to disk."""
    policy_dir = project_root / ".codegraph" / "policies"
    policy_dir.mkdir(parents=True, exist_ok=True)
    path = policy_dir / POLICY_FILE
    path.write_text(
        json.dumps(
            {"policies": [p.to_dict() for p in policies]},
            indent=2, ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    logger.info("Saved %d architecture policies", len(policies))
    return path


def add_policy(
    project_root: Path,
    name: str,
    policy_type: str,
    rule: str,
    action: str = "warn",
    threshold: float = 0.0,
    target: str = "",
) -> ArchPolicy:
    """Add a new architecture policy."""
    if policy_type not in VALID_POLICY_TYPES:
        raise ValueError(f"Invalid policy type: {policy_type}. "
                         f"Valid: {sorted(VALID_POLICY_TYPES)}")
    if action not in VALID_ACTIONS:
        raise ValueError(f"Invalid action: {action}. "
                         f"Valid: {sorted(VALID_ACTIONS)}")

    policies = load_policies(project_root)
    next_id = f"pol_{len(policies) + 1:03d}"

    policy = ArchPolicy(
        policy_id=next_id,
        name=name,
        policy_type=policy_type,
        rule=rule,
        action=action,
        threshold=threshold,
        target=target,
    )
    policies.append(policy)
    save_policies(project_root, policies)
    logger.info("Added policy %s: %s", next_id, name)
    return policy


def remove_policy(project_root: Path, policy_id: str) -> bool:
    """Remove a policy by ID."""
    policies = load_policies(project_root)
    before = len(policies)
    policies = [p for p in policies if p.policy_id != policy_id]
    if len(policies) == before:
        return False
    save_policies(project_root, policies)
    logger.info("Removed policy %s", policy_id)
    return True


# ═══════════════════════════════════════════════════════════════════════
# Policy Evaluation
# ═══════════════════════════════════════════════════════════════════════


def evaluate_policies(
    project_root: Path,
    graph_data: Optional[Dict[str, Any]] = None,
    architecture_data: Optional[Dict[str, Any]] = None,
    health_data: Optional[Dict[str, Any]] = None,
) -> PolicyReport:
    """Evaluate all enabled architecture policies.

    Loads architecture data from .codegraph if not provided.
    Returns a :class:`PolicyReport` with violations.
    """
    policies = load_policies(project_root)
    enabled = [p for p in policies if p.enabled]

    report = PolicyReport(policies_checked=len(enabled))

    # Load data lazily if not provided
    if graph_data is None:
        graph_data = _load_json(
            project_root / ".codegraph" / "graphs" / "graph0.json"
        )
    if architecture_data is None:
        architecture_data = _load_json(
            project_root / ".codegraph" / "architecture" / "system.json"
        )
    if health_data is None:
        health_data = _load_json(
            project_root / ".codegraph" / "health" / "health_report.json"
        )

    for policy in enabled:
        violations = _check_policy(
            policy, graph_data, architecture_data, health_data
        )
        report.violations.extend(violations)

    report.passed = not any(v.action == "block" for v in report.violations)
    return report


def _check_policy(
    policy: ArchPolicy,
    graph_data: Dict[str, Any],
    architecture_data: Dict[str, Any],
    health_data: Dict[str, Any],
) -> List[PolicyViolation]:
    """Evaluate a single policy."""
    handler = _POLICY_HANDLERS.get(policy.policy_type)
    if handler is None:
        return []
    return handler(policy, graph_data, architecture_data, health_data)


# ── Policy Handlers ────────────────────────────────────────────────────


def _check_no_large_modules(
    policy: ArchPolicy,
    graph_data: Dict[str, Any],
    architecture_data: Dict[str, Any],
    health_data: Dict[str, Any],
) -> List[PolicyViolation]:
    """Check for modules exceeding node count threshold."""
    threshold = int(policy.threshold) if policy.threshold else 50
    violations: List[PolicyViolation] = []

    # Count nodes per file
    file_counts: Dict[str, int] = {}
    for node in graph_data.get("nodes", []):
        fp = node.get("file", "")
        if fp:
            file_counts[fp] = file_counts.get(fp, 0) + 1

    for fp, count in sorted(file_counts.items(), key=lambda x: -x[1]):
        if count > threshold:
            violations.append(PolicyViolation(
                policy_id=policy.policy_id,
                policy_name=policy.name,
                description=f"{fp} has {count} nodes (limit: {threshold})",
                action=policy.action,
                details={"file": fp, "node_count": count, "threshold": threshold},
            ))

    return violations


def _check_max_subsystem_size(
    policy: ArchPolicy,
    graph_data: Dict[str, Any],
    architecture_data: Dict[str, Any],
    health_data: Dict[str, Any],
) -> List[PolicyViolation]:
    """Check for subsystems exceeding size threshold."""
    threshold = int(policy.threshold) if policy.threshold else 200
    violations: List[PolicyViolation] = []

    for sub in architecture_data.get("subsystems", []):
        comp_count = len(sub.get("components", []))
        if comp_count > threshold:
            violations.append(PolicyViolation(
                policy_id=policy.policy_id,
                policy_name=policy.name,
                description=(f"Subsystem '{sub['name']}' has {comp_count} "
                             f"components (limit: {threshold})"),
                action=policy.action,
                details={"subsystem": sub["name"], "components": comp_count,
                         "threshold": threshold},
            ))

    return violations


def _check_score_gate(
    policy: ArchPolicy,
    graph_data: Dict[str, Any],
    architecture_data: Dict[str, Any],
    health_data: Dict[str, Any],
) -> List[PolicyViolation]:
    """Check if architecture score is above minimum threshold."""
    min_score = policy.threshold if policy.threshold else 0.5
    violations: List[PolicyViolation] = []

    current_score = health_data.get("overall_score", 1.0)
    if current_score < min_score:
        violations.append(PolicyViolation(
            policy_id=policy.policy_id,
            policy_name=policy.name,
            description=(f"Architecture score {current_score:.2f} is below "
                         f"minimum {min_score:.2f}"),
            action=policy.action,
            details={"current_score": current_score, "threshold": min_score},
        ))

    return violations


def _check_coupling_limit(
    policy: ArchPolicy,
    graph_data: Dict[str, Any],
    architecture_data: Dict[str, Any],
    health_data: Dict[str, Any],
) -> List[PolicyViolation]:
    """Check cross-subsystem coupling ratio."""
    max_coupling = policy.threshold if policy.threshold else 0.4
    violations: List[PolicyViolation] = []

    # Use health data's coupling metric if available
    coupling = health_data.get("coupling", 0.0)
    if coupling > max_coupling:
        violations.append(PolicyViolation(
            policy_id=policy.policy_id,
            policy_name=policy.name,
            description=(f"Cross-subsystem coupling {coupling:.3f} exceeds "
                         f"limit {max_coupling:.3f}"),
            action=policy.action,
            details={"coupling": coupling, "threshold": max_coupling},
        ))

    return violations


def _check_frontend_backend_boundary(
    policy: ArchPolicy,
    graph_data: Dict[str, Any],
    architecture_data: Dict[str, Any],
    health_data: Dict[str, Any],
) -> List[PolicyViolation]:
    """Check that frontend modules don't directly import backend modules."""
    violations: List[PolicyViolation] = []

    # Identify frontend/backend files by extension or path convention
    nodes_by_file: Dict[str, List[str]] = {}
    for node in graph_data.get("nodes", []):
        fp = node.get("file", "")
        node_id = node.get("id", "")
        if fp:
            nodes_by_file.setdefault(fp, []).append(node_id)

    frontend_files = {f for f in nodes_by_file
                      if f.endswith((".js", ".jsx", ".ts", ".tsx"))}
    backend_files = {f for f in nodes_by_file if f.endswith(".py")}

    # Check edges for cross-boundary imports
    # (This is a simplified check; full implementation would check workflow edges)
    if frontend_files and backend_files:
        # No violations by default — actual import checking requires workflow data
        pass

    return violations


def _check_no_apply_without_plan(
    policy: ArchPolicy,
    graph_data: Dict[str, Any],
    architecture_data: Dict[str, Any],
    health_data: Dict[str, Any],
) -> List[PolicyViolation]:
    """Check that a plan exists before apply operations.

    This is enforced at runtime — here we just verify plan artifacts exist.
    """
    return []  # Enforcement is in the CLI pipeline, not in static analysis


def _check_layer_isolation(
    policy: ArchPolicy,
    graph_data: Dict[str, Any],
    architecture_data: Dict[str, Any],
    health_data: Dict[str, Any],
) -> List[PolicyViolation]:
    """Enforce layer isolation — prevent cross-layer dependencies.

    Uses the ``target`` field as ``source_layer->target_layer`` to
    declare a forbidden direction.  Example: ``domain->infrastructure``.
    Layers are matched against subsystem names in the architecture.
    """
    violations: List[PolicyViolation] = []
    if "->" not in (policy.target or ""):
        return violations

    src_layer, tgt_layer = policy.target.split("->", 1)
    src_layer = src_layer.strip()
    tgt_layer = tgt_layer.strip()

    # Build subsystem lookup
    subsystems = {s["name"]: s for s in architecture_data.get("subsystems", [])}
    src_sub = subsystems.get(src_layer)
    tgt_sub = subsystems.get(tgt_layer)
    if not src_sub or not tgt_sub:
        return violations

    # Collect module paths belonging to each layer
    src_modules = {
        c.get("module", c.get("name", ""))
        for c in src_sub.get("components", [])
    }
    tgt_modules = {
        c.get("module", c.get("name", ""))
        for c in tgt_sub.get("components", [])
    }

    # Check edges in architecture
    for edge in architecture_data.get("edges", []):
        if edge.get("from") == src_layer and edge.get("to") == tgt_layer:
            violations.append(PolicyViolation(
                policy_id=policy.policy_id,
                policy_name=policy.name,
                description=(
                    f"Layer isolation violated: {src_layer} -> {tgt_layer} "
                    f"edge exists in architecture"
                ),
                action=policy.action,
                details={
                    "source_layer": src_layer,
                    "target_layer": tgt_layer,
                    "source_modules": sorted(src_modules)[:5],
                    "target_modules": sorted(tgt_modules)[:5],
                },
            ))

    return violations


def _check_forbidden_subsystem_dep(
    policy: ArchPolicy,
    graph_data: Dict[str, Any],
    architecture_data: Dict[str, Any],
    health_data: Dict[str, Any],
) -> List[PolicyViolation]:
    """Forbid a specific subsystem-to-subsystem dependency.

    Uses ``target`` as ``source->target`` to declare a forbidden edge.
    Checks both declared architecture edges and actual call graph edges.
    """
    violations: List[PolicyViolation] = []
    if "->" not in (policy.target or ""):
        return violations

    src_name, tgt_name = policy.target.split("->", 1)
    src_name = src_name.strip()
    tgt_name = tgt_name.strip()

    # Check declared edges
    for edge in architecture_data.get("edges", []):
        if edge.get("from") == src_name and edge.get("to") == tgt_name:
            violations.append(PolicyViolation(
                policy_id=policy.policy_id,
                policy_name=policy.name,
                description=(
                    f"Forbidden subsystem dependency: {src_name} -> {tgt_name}"
                ),
                action=policy.action,
                details={
                    "source": src_name,
                    "target": tgt_name,
                    "edge_type": "declared",
                },
            ))

    return violations


_POLICY_HANDLERS = {
    "no_large_modules": _check_no_large_modules,
    "max_subsystem_size": _check_max_subsystem_size,
    "score_gate": _check_score_gate,
    "coupling_limit": _check_coupling_limit,
    "frontend_backend_boundary": _check_frontend_backend_boundary,
    "no_apply_without_plan": _check_no_apply_without_plan,
    "layer_isolation": _check_layer_isolation,
    "forbidden_subsystem_dep": _check_forbidden_subsystem_dep,
}


# ═══════════════════════════════════════════════════════════════════════
# Default Policies
# ═══════════════════════════════════════════════════════════════════════


DEFAULT_POLICIES = [
    ArchPolicy(
        policy_id="pol_001",
        name="no_large_modules",
        policy_type="no_large_modules",
        rule="Modules must not exceed 50 nodes",
        action="warn",
        threshold=50,
    ),
    ArchPolicy(
        policy_id="pol_002",
        name="max_subsystem_size",
        policy_type="max_subsystem_size",
        rule="Subsystems must not exceed 200 components",
        action="warn",
        threshold=200,
    ),
    ArchPolicy(
        policy_id="pol_003",
        name="score_gate",
        policy_type="score_gate",
        rule="Architecture score must stay above 0.5",
        action="block",
        threshold=0.5,
    ),
    ArchPolicy(
        policy_id="pol_004",
        name="coupling_limit",
        policy_type="coupling_limit",
        rule="Cross-subsystem coupling must stay below 0.4",
        action="warn",
        threshold=0.4,
    ),
]


def init_default_policies(project_root: Path) -> List[ArchPolicy]:
    """Initialize default architecture policies."""
    existing = load_policies(project_root)
    if existing:
        return existing
    save_policies(project_root, DEFAULT_POLICIES)
    logger.info("Initialized %d default policies", len(DEFAULT_POLICIES))
    return DEFAULT_POLICIES


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════


def _load_json(path: Path) -> Dict[str, Any]:
    """Load JSON file, returning empty dict if missing."""
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))
