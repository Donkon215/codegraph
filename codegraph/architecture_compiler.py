"""codegraph.architecture_compiler — Intent-to-architecture compiler.

Converts high-level architecture intents (e.g. "add REST API", "add caching
layer") into concrete architecture changes: new subsystems, components,
edges, and constraints.

The compiler bridges human intent and machine-readable architecture:

    intent  →  ArchitecturePlan  →  target_architecture changes

It determines:
  - Which subsystem the intent belongs to
  - What components need to be created
  - What dependencies are required
  - What constraints must be respected
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from codegraph.arch_schema import (
    ArchComponent,
    ArchConstraint,
    ArchEdge,
    SubsystemDef,
    SystemArchitecture,
)
from codegraph.logging_config import get_logger
from codegraph.target_architecture import TargetEdge, TargetNode, TargetWorkflow

logger = get_logger("architecture_compiler")

PLAN_DIR = "planning"
PLAN_FILE = "architecture_plan.json"


# ── Compiled Change ────────────────────────────────────────────────────


@dataclass
class CompiledChange:
    """A single compiled architecture change."""

    change_type: str  # "add_subsystem", "add_component", "add_edge",
    #                   "add_constraint", "add_module"
    subsystem: str = ""
    component_name: str = ""
    module_path: str = ""
    description: str = ""
    target_subsystem: str = ""  # for edges
    constraint_type: str = ""  # "forbidden", "required"
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"change_type": self.change_type}
        for attr in ("subsystem", "component_name", "module_path",
                      "description", "target_subsystem", "constraint_type",
                      "reason"):
            val = getattr(self, attr)
            if val:
                d[attr] = val
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> CompiledChange:
        return cls(
            change_type=d["change_type"],
            subsystem=d.get("subsystem", ""),
            component_name=d.get("component_name", ""),
            module_path=d.get("module_path", ""),
            description=d.get("description", ""),
            target_subsystem=d.get("target_subsystem", ""),
            constraint_type=d.get("constraint_type", ""),
            reason=d.get("reason", ""),
        )


# ── Architecture Plan ──────────────────────────────────────────────────


@dataclass
class ArchitecturePlan:
    """A compiled plan of architecture changes from an intent.

    Produced by compile_intent() and consumed by apply_plan() to
    modify the SystemArchitecture and generate a TargetWorkflow.
    """

    intent: str
    changes: List[CompiledChange] = field(default_factory=list)
    target_edges: List[TargetEdge] = field(default_factory=list)
    target_nodes: List[TargetNode] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.changes or self.target_edges or self.target_nodes)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent": self.intent,
            "summary": {
                "changes": len(self.changes),
                "target_edges": len(self.target_edges),
                "target_nodes": len(self.target_nodes),
                "warnings": len(self.warnings),
            },
            "changes": [c.to_dict() for c in self.changes],
            "target_edges": [e.to_dict() for e in self.target_edges],
            "target_nodes": [n.to_dict() for n in self.target_nodes],
            "warnings": self.warnings,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> ArchitecturePlan:
        changes = [CompiledChange.from_dict(c) for c in d.get("changes", [])]
        target_edges = [TargetEdge.from_dict(e)
                        for e in d.get("target_edges", [])]
        target_nodes = [TargetNode.from_dict(n)
                        for n in d.get("target_nodes", [])]
        return cls(
            intent=d.get("intent", ""),
            changes=changes,
            target_edges=target_edges,
            target_nodes=target_nodes,
            warnings=d.get("warnings", []),
        )

    def save(self, project_root: Path) -> Path:
        path = project_root / ".codegraph" / PLAN_DIR / PLAN_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("Saved architecture plan → %s", path)
        return path

    @classmethod
    def load(cls, project_root: Path) -> Optional[ArchitecturePlan]:
        path = project_root / ".codegraph" / PLAN_DIR / PLAN_FILE
        if not path.exists():
            return None
        text = path.read_text(encoding="utf-8")
        return cls.from_dict(json.loads(text))

    def format(self) -> str:
        lines = [f"Architecture Plan: {self.intent}"]
        lines.append(f"  Changes: {len(self.changes)}")
        lines.append(f"  Target edges: {len(self.target_edges)}")
        lines.append(f"  Target nodes: {len(self.target_nodes)}")
        if self.changes:
            lines.append("\nChanges:")
            for c in self.changes:
                lines.append(f"  [{c.change_type}] {c.subsystem}"
                             f"{' → ' + c.target_subsystem if c.target_subsystem else ''}"
                             f" {c.component_name or c.module_path or ''}"
                             f" — {c.reason or c.description}")
        if self.warnings:
            lines.append("\nWarnings:")
            for w in self.warnings:
                lines.append(f"  ⚠ {w}")
        return "\n".join(lines)


# ── Compile Intent ─────────────────────────────────────────────────────


# Subsystem intent keywords — maps keywords in intent text to likely
# subsystem names and typical dependency targets.
_INTENT_PATTERNS: Dict[str, Dict[str, Any]] = {
    "api": {
        "subsystem": "api",
        "description": "REST/HTTP API server layer",
        "depends_on": ["core_engine", "query", "models"],
        "modules": ["api/server.py", "api/routes.py"],
    },
    "graphql": {
        "subsystem": "api",
        "description": "GraphQL API layer",
        "depends_on": ["core_engine", "query", "models"],
        "modules": ["api/graphql.py"],
    },
    "cache": {
        "subsystem": "infrastructure",
        "description": "Caching layer for performance",
        "depends_on": ["infrastructure"],
        "modules": ["codegraph/cache.py"],
    },
    "database": {
        "subsystem": "infrastructure",
        "description": "Database access layer",
        "depends_on": ["models", "infrastructure"],
        "modules": ["codegraph/database.py"],
    },
    "auth": {
        "subsystem": "security",
        "description": "Authentication and authorization",
        "depends_on": ["infrastructure", "models"],
        "modules": ["security/auth.py"],
    },
    "test": {
        "subsystem": "testing",
        "description": "Testing infrastructure",
        "depends_on": ["core_engine", "models"],
        "modules": ["tests/helpers.py"],
    },
    "plugin": {
        "subsystem": "plugins",
        "description": "Plugin system for extensibility",
        "depends_on": ["core_engine", "infrastructure"],
        "modules": ["plugins/loader.py", "plugins/registry.py"],
    },
    "export": {
        "subsystem": "infrastructure",
        "description": "Export/reporting functionality",
        "depends_on": ["core_engine", "query", "models"],
        "modules": ["codegraph/export.py"],
    },
}


def compile_intent(
    intent: str,
    architecture: SystemArchitecture,
    *,
    auto_constraints: bool = True,
) -> ArchitecturePlan:
    """Compile a high-level architecture intent into a concrete plan.

    Analyzes the intent text, determines what architecture changes are
    needed, and produces an ArchitecturePlan with changes, target edges,
    and target nodes.

    Args:
        intent: Human-readable architecture intent (e.g. "add REST API").
        architecture: Current system architecture.
        auto_constraints: Whether to auto-generate constraints for new
            subsystems (e.g. models must not import new subsystem).
    """
    plan = ArchitecturePlan(intent=intent)
    intent_lower = intent.lower()
    existing_subsystems = set(architecture.subsystem_names)

    # Detect which patterns match
    matched = _match_intent_patterns(intent_lower)
    if not matched:
        # Generic: create a new subsystem from the intent
        subsystem_name = _extract_subsystem_name(intent_lower)
        if subsystem_name and subsystem_name not in existing_subsystems:
            plan.changes.append(CompiledChange(
                change_type="add_subsystem",
                subsystem=subsystem_name,
                description=f"New subsystem from intent: {intent}",
                reason=intent,
            ))
            # Default dependency on models + infrastructure
            for dep in ["models", "infrastructure"]:
                if dep in existing_subsystems:
                    plan.changes.append(CompiledChange(
                        change_type="add_edge",
                        subsystem=subsystem_name,
                        target_subsystem=dep,
                        reason=f"{subsystem_name} depends on {dep}",
                    ))
            if auto_constraints:
                _add_default_constraints(plan, subsystem_name,
                                         existing_subsystems)
        else:
            plan.warnings.append(
                f"Could not determine subsystem from intent: {intent}"
            )
        return plan

    # Apply matched patterns
    for pattern_name, pattern_info in matched.items():
        sub_name = pattern_info["subsystem"]

        if sub_name not in existing_subsystems:
            # Create new subsystem
            plan.changes.append(CompiledChange(
                change_type="add_subsystem",
                subsystem=sub_name,
                description=pattern_info.get("description", ""),
                reason=intent,
            ))

            # Add dependency edges
            for dep in pattern_info.get("depends_on", []):
                if dep in existing_subsystems:
                    plan.changes.append(CompiledChange(
                        change_type="add_edge",
                        subsystem=sub_name,
                        target_subsystem=dep,
                        reason=f"{sub_name} depends on {dep}",
                    ))

            if auto_constraints:
                _add_default_constraints(plan, sub_name, existing_subsystems)

        # Add modules/components
        for mod_path in pattern_info.get("modules", []):
            comp_name = Path(mod_path).stem
            plan.changes.append(CompiledChange(
                change_type="add_component",
                subsystem=sub_name,
                component_name=comp_name,
                module_path=mod_path,
                description=f"Component for {pattern_name}",
                reason=intent,
            ))

            # Create target node for the module
            plan.target_nodes.append(TargetNode(
                node_id=mod_path.replace(".py", "").replace("/", "."),
                module=mod_path,
                subsystem=sub_name,
                intent=pattern_info.get("description", ""),
                reason=intent,
            ))

    return plan


def apply_plan(
    plan: ArchitecturePlan,
    architecture: SystemArchitecture,
) -> SystemArchitecture:
    """Apply a compiled plan to an architecture definition.

    Modifies the architecture in-place and returns it.
    Only applies structural changes (subsystems, components, edges,
    constraints). Does NOT modify code files.
    """
    for change in plan.changes:
        if change.change_type == "add_subsystem":
            if not architecture.get_subsystem(change.subsystem):
                architecture.subsystems.append(SubsystemDef(
                    name=change.subsystem,
                    description=change.description,
                ))
                logger.info("Added subsystem: %s", change.subsystem)

        elif change.change_type == "add_component":
            sub = architecture.get_subsystem(change.subsystem)
            if sub:
                existing = {c.name for c in sub.components}
                if change.component_name not in existing:
                    sub.components.append(ArchComponent(
                        name=change.component_name,
                        module=change.module_path,
                        description=change.description,
                    ))
                    logger.info("Added component %s to %s",
                                change.component_name, change.subsystem)

        elif change.change_type == "add_edge":
            edge = ArchEdge(
                source=change.subsystem,
                target=change.target_subsystem,
            )
            # Avoid duplicates
            existing_edges = {(e.source, e.target) for e in architecture.edges}
            if (edge.source, edge.target) not in existing_edges:
                architecture.edges.append(edge)
                logger.info("Added edge: %s → %s",
                            change.subsystem, change.target_subsystem)

        elif change.change_type == "add_constraint":
            constraint = ArchConstraint(
                constraint_type=change.constraint_type,
                source=change.subsystem,
                target=change.target_subsystem,
                reason=change.reason,
            )
            architecture.constraints.append(constraint)
            logger.info("Added constraint: %s %s → %s",
                        change.constraint_type, change.subsystem,
                        change.target_subsystem)

    return architecture


def plan_to_target_workflow(
    plan: ArchitecturePlan,
    *,
    existing_target: Optional[TargetWorkflow] = None,
) -> TargetWorkflow:
    """Convert an architecture plan into target workflow additions.

    If an existing target workflow is provided, the plan's edges and
    nodes are appended to it. Otherwise a new one is created.
    """
    target = existing_target or TargetWorkflow(
        description=f"Target from intent: {plan.intent}",
    )
    for edge in plan.target_edges:
        target.edges.append(edge)
    for node in plan.target_nodes:
        target.nodes.append(node)
    return target


# ── Internal Helpers ───────────────────────────────────────────────────


def _match_intent_patterns(
    intent_lower: str,
) -> Dict[str, Dict[str, Any]]:
    """Match intent text against known patterns."""
    matched: Dict[str, Dict[str, Any]] = {}
    for keyword, info in _INTENT_PATTERNS.items():
        if re.search(r"\b" + re.escape(keyword) + r"\b", intent_lower):
            matched[keyword] = info
    return matched


def _extract_subsystem_name(intent_lower: str) -> str:
    """Extract a subsystem name from freeform intent text."""
    # Try "add X", "create X", "new X"
    m = re.search(r"(?:add|create|new|introduce)\s+(\w+)", intent_lower)
    if m:
        name = m.group(1)
        # Skip generic words
        if name not in {"a", "an", "the", "new", "module", "file", "function"}:
            return name.replace("-", "_")
    return ""


def _add_default_constraints(
    plan: ArchitecturePlan,
    subsystem_name: str,
    existing_subsystems: Set[str],
) -> None:
    """Add default architectural constraints for a new subsystem."""
    # Models must not depend on the new subsystem
    if "models" in existing_subsystems:
        plan.changes.append(CompiledChange(
            change_type="add_constraint",
            subsystem="models",
            target_subsystem=subsystem_name,
            constraint_type="forbidden",
            reason=f"Models must not depend on {subsystem_name}.",
        ))
    # Infrastructure must not depend on the new subsystem
    # (unless the new subsystem IS infrastructure)
    if ("infrastructure" in existing_subsystems
            and subsystem_name != "infrastructure"):
        plan.changes.append(CompiledChange(
            change_type="add_constraint",
            subsystem="infrastructure",
            target_subsystem=subsystem_name,
            constraint_type="forbidden",
            reason=f"Infrastructure must not depend on {subsystem_name}.",
        ))


# ── Evolution Proposal Processing ──────────────────────────────────────


def process_evolution_proposals(
    project_root: Path,
    *,
    auto_accept_safe: bool = False,
) -> List[Dict[str, Any]]:
    """Read pending evolution proposals and validate them.

    The compiler is the sole authority for accepting or rejecting
    proposals from the evolution engine.

    Args:
        project_root: Project root directory.
        auto_accept_safe: If True, auto-accept proposals with ``safe`` tier.

    Returns:
        List of dicts describing each proposal decision.
    """
    from codegraph.evolution_proposals import (
        load_proposals,
        save_proposals,
        STATUS_PENDING,
    )

    store = load_proposals(project_root)
    pending = store.pending()
    if not pending:
        return []

    arch = SystemArchitecture.load(project_root)
    decisions: List[Dict[str, Any]] = []

    for proposal in pending:
        decision: Dict[str, Any] = {
            "proposal_id": proposal.proposal_id,
            "strategy": proposal.strategy,
        }

        # Validate: reject if score would degrade
        if proposal.predicted_score_delta < -0.02:
            store.reject(
                proposal.proposal_id,
                f"Predicted score degradation: {proposal.predicted_score_delta:+.3f}",
            )
            decision["action"] = "rejected"
            decision["reason"] = "score_degradation"
            decisions.append(decision)
            continue

        # Validate: block dangerous tier
        if proposal.safety_tier == "dangerous":
            store.reject(
                proposal.proposal_id,
                "Dangerous-tier mutation requires human approval",
            )
            decision["action"] = "rejected"
            decision["reason"] = "dangerous_tier"
            decisions.append(decision)
            continue

        # Auto-accept safe tier if configured
        if auto_accept_safe and proposal.safety_tier == "safe":
            store.accept(proposal.proposal_id)
            decision["action"] = "accepted"
            decision["reason"] = "auto_safe"
            decisions.append(decision)
            continue

        # Otherwise leave pending for human review
        decision["action"] = "pending"
        decision["reason"] = "awaiting_review"
        decisions.append(decision)

    save_proposals(project_root, store)
    logger.info("Processed %d proposals: %s",
                len(decisions),
                {d["action"] for d in decisions})
    return decisions
