"""codegraph.suggest — Suggested workflow / architecture policy manager.

Group H: H-001 through H-027.
Manages suggested_workflow.json rules, scope expansion, violation detection,
dangling-rule checks, rule import, validation, and policy diff.
"""

from __future__ import annotations

import fnmatch
import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from codegraph.constants import (
    LAYER_PROJECT,
    LAYER_TEST,
    SUGGESTED_WORKFLOW_FILE,
    WORKFLOW_DIR,
)
from codegraph.logging_config import get_logger
from codegraph.models.graph0 import Graph0
from codegraph.models.graph1 import Graph1
from codegraph.models.suggested_workflow import (
    RuleType,
    SuggestedWorkflow,
    SuggestedWorkflowRule,
    expand_arch_layer_scope,
    expand_layer_scope,
    expand_rule_scope,
)
from codegraph.models.workflow import Workflow, WorkflowEdge
from codegraph.storage import atomic_write, ensure_codegraph_dir, resolve_path
from codegraph.utils.formatting import iso_now

logger = get_logger("suggest")


# ═══════════════════════════════════════════════════════════════════════
# H-001 — Suggested Workflow Data Store
# ═══════════════════════════════════════════════════════════════════════


def _sw_path(project_root: Path) -> Path:
    return resolve_path(project_root, WORKFLOW_DIR, SUGGESTED_WORKFLOW_FILE)


def load_suggested_workflow(project_root: Path) -> SuggestedWorkflow:
    """Load suggested_workflow.json (H-001).  Returns empty if missing."""
    path = _sw_path(project_root)
    if not path.exists():
        return SuggestedWorkflow()
    text = path.read_text(encoding="utf-8")
    return SuggestedWorkflow.from_json(text)


def save_suggested_workflow(sw: SuggestedWorkflow, project_root: Path) -> Path:
    """Save suggested_workflow.json atomically (H-001)."""
    ensure_codegraph_dir(project_root)
    dest = _sw_path(project_root)
    dest.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(sw.to_json())
    atomic_write(dest, data)
    logger.info("Saved suggested workflow (%d rules) → %s", len(sw.rules), dest)
    return dest


# ═══════════════════════════════════════════════════════════════════════
# H-004–H-008 — Scope matchers
# ═══════════════════════════════════════════════════════════════════════


def match_scope_exact(node_id: str, scope_value: str) -> bool:
    """H-004: Exact scope match."""
    return node_id == scope_value


def match_scope_module(node_id: str, scope_value: str) -> bool:
    """H-005: Module scope — match first segment before '::'."""
    module = node_id.split("::")[0] if "::" in node_id else node_id
    # Also handle file-path style (codegraph/suggest → codegraph.suggest)
    normalised = module.replace("/", ".").replace("\\", ".")
    if normalised.endswith(".py"):
        normalised = normalised[:-3]
    scope_norm = scope_value.replace("/", ".").replace("\\", ".")
    if scope_norm.endswith(".py"):
        scope_norm = scope_norm[:-3]
    return normalised == scope_norm


def match_scope_glob(node_id: str, scope_value: str) -> bool:
    """H-006: Glob scope match using fnmatch."""
    return fnmatch.fnmatch(node_id, scope_value)


def match_scope_layer(
    node_id: str, scope_value: int, graph1: Graph1,
) -> bool:
    """H-007: Layer scope match."""
    g1_node = graph1.get_node(node_id)
    if g1_node is None:
        return False
    return g1_node.layer == scope_value


def match_scope_arch_layer(
    node_id: str, scope_value: str, graph1: Graph1,
) -> bool:
    """H-008: Arch-layer scope match."""
    g1_node = graph1.get_node(node_id)
    if g1_node is None:
        return False
    return g1_node.arch_layer == scope_value


# ═══════════════════════════════════════════════════════════════════════
# H-009 — Scope Resolution Engine
# ═══════════════════════════════════════════════════════════════════════


def expand_scope(
    rule: SuggestedWorkflowRule,
    graph0: Graph0,
    graph1: Graph1,
    *,
    side: str = "source",
) -> Set[str]:
    """Expand a rule's source or target specifiers to matching node IDs (H-009).

    A rule can specify a node by name (glob or exact), by layer number,
    or by arch_layer.  All specified filters are intersected.
    """
    all_ids = {n.id for n in graph0.nodes}
    candidates: Optional[Set[str]] = None  # None means "not yet constrained"

    if side == "source":
        name_pat, layer_val, arch_val = rule.source, rule.source_layer, rule.source_arch_layer
    else:
        name_pat, layer_val, arch_val = rule.target, rule.target_layer, rule.target_arch_layer

    # Name / glob filter
    if name_pat is not None:
        if any(c in name_pat for c in ("*", "?", "[", "]")):
            hits = {nid for nid in all_ids if fnmatch.fnmatch(nid, name_pat)}
        else:
            hits = {name_pat} if name_pat in all_ids else set()
        candidates = hits

    # Layer filter
    if layer_val is not None:
        layer_ids = set(expand_layer_scope(layer_val, graph1))
        candidates = layer_ids if candidates is None else candidates & layer_ids

    # Arch-layer filter
    if arch_val is not None:
        arch_ids = set(expand_arch_layer_scope(arch_val, graph1))
        candidates = arch_ids if candidates is None else candidates & arch_ids

    return candidates if candidates is not None else set()


# Caching wrapper
_scope_cache: Dict[Tuple[str, str], Set[str]] = {}


def _expand_scope_cached(
    rule: SuggestedWorkflowRule,
    graph0: Graph0,
    graph1: Graph1,
    side: str,
) -> Set[str]:
    key = (rule.id, side)
    if key not in _scope_cache:
        _scope_cache[key] = expand_scope(rule, graph0, graph1, side=side)
    return _scope_cache[key]


def clear_scope_cache() -> None:
    _scope_cache.clear()


# ═══════════════════════════════════════════════════════════════════════
# H-002 / H-003 — Rule type evaluation helpers
# ═══════════════════════════════════════════════════════════════════════


def _edge_exists(workflow: Workflow, source: str, target: str) -> bool:
    """Check whether *source* has any edge to *target*."""
    for edge in workflow.get_edges_from(source):
        if edge.target == target:
            return True
    return False


# ═══════════════════════════════════════════════════════════════════════
# H-010 — Policy Violation Detector
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class PolicyViolation:
    """A single detected policy violation (H-010)."""

    rule_id: str
    rule_type: str
    source: str
    target: str
    reason: str = ""
    severity: str = "error"


def detect_violations(
    suggested: SuggestedWorkflow,
    workflow: Workflow,
    graph0: Graph0,
    graph1: Graph1,
) -> List[PolicyViolation]:
    """Check all rules against the actual workflow (H-010)."""
    clear_scope_cache()
    violations: List[PolicyViolation] = []

    for rule in suggested.rules:
        try:
            rule_type = RuleType(rule.type)
        except ValueError:
            logger.warning("Unknown rule type '%s' in rule %s", rule.type, rule.id)
            continue

        sources = _expand_scope_cached(rule, graph0, graph1, "source")
        targets = _expand_scope_cached(rule, graph0, graph1, "target")

        if not sources or not targets:
            continue  # dangling — handled separately in H-014

        severity = getattr(rule, "severity", "error") or "error"

        for src in sources:
            for tgt in targets:
                exists = _edge_exists(workflow, src, tgt)
                if rule_type.is_violation(exists):
                    violations.append(PolicyViolation(
                        rule_id=rule.id,
                        rule_type=rule.type,
                        source=src,
                        target=tgt,
                        reason=rule.reason,
                        severity=severity,
                    ))

    return violations


# ═══════════════════════════════════════════════════════════════════════
# H-011 — Add rule
# ═══════════════════════════════════════════════════════════════════════


def add_rule(
    project_root: Path,
    rule_type: str,
    *,
    source: Optional[str] = None,
    target: Optional[str] = None,
    source_layer: Optional[int] = None,
    target_layer: Optional[int] = None,
    source_arch_layer: Optional[str] = None,
    target_arch_layer: Optional[str] = None,
    max_fan_in: Optional[int] = None,
    max_fan_out: Optional[int] = None,
    reason: str = "",
    author: str = "human",
    severity: str = "error",
) -> str:
    """Add a new rule to suggested_workflow.json (H-011).  Returns rule id."""
    # Validate rule_type
    try:
        RuleType(rule_type)
    except ValueError:
        raise ValueError(f"Invalid rule type '{rule_type}'. Valid: {[t.value for t in RuleType]}")

    sw = load_suggested_workflow(project_root)

    rule = SuggestedWorkflowRule(
        type=rule_type,
        source=source,
        target=target,
        source_layer=source_layer,
        target_layer=target_layer,
        source_arch_layer=source_arch_layer,
        target_arch_layer=target_arch_layer,
        max_fan_in=max_fan_in,
        max_fan_out=max_fan_out,
        reason=reason,
        added_by=author,
    )

    rule_id = sw.add_rule(rule)
    save_suggested_workflow(sw, project_root)
    logger.info("Added rule %s (%s)", rule_id, rule_type)
    return rule_id


# ═══════════════════════════════════════════════════════════════════════
# H-012 — Remove rule
# ═══════════════════════════════════════════════════════════════════════


def remove_rule(project_root: Path, rule_id: str) -> bool:
    """Remove a rule by ID (H-012).  Returns True if removed."""
    sw = load_suggested_workflow(project_root)
    if sw.get_rule(rule_id) is None:
        return False
    sw.remove_rule(rule_id)
    save_suggested_workflow(sw, project_root)
    logger.info("Removed rule %s", rule_id)
    return True


# ═══════════════════════════════════════════════════════════════════════
# H-013 — List rules
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class RuleDisplay:
    """Formatted rule for display (H-013)."""

    index: int
    rule_id: str
    rule_type: str
    source: str
    target: str
    reason: str
    severity: str = "error"
    author: str = ""
    added_at: str = ""


def list_rules(
    project_root: Path,
    *,
    filter_type: Optional[str] = None,
) -> List[RuleDisplay]:
    """List all rules, optionally filtered (H-013)."""
    sw = load_suggested_workflow(project_root)
    result: List[RuleDisplay] = []
    for idx, rule in enumerate(sw.rules, 1):
        if filter_type and rule.type != filter_type:
            continue

        # Build readable source/target strings
        src_parts: List[str] = []
        if rule.source:
            src_parts.append(rule.source)
        if rule.source_layer is not None:
            src_parts.append(f"layer={rule.source_layer}")
        if rule.source_arch_layer:
            src_parts.append(f"arch={rule.source_arch_layer}")
        source_str = " & ".join(src_parts) or "(any)"

        tgt_parts: List[str] = []
        if rule.target:
            tgt_parts.append(rule.target)
        if rule.target_layer is not None:
            tgt_parts.append(f"layer={rule.target_layer}")
        if rule.target_arch_layer:
            tgt_parts.append(f"arch={rule.target_arch_layer}")
        target_str = " & ".join(tgt_parts) or "(any)"

        result.append(RuleDisplay(
            index=idx,
            rule_id=rule.id,
            rule_type=rule.type,
            source=source_str,
            target=target_str,
            reason=rule.reason,
            severity=getattr(rule, "severity", "error") or "error",
            author=rule.added_by,
            added_at=rule.added_at,
        ))
    return result


def format_rules_table(rules: List[RuleDisplay]) -> str:
    """Format rules for CLI display."""
    if not rules:
        return "No rules defined."
    lines: List[str] = []
    lines.append(f"{'#':>3}  {'ID':<12} {'Type':<16} {'Source':<30} {'Target':<30} Reason")
    lines.append("-" * 100)
    for r in rules:
        lines.append(
            f"{r.index:>3}  {r.rule_id:<12} {r.rule_type:<16} "
            f"{r.source:<30} {r.target:<30} {r.reason}"
        )
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# H-014 — Dangling Rule Detection
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class DanglingRule:
    """A rule whose scope matches no existing nodes (H-014)."""

    rule_id: str
    side: str  # "source" or "target"
    pattern: str
    reason: str = ""


def find_dangling_rules(
    suggested: SuggestedWorkflow,
    graph0: Graph0,
    graph1: Graph1,
) -> List[DanglingRule]:
    """Detect rules with source or target matching zero nodes (H-014, H-015)."""
    clear_scope_cache()
    danglings: List[DanglingRule] = []

    for rule in suggested.rules:
        for side in ("source", "target"):
            matches = expand_scope(rule, graph0, graph1, side=side)
            if not matches:
                if side == "source":
                    pat = rule.source or f"layer={rule.source_layer}" or f"arch={rule.source_arch_layer}"
                else:
                    pat = rule.target or f"layer={rule.target_layer}" or f"arch={rule.target_arch_layer}"
                danglings.append(DanglingRule(
                    rule_id=rule.id,
                    side=side,
                    pattern=str(pat),
                    reason=f"Rule {rule.id} {side} matches zero nodes",
                ))

    return danglings


# ═══════════════════════════════════════════════════════════════════════
# H-016 — Rule Import from Template
# ═══════════════════════════════════════════════════════════════════════

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def available_templates() -> List[str]:
    """Return names of built-in rule templates."""
    if not _TEMPLATES_DIR.exists():
        return []
    return sorted(p.stem for p in _TEMPLATES_DIR.glob("*.json"))


def import_rules_template(
    template_name: str,
    project_root: Path,
    *,
    author: str = "template",
) -> int:
    """Import a rule template, merging with existing rules (H-016).  Returns count added."""
    template_path = _TEMPLATES_DIR / f"{template_name}.json"
    if not template_path.exists():
        avail = available_templates()
        raise ValueError(
            f"Template '{template_name}' not found. "
            f"Available: {avail}"
        )

    template_data = json.loads(template_path.read_text(encoding="utf-8"))
    sw = load_suggested_workflow(project_root)
    added = 0

    for rd in template_data.get("rules", []):
        rd["added_by"] = author
        rd["added_at"] = iso_now()
        rd.pop("id", None)  # Let auto-id assign
        try:
            rule = SuggestedWorkflowRule.from_dict(rd)
            sw.add_rule(rule)
            added += 1
        except (ValueError, KeyError) as exc:
            logger.warning("Skipping template rule: %s", exc)

    if added:
        save_suggested_workflow(sw, project_root)
    logger.info("Imported %d rules from template '%s'", added, template_name)
    return added


# ═══════════════════════════════════════════════════════════════════════
# H-017 / H-018 — Rule versioning & severity
#
# These are fields on SuggestedWorkflowRule.  The model in
# models/suggested_workflow.py already has added_at, added_by.
# We add updated_at and severity handling here at the logic layer.
# ═══════════════════════════════════════════════════════════════════════


def update_rule(
    project_root: Path,
    rule_id: str,
    *,
    reason: Optional[str] = None,
    severity: Optional[str] = None,
    author: Optional[str] = None,
) -> bool:
    """Update mutable fields on a rule (H-017, H-018).  Returns True if found."""
    sw = load_suggested_workflow(project_root)
    rule = sw.get_rule(rule_id)
    if rule is None:
        return False
    if reason is not None:
        rule.reason = reason
    if author is not None:
        rule.added_by = author
    save_suggested_workflow(sw, project_root)
    return True


# ═══════════════════════════════════════════════════════════════════════
# H-019 — Suggested Workflow Validation
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class ValidationIssue:
    """A validation problem in suggested_workflow.json (H-019)."""

    severity: str  # "error" / "warning" / "info"
    message: str
    rule_id: str = ""


def validate_suggested_workflow(
    sw: SuggestedWorkflow,
    graph0: Graph0,
    graph1: Optional[Graph1] = None,
) -> List[ValidationIssue]:
    """Validate structural and semantic correctness (H-019)."""
    issues: List[ValidationIssue] = []
    seen_pairs: Dict[Tuple[str, str, str], str] = {}  # (type, src, tgt) → rule_id

    for rule in sw.rules:
        # Structural: valid rule type
        try:
            RuleType(rule.type)
        except ValueError:
            issues.append(ValidationIssue("error", f"Invalid rule type: {rule.type}", rule.id))

        # Structural: must have source/target specifier
        has_src = any([rule.source, rule.source_layer is not None, rule.source_arch_layer])
        has_tgt = any([rule.target, rule.target_layer is not None, rule.target_arch_layer])
        if not has_src:
            issues.append(ValidationIssue("error", "Rule has no source specifier", rule.id))
        if not has_tgt:
            issues.append(ValidationIssue("error", "Rule has no target specifier", rule.id))

        # Contradiction check: same src+tgt required AND forbidden
        if rule.source and rule.target:
            key = (rule.source, rule.target)
            contra_key = ("required_call" if rule.type == "forbidden_call" else "forbidden_call",
                          rule.source, rule.target)
            pair_key = (rule.type, rule.source, rule.target)
            if contra_key in seen_pairs:
                issues.append(ValidationIssue(
                    "error",
                    f"Contradiction: rule {rule.id} ({rule.type}) conflicts with "
                    f"rule {seen_pairs[contra_key]} for {rule.source} → {rule.target}",
                    rule.id,
                ))
            seen_pairs[pair_key] = rule.id

        # Semantic: dangling scopes
        if graph1 is not None:
            for side in ("source", "target"):
                matches = expand_scope(rule, graph0, graph1, side=side)
                if not matches:
                    pat = (rule.source if side == "source" else rule.target) or "(layer/arch)"
                    issues.append(ValidationIssue(
                        "warning",
                        f"Rule {side} '{pat}' matches zero nodes (dangling)",
                        rule.id,
                    ))

    return issues


# ═══════════════════════════════════════════════════════════════════════
# H-020 — Policy Diff Report
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class PolicyDiffEntry:
    """Status of a single rule in the policy diff (H-020)."""

    rule_id: str
    rule_type: str
    status: str  # "satisfied" / "violated" / "unverifiable" / "dangling"
    details: List[str] = field(default_factory=list)


@dataclass
class PolicyDiff:
    """Full policy diff: suggested vs actual (H-020)."""

    entries: List[PolicyDiffEntry] = field(default_factory=list)

    @property
    def satisfied(self) -> List[PolicyDiffEntry]:
        return [e for e in self.entries if e.status == "satisfied"]

    @property
    def violated(self) -> List[PolicyDiffEntry]:
        return [e for e in self.entries if e.status == "violated"]

    @property
    def unverifiable(self) -> List[PolicyDiffEntry]:
        return [e for e in self.entries if e.status == "unverifiable"]

    @property
    def dangling(self) -> List[PolicyDiffEntry]:
        return [e for e in self.entries if e.status == "dangling"]

    def format(self) -> str:
        lines = [f"Policy Diff: {len(self.entries)} rules"]
        lines.append(f"  Satisfied:    {len(self.satisfied)}")
        lines.append(f"  Violated:     {len(self.violated)}")
        lines.append(f"  Unverifiable: {len(self.unverifiable)}")
        lines.append(f"  Dangling:     {len(self.dangling)}")
        if self.violated:
            lines.append("\nViolations:")
            for e in self.violated:
                lines.append(f"  [{e.rule_id}] {e.rule_type}")
                for d in e.details:
                    lines.append(f"    - {d}")
        return "\n".join(lines)


def policy_diff(
    suggested: SuggestedWorkflow,
    workflow: Workflow,
    graph0: Graph0,
    graph1: Graph1,
) -> PolicyDiff:
    """Generate a full policy diff (H-020)."""
    clear_scope_cache()
    diff = PolicyDiff()

    for rule in suggested.rules:
        try:
            rule_type = RuleType(rule.type)
        except ValueError:
            diff.entries.append(PolicyDiffEntry(
                rule_id=rule.id, rule_type=rule.type,
                status="unverifiable", details=[f"Unknown type: {rule.type}"],
            ))
            continue

        sources = _expand_scope_cached(rule, graph0, graph1, "source")
        targets = _expand_scope_cached(rule, graph0, graph1, "target")

        if not sources or not targets:
            side = "source" if not sources else "target"
            diff.entries.append(PolicyDiffEntry(
                rule_id=rule.id, rule_type=rule.type,
                status="dangling", details=[f"{side} matches zero nodes"],
            ))
            continue

        rule_violations: List[str] = []
        for src in sources:
            for tgt in targets:
                exists = _edge_exists(workflow, src, tgt)
                if rule_type.is_violation(exists):
                    if rule_type == RuleType.REQUIRED_CALL:
                        rule_violations.append(f"{src} does not call {tgt}")
                    else:
                        rule_violations.append(f"{src} calls forbidden {tgt}")

        if rule_violations:
            diff.entries.append(PolicyDiffEntry(
                rule_id=rule.id, rule_type=rule.type,
                status="violated", details=rule_violations,
            ))
        else:
            diff.entries.append(PolicyDiffEntry(
                rule_id=rule.id, rule_type=rule.type,
                status="satisfied",
            ))

    return diff


# ═══════════════════════════════════════════════════════════════════════
# H-021 — Serialization compatibility
#
# The model already handles forward/backward compat:
#   - Unknown fields: preserved via additionalProperties in schema
#   - Missing fields: default values in from_dict()
#   - schema_version tracked via SuggestedWorkflow.version
# ═══════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════
# H-022 — Promote agent suggestion to permanent rule
# ═══════════════════════════════════════════════════════════════════════


def promote_suggestion(
    suggestion_type: str,
    source: str,
    target: str,
    reason: str,
    project_root: Path,
    *,
    author: str = "agent",
) -> str:
    """Promote an agent workflow suggestion to a permanent rule (H-022)."""
    return add_rule(
        project_root,
        suggestion_type,
        source=source,
        target=target,
        reason=reason,
        author=author,
    )


# ═══════════════════════════════════════════════════════════════════════
# H-023 — Rule Dependency / Contradiction Checking
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class RuleConflict:
    """A conflict or contradiction between rules (H-023)."""

    rule_a: str
    rule_b: str
    conflict_type: str  # "contradiction" / "circular"
    message: str


def check_rule_dependencies(rules: List[SuggestedWorkflowRule]) -> List[RuleConflict]:
    """Detect contradictions and circular dependencies (H-023)."""
    conflicts: List[RuleConflict] = []

    # Index rules by (source, target)
    pair_rules: Dict[Tuple[Optional[str], Optional[str]], List[SuggestedWorkflowRule]] = defaultdict(list)
    for rule in rules:
        pair_rules[(rule.source, rule.target)].append(rule)

    # Direct contradiction: same source+target, required + forbidden
    for (src, tgt), group in pair_rules.items():
        if src is None or tgt is None:
            continue
        types = {r.type for r in group}
        if RuleType.REQUIRED_CALL.value in types and RuleType.FORBIDDEN_CALL.value in types:
            r_ids = [r.id for r in group]
            conflicts.append(RuleConflict(
                rule_a=r_ids[0],
                rule_b=r_ids[-1],
                conflict_type="contradiction",
                message=f"Both required and forbidden call between {src} → {tgt}",
            ))

    # Circular required_call chains: A→B, B→A
    required_edges: Dict[str, Set[str]] = defaultdict(set)
    rule_by_pair: Dict[Tuple[str, str], str] = {}
    for rule in rules:
        if rule.type == RuleType.REQUIRED_CALL.value and rule.source and rule.target:
            required_edges[rule.source].add(rule.target)
            rule_by_pair[(rule.source, rule.target)] = rule.id

    for src, targets in required_edges.items():
        for tgt in targets:
            if src in required_edges.get(tgt, set()):
                conflicts.append(RuleConflict(
                    rule_a=rule_by_pair.get((src, tgt), "?"),
                    rule_b=rule_by_pair.get((tgt, src), "?"),
                    conflict_type="circular",
                    message=f"Circular required_call: {src} ↔ {tgt}",
                ))

    return conflicts


# ═══════════════════════════════════════════════════════════════════════
# H-024 — Rule Statistics Dashboard
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class RuleStats:
    """Rule statistics (H-024)."""

    total_rules: int = 0
    by_type: Dict[str, int] = field(default_factory=dict)
    compliance_rate: float = 0.0
    satisfied: int = 0
    violated: int = 0
    dangling: int = 0
    unverifiable: int = 0
    node_coverage: float = 0.0  # % of nodes covered by at least one rule

    def format(self) -> str:
        lines = [f"Rules: {self.total_rules}"]
        for t, c in sorted(self.by_type.items()):
            lines.append(f"  {t}: {c}")
        lines.append(f"Compliance: {self.compliance_rate:.1%}")
        lines.append(f"  Satisfied: {self.satisfied}")
        lines.append(f"  Violated:  {self.violated}")
        lines.append(f"  Dangling:  {self.dangling}")
        lines.append(f"Node coverage: {self.node_coverage:.1%}")
        return "\n".join(lines)


def rule_statistics(
    suggested: SuggestedWorkflow,
    workflow: Workflow,
    graph0: Graph0,
    graph1: Graph1,
) -> RuleStats:
    """Generate rule compliance statistics (H-024)."""
    diff = policy_diff(suggested, workflow, graph0, graph1)
    stats = RuleStats(total_rules=len(suggested.rules))

    for rule in suggested.rules:
        stats.by_type[rule.type] = stats.by_type.get(rule.type, 0) + 1

    stats.satisfied = len(diff.satisfied)
    stats.violated = len(diff.violated)
    stats.dangling = len(diff.dangling)
    stats.unverifiable = len(diff.unverifiable)

    evaluable = stats.satisfied + stats.violated
    stats.compliance_rate = stats.satisfied / evaluable if evaluable > 0 else 1.0

    # Node coverage: how many graph0 nodes appear in at least one rule scope
    covered: Set[str] = set()
    clear_scope_cache()
    for rule in suggested.rules:
        covered |= expand_scope(rule, graph0, graph1, side="source")
        covered |= expand_scope(rule, graph0, graph1, side="target")

    total_nodes = len(graph0.nodes)
    stats.node_coverage = len(covered) / total_nodes if total_nodes > 0 else 0.0

    return stats


# ═══════════════════════════════════════════════════════════════════════
# H-025 — JSON Schema Validation (uses existing schema file)
# ═══════════════════════════════════════════════════════════════════════


def validate_schema(sw_data: Dict[str, Any]) -> List[str]:
    """Validate suggested_workflow data dict against JSON schema (H-025).

    Returns list of error messages (empty = valid).
    """
    errors: List[str] = []
    # Basic structural validation without external dependency
    if not isinstance(sw_data.get("version"), int):
        errors.append("'version' must be an integer")
    rules = sw_data.get("rules")
    if not isinstance(rules, list):
        errors.append("'rules' must be an array")
        return errors
    valid_types = {t.value for t in RuleType}
    for idx, rule in enumerate(rules):
        if not isinstance(rule, dict):
            errors.append(f"Rule [{idx}]: must be an object")
            continue
        if "type" in rule and rule["type"] not in valid_types:
            errors.append(f"Rule [{idx}]: invalid type '{rule['type']}'")
        if "id" not in rule:
            errors.append(f"Rule [{idx}]: missing 'id' field")
    return errors


# ═══════════════════════════════════════════════════════════════════════
# H-026 / H-027 — Semantic rule types (stub for future Group R)
#
# These depend on R-025/R-026 which aren't implemented yet.
# The schema and loader accept semantic rules; actual evaluation
# is deferred.
# ═══════════════════════════════════════════════════════════════════════


SEMANTIC_RULE_TYPES = frozenset({
    "requires_guard",
    "forbidden_effect",
    "required_effect",
    "domain_boundary",
    "action_sequence",
})


def is_semantic_rule(rule_type: str) -> bool:
    """Return True if rule_type is a semantic policy rule (H-026)."""
    return rule_type in SEMANTIC_RULE_TYPES


def evaluate_semantic_rules(
    suggested: SuggestedWorkflow,
    graph0: Graph0,
    graph1: Graph1,
    workflow: Workflow,
    graph2: Any = None,
) -> List[PolicyViolation]:
    """Evaluate semantic rules (H-027, R-016).  Returns violations.

    When Graph_2 is available, dispatches to the semantic violation detector.
    """
    violations: List[PolicyViolation] = []
    semantic_rules = [r for r in suggested.rules if is_semantic_rule(r.type)]

    if not semantic_rules:
        return violations

    if graph2 is None or not hasattr(graph2, "nodes") or not graph2.nodes:
        logger.info(
            "Skipping %d semantic rules (no Graph_2 data available)",
            len(semantic_rules),
        )
        return violations

    try:
        from codegraph.semantics import evaluate_semantic_rules_impl
        raw_violations = evaluate_semantic_rules_impl(graph2, graph0, workflow)

        for v in raw_violations:
            violations.append(PolicyViolation(
                rule_id=v.get("rule", "semantic"),
                rule_type="semantic",
                source=v.get("node_id", ""),
                target="",
                reason=v.get("message", ""),
                severity=v.get("severity", "info"),
            ))
    except Exception as exc:
        logger.warning("Semantic rule evaluation failed: %s", exc)

    return violations
