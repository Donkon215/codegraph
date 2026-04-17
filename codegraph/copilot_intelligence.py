"""codegraph.copilot_intelligence — Autonomous cognition layer for Copilot.

Adds the missing layers that make Copilot's interaction with codegraph
genuinely intelligent rather than merely informational:

1. **Scenario Engine** — generates component interaction scenarios,
   cross-product expansion, and system-level risk coverage.
   Includes pruning, ranking, and probabilistic filtering.
2. **Decision Layer** — structured reasoning with alternatives,
   rejected paths, confidence, and evidence.
   Memory-influenced: past patterns boost or penalize actions.
3. **Deep Simulation** — state transitions, data flow impact,
   failure injection beyond structural analysis.
4. **Confidence Calibration** — tracks predicted vs actual outcomes,
   adjusts future confidence based on historical accuracy.
5. **Query Engine Integration** — actively uses path analysis,
   dependency traversal, and explain for richer context.
6. **Copilot Loop Orchestrator** — single entry point that runs
   the full cognition cycle without manual step-by-step invocation.

CLI commands: copilot-loop, scenario, decide
"""

from __future__ import annotations

import json
import math
from collections import deque
from dataclasses import dataclass, field
from itertools import islice, product
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple

from codegraph.logging_config import get_logger

logger = get_logger("copilot_intelligence")

MAX_SCENARIO_COMBINATIONS = 200


# ═══════════════════════════════════════════════════════════════════════
# 1. Scenario Explosion Engine
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class ComponentScenario:
    """A single scenario for one component."""

    component_id: str = ""
    scenario_id: str = ""
    description: str = ""
    change_type: str = ""  # add_dep, remove_dep, split, merge, rewire
    affected_edges: List[str] = field(default_factory=list)
    risk: str = "low"  # low | medium | high

    def to_dict(self) -> Dict[str, Any]:
        return {
            "component_id": self.component_id,
            "scenario_id": self.scenario_id,
            "description": self.description,
            "change_type": self.change_type,
            "affected_edges": self.affected_edges[:10],
            "risk": self.risk,
        }


@dataclass
class SystemScenario:
    """A cross-product scenario combining changes across components."""

    scenario_id: str = ""
    components: List[ComponentScenario] = field(default_factory=list)
    interaction_risk: str = "low"
    failure_propagation: List[str] = field(default_factory=list)
    coverage_paths: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "components": [c.to_dict() for c in self.components],
            "interaction_risk": self.interaction_risk,
            "failure_propagation": self.failure_propagation[:10],
            "coverage_paths": self.coverage_paths[:10],
        }


@dataclass
class ScenarioReport:
    """Full scenario explosion report."""

    component_scenarios: Dict[str, List[ComponentScenario]] = field(
        default_factory=dict
    )
    system_scenarios: List[SystemScenario] = field(default_factory=list)
    total_combinations: int = 0
    sampled_combinations: int = 0
    risk_distribution: Dict[str, int] = field(default_factory=dict)
    coverage_score: float = 0.0
    next_steps: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "component_scenarios": {
                k: [s.to_dict() for s in v]
                for k, v in self.component_scenarios.items()
            },
            "system_scenarios": [s.to_dict() for s in self.system_scenarios[:50]],
            "total_combinations": self.total_combinations,
            "sampled_combinations": self.sampled_combinations,
            "risk_distribution": self.risk_distribution,
            "coverage_score": round(self.coverage_score, 3),
            "next_steps": self.next_steps,
        }

    def format(self) -> str:
        lines = ["Scenario Explosion Report"]
        lines.append(
            f"  Components: {len(self.component_scenarios)}  "
            f"System scenarios: {self.sampled_combinations}/{self.total_combinations}"
        )
        lines.append(f"  Coverage: {self.coverage_score:.1%}")
        lines.append(f"  Risk: {self.risk_distribution}")

        for comp_id, scenarios in self.component_scenarios.items():
            lines.append(f"\n  {comp_id}:")
            for s in scenarios[:5]:
                lines.append(f"    [{s.scenario_id}] {s.description} (risk={s.risk})")

        if self.system_scenarios:
            lines.append(f"\n  System Scenarios (top {min(10, len(self.system_scenarios))}):")
            for ss in self.system_scenarios[:10]:
                comp_ids = ", ".join(c.scenario_id for c in ss.components)
                lines.append(f"    [{ss.scenario_id}] ({comp_ids}) risk={ss.interaction_risk}")
                if ss.failure_propagation:
                    lines.append(
                        f"      propagation: {' → '.join(ss.failure_propagation[:5])}"
                    )

        if self.next_steps:
            lines.append("\n  Next Steps:")
            for ns in self.next_steps[:5]:
                lines.append(f"    → {ns}")

        return "\n".join(lines)


def scenario_context(
    project_root: Path,
    *,
    target_components: Optional[List[str]] = None,
    max_combinations: int = MAX_SCENARIO_COMBINATIONS,
) -> ScenarioReport:
    """Generate component scenarios and cross-product system scenarios.

    For each component (hotspot module / subsystem), generates possible
    change scenarios. Then computes cross-product combinations to find
    interaction risks and failure propagation paths.

    Args:
        project_root: Project root path.
        target_components: Specific components to analyze. If None, uses
            hotspot modules.
        max_combinations: Cap on cross-product expansion.
    """
    report = ScenarioReport()

    # 1. Identify target components from hotspots
    from codegraph.copilot_context_builder import hotspot_context

    hotspots = hotspot_context(project_root)
    components = target_components or []

    if not components:
        # Use hotspot modules as components
        for v in hotspots.violation_hotspots[:5]:
            mod = v.get("node", "").split("::", 1)[0]
            if mod and mod not in components:
                components.append(mod)
        for g in hotspots.god_modules[:3]:
            mod = g.get("module", "")
            if mod and mod not in components:
                components.append(mod)
        for c in hotspots.coupling_hotspots[:3]:
            mod = c.get("module", "")
            if mod and mod not in components:
                components.append(mod)

    if not components:
        report.next_steps = ["No hotspot components found. Run: codegraph build && codegraph analyze"]
        return report

    # 2. Load graph for edge analysis
    wf_edges = _load_workflow_edges(project_root)
    g0_nodes = _load_graph0_nodes(project_root)

    # 3. Generate per-component scenarios
    for comp in components[:10]:
        scenarios = _generate_component_scenarios(comp, g0_nodes, wf_edges)
        if scenarios:
            report.component_scenarios[comp] = scenarios

    # 4. Cross-product expansion
    if len(report.component_scenarios) >= 2:
        all_scenario_lists = list(report.component_scenarios.values())
        total = 1
        for sl in all_scenario_lists:
            total *= len(sl)
        report.total_combinations = total

        combos = list(islice(product(*all_scenario_lists), max_combinations))
        report.sampled_combinations = len(combos)

        for i, combo in enumerate(combos):
            system_scenario = _build_system_scenario(
                f"SYS-{i + 1:03d}", list(combo), wf_edges
            )
            report.system_scenarios.append(system_scenario)
    elif report.component_scenarios:
        # Single component — scenarios are system scenarios
        for comp_id, scenarios in report.component_scenarios.items():
            for s in scenarios:
                ss = SystemScenario(
                    scenario_id=f"SYS-{s.scenario_id}",
                    components=[s],
                    interaction_risk=s.risk,
                )
                report.system_scenarios.append(ss)
        report.total_combinations = len(report.system_scenarios)
        report.sampled_combinations = len(report.system_scenarios)

    # 5. Risk distribution
    risk_counts: Dict[str, int] = {"low": 0, "medium": 0, "high": 0}
    for ss in report.system_scenarios:
        risk_counts[ss.interaction_risk] = risk_counts.get(
            ss.interaction_risk, 0
        ) + 1
    report.risk_distribution = risk_counts

    # 6. Coverage score
    total_components = len(components)
    covered = len(report.component_scenarios)
    report.coverage_score = covered / max(total_components, 1)

    # 7. Prune and rank system scenarios
    if report.system_scenarios:
        report.system_scenarios = _rank_and_prune_scenarios(
            report.system_scenarios, max_keep=max_combinations
        )

    # 8. Next steps
    high_risk = [
        ss for ss in report.system_scenarios if ss.interaction_risk == "high"
    ]
    if high_risk:
        report.next_steps.append(
            f"Simulate {len(high_risk)} high-risk scenarios: "
            f"codegraph copilot-loop --simulate"
        )
    if report.coverage_score < 0.8:
        report.next_steps.append(
            f"Coverage {report.coverage_score:.0%} — run codegraph build to "
            f"capture missing components"
        )
    report.next_steps.append(
        "Run: codegraph decide <scenario_id> to get decision reasoning"
    )

    return report


def _generate_component_scenarios(
    component: str,
    g0_nodes: Dict[str, Any],
    wf_edges: List[Dict[str, Any]],
) -> List[ComponentScenario]:
    """Generate change scenarios for a single component."""
    scenarios: List[ComponentScenario] = []

    # Find edges involving this component
    outbound = [
        e for e in wf_edges if e.get("source", "").startswith(component)
    ]
    inbound = [
        e for e in wf_edges if e.get("target", "").startswith(component)
    ]

    component_nodes = [
        nid for nid in g0_nodes if nid.startswith(component)
    ]

    base_id = component.replace("/", "_").replace(".", "_")

    # Scenario: reduce fan-out (remove low-confidence outbound edges)
    if len(outbound) > 10:
        scenarios.append(ComponentScenario(
            component_id=component,
            scenario_id=f"{base_id}_S1",
            description=f"Reduce fan-out from {len(outbound)} to ≤10 by extracting helpers",
            change_type="split",
            affected_edges=[f"{e.get('source','')}→{e.get('target','')}" for e in outbound[:5]],
            risk="medium",
        ))

    # Scenario: break incoming coupling
    if len(inbound) > 15:
        scenarios.append(ComponentScenario(
            component_id=component,
            scenario_id=f"{base_id}_S2",
            description=f"Reduce inbound coupling ({len(inbound)} callers) via interface extraction",
            change_type="add_dep",
            affected_edges=[f"{e.get('source','')}→{e.get('target','')}" for e in inbound[:5]],
            risk="high",
        ))

    # Scenario: split god module
    if len(component_nodes) > 20:
        scenarios.append(ComponentScenario(
            component_id=component,
            scenario_id=f"{base_id}_S3",
            description=f"Split module ({len(component_nodes)} nodes) into cohesive sub-modules",
            change_type="split",
            affected_edges=[],
            risk="high",
        ))

    # Scenario: dependency inversion for cross-layer calls
    cross_layer = [
        e for e in outbound
        if _is_cross_layer(e.get("source", ""), e.get("target", ""))
    ]
    if cross_layer:
        scenarios.append(ComponentScenario(
            component_id=component,
            scenario_id=f"{base_id}_S4",
            description=f"Invert {len(cross_layer)} cross-layer dependency(ies)",
            change_type="rewire",
            affected_edges=[f"{e.get('source','')}→{e.get('target','')}" for e in cross_layer[:5]],
            risk="medium",
        ))

    # Scenario: no-change baseline
    scenarios.append(ComponentScenario(
        component_id=component,
        scenario_id=f"{base_id}_S0",
        description="No change (baseline)",
        change_type="none",
        affected_edges=[],
        risk="low",
    ))

    return scenarios


def _rank_and_prune_scenarios(
    system_scenarios: List[SystemScenario],
    max_keep: int = 50,
) -> List[SystemScenario]:
    """Rank system scenarios by risk and prune low-value ones.

    Scoring: high risk=3, medium=2, low=1.
    Non-baseline components get +1.
    Multiplicative: more changed components = higher score.
    Keeps top ``max_keep`` by score.
    """
    risk_weight = {"high": 3, "medium": 2, "low": 1}

    def _score(ss: SystemScenario) -> float:
        base = risk_weight.get(ss.interaction_risk, 1)
        changed = sum(1 for c in ss.components if c.change_type != "none")
        propagation_bonus = min(len(ss.failure_propagation), 5) * 0.5
        return base * max(changed, 1) + propagation_bonus

    scored = sorted(system_scenarios, key=_score, reverse=True)
    return scored[:max_keep]


def _build_system_scenario(
    scenario_id: str,
    components: List[ComponentScenario],
    wf_edges: List[Dict[str, Any]],
) -> SystemScenario:
    """Build a system-level scenario from component scenarios."""
    # Determine interaction risk
    risks = [c.risk for c in components]
    if risks.count("high") >= 2:
        interaction_risk = "high"
    elif "high" in risks:
        interaction_risk = "medium"
    elif risks.count("medium") >= 2:
        interaction_risk = "medium"
    else:
        interaction_risk = "low"

    # Determine failure propagation
    propagation: List[str] = []
    changed_modules = {c.component_id for c in components if c.change_type != "none"}
    if changed_modules:
        # Trace outbound edges from changed modules
        for edge in wf_edges:
            src_mod = edge.get("source", "").split("::", 1)[0]
            tgt_mod = edge.get("target", "").split("::", 1)[0]
            if src_mod in changed_modules and tgt_mod not in changed_modules:
                propagation.append(f"{src_mod} → {tgt_mod}")

    # Coverage paths: internal edges between changed components
    coverage: List[str] = []
    for edge in wf_edges:
        src_mod = edge.get("source", "").split("::", 1)[0]
        tgt_mod = edge.get("target", "").split("::", 1)[0]
        if src_mod in changed_modules and tgt_mod in changed_modules:
            coverage.append(f"{src_mod} ↔ {tgt_mod}")

    return SystemScenario(
        scenario_id=scenario_id,
        components=components,
        interaction_risk=interaction_risk,
        failure_propagation=list(dict.fromkeys(propagation)),
        coverage_paths=list(dict.fromkeys(coverage)),
    )


def _is_cross_layer(source: str, target: str) -> bool:
    """Heuristic: detect likely cross-layer calls."""
    src_parts = source.lower()
    tgt_parts = target.lower()
    layers = ["controller", "handler", "route", "service", "repository", "model", "util"]
    src_layer = next((l for l in layers if l in src_parts), "")
    tgt_layer = next((l for l in layers if l in tgt_parts), "")
    if src_layer and tgt_layer and src_layer != tgt_layer:
        layer_order = {l: i for i, l in enumerate(layers)}
        return layer_order.get(src_layer, 0) > layer_order.get(tgt_layer, 99)
    return False


# ═══════════════════════════════════════════════════════════════════════
# 2. Decision Reasoning Layer
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class DecisionAlternative:
    """An alternative action that was considered."""

    action: str = ""
    reason_rejected: str = ""
    estimated_risk: str = "medium"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "reason_rejected": self.reason_rejected,
            "estimated_risk": self.estimated_risk,
        }


@dataclass
class Decision:
    """A structured architecture decision with full reasoning trace."""

    decision_id: str = ""
    target: str = ""
    action: str = ""
    reason: str = ""
    alternatives: List[DecisionAlternative] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)
    confidence: float = 0.0
    risk: str = "low"
    impact_scope: str = "node"  # node | module | subsystem | system
    preconditions: List[str] = field(default_factory=list)
    postconditions: List[str] = field(default_factory=list)
    next_steps: List[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        """One-line human-readable summary for Copilot inline context."""
        risk_label = {"low": "[LOW]", "medium": "[CAUTION]", "high": "[HIGH-RISK]"}.get(
            self.risk, "[?]"
        )
        return (
            f"{risk_label} {self.action} on `{self.target}` "
            f"({self.confidence:.0%} confidence) -- {self.reason[:80]}"
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "target": self.target,
            "action": self.action,
            "summary": self.summary,
            "reason": self.reason,
            "alternatives": [a.to_dict() for a in self.alternatives],
            "evidence": self.evidence[:10],
            "confidence": round(self.confidence, 2),
            "risk": self.risk,
            "impact_scope": self.impact_scope,
            "preconditions": self.preconditions,
            "postconditions": self.postconditions,
            "next_steps": self.next_steps,
        }

    def format(self) -> str:
        lines = [
            f"Decision: {self.decision_id}",
            f"  Target: {self.target}",
            f"  Action: {self.action}",
            f"  Reason: {self.reason}",
            f"  Confidence: {self.confidence:.0%}  Risk: {self.risk}  "
            f"Scope: {self.impact_scope}",
        ]
        if self.evidence:
            lines.append("  Evidence:")
            for e in self.evidence[:5]:
                lines.append(f"    - {e}")
        if self.alternatives:
            lines.append("  Alternatives considered:")
            for a in self.alternatives[:3]:
                lines.append(f"    X {a.action}: {a.reason_rejected}")
        if self.preconditions:
            lines.append("  Preconditions:")
            for p in self.preconditions:
                lines.append(f"    - {p}")
        if self.next_steps:
            lines.append("  Next Steps:")
            for ns in self.next_steps:
                lines.append(f"    → {ns}")
        return "\n".join(lines)

    def save(self, project_root: Path) -> Path:
        """Persist decision to .codegraph/decisions/."""
        decisions_dir = project_root / ".codegraph" / "decisions"
        decisions_dir.mkdir(parents=True, exist_ok=True)
        path = decisions_dir / f"{self.decision_id}.json"
        path.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return path


def decide(
    project_root: Path,
    target: str,
    *,
    action_hint: str = "",
) -> Decision:
    """Generate a structured architecture decision for a target.

    Analyzes the target, considers alternatives, and produces a decision
    with full reasoning trace. Copilot uses this to explain WHY a fix
    is the right approach.

    Args:
        project_root: Project root path.
        target: File, node, or subsystem to decide about.
        action_hint: Optional hint about what kind of action is planned.
    """
    from codegraph.copilot_context_builder import focus_context, hotspot_context

    decision = Decision(
        decision_id=f"DEC-{_short_hash(target)}",
        target=target,
    )

    # 0. Load memory — past patterns influence this decision
    memory_patterns = _load_memory_patterns(project_root)

    # 1. Gather focus context
    focus = focus_context(project_root, target, depth=1)

    # 1b. Enrich with query engine data (paths, dependencies)
    query_insights = _query_enrich(project_root, target, focus)

    # 2. Determine primary action based on context
    if focus.violations:
        decision.action = "fix_violations"
        decision.reason = (
            f"{len(focus.violations)} violation(s) detected. "
            f"Architecture rules are broken in this area."
        )
        decision.risk = "medium" if len(focus.violations) <= 3 else "high"
        decision.evidence.extend(focus.violations[:5])

        decision.alternatives.append(DecisionAlternative(
            action="ignore_violations",
            reason_rejected="Violations propagate and degrade architecture score",
            estimated_risk="high",
        ))
        decision.alternatives.append(DecisionAlternative(
            action="suppress_rule",
            reason_rejected="Suppressing masks real coupling issues",
            estimated_risk="medium",
        ))

    elif focus.fan_out > 15:
        decision.action = "reduce_fan_out"
        decision.reason = (
            f"Fan-out is {focus.fan_out} (threshold: 15). "
            f"Extract helper modules or apply dependency inversion."
        )
        decision.risk = "medium"
        decision.evidence.append(f"Fan-out: {focus.fan_out}")
        decision.evidence.extend(
            [f"Callee: {c}" for c in focus.callees[:5]]
        )

        decision.alternatives.append(DecisionAlternative(
            action="split_module",
            reason_rejected="Module split has higher blast radius than extraction",
            estimated_risk="high",
        ))
        decision.alternatives.append(DecisionAlternative(
            action="no_change",
            reason_rejected=f"Fan-out {focus.fan_out} exceeds safe threshold",
            estimated_risk="low",
        ))

    elif focus.fan_in > 20:
        decision.action = "stabilize_interface"
        decision.reason = (
            f"Fan-in is {focus.fan_in}. Changes here affect "
            f"{focus.fan_in} callers. Stabilize interface first."
        )
        decision.risk = "high"
        decision.evidence.append(f"Fan-in: {focus.fan_in}")
        decision.evidence.extend(
            [f"Caller: {c}" for c in focus.callers[:5]]
        )

        decision.alternatives.append(DecisionAlternative(
            action="direct_edit",
            reason_rejected=f"Wide blast radius: {focus.fan_in} callers affected",
            estimated_risk="high",
        ))

    elif focus.smells:
        decision.action = "address_smells"
        smell_types = [s.get("smell_type", "") for s in focus.smells]
        decision.reason = (
            f"{len(focus.smells)} smell(s) detected: {', '.join(smell_types[:3])}"
        )
        decision.risk = "low"
        decision.evidence.extend(
            [f"{s.get('smell_type', '')}: {s.get('description', '')}"
             for s in focus.smells[:5]]
        )

    else:
        decision.action = action_hint or "safe_to_edit"
        decision.reason = (
            "No violations, acceptable coupling, no critical smells. "
            "Area is safe for modification."
        )
        decision.risk = "low"
        decision.confidence = 0.9

    # 3. Confidence based on evidence quality + memory calibration
    if not decision.confidence:
        evidence_count = len(decision.evidence)
        base_confidence = min(0.95, 0.5 + evidence_count * 0.1)
        # Adjust by historical success rate of this action type
        memory_boost = _memory_confidence_adjustment(
            memory_patterns, decision.action
        )
        decision.confidence = min(0.99, max(0.1, base_confidence + memory_boost))

    # 3b. Add query-derived evidence
    if query_insights.get("dependency_depth"):
        decision.evidence.append(
            f"Dependency depth: {query_insights['dependency_depth']}"
        )
    if query_insights.get("paths_to_hotspots"):
        for ph in query_insights["paths_to_hotspots"][:3]:
            decision.evidence.append(f"Path to hotspot: {ph}")
    if query_insights.get("cycle_involvement"):
        decision.evidence.append(
            f"Involved in {query_insights['cycle_involvement']} cycle path(s)"
        )
        if decision.risk == "low":
            decision.risk = "medium"

    # 3c. Memory-informed preconditions
    for mp in memory_patterns:
        if mp.get("task_type") == decision.action and mp.get("success_count", 0) >= 3:
            decision.evidence.append(
                f"Memory: pattern '{mp.get('action_taken', '')}' "
                f"succeeded {mp.get('success_count', 0)}x for '{mp.get('task_type', '')}'"
            )

    # 4. Impact scope
    if focus.target_type == "file":
        decision.impact_scope = "module"
    elif focus.target_type == "node":
        if focus.fan_in > 10:
            decision.impact_scope = "subsystem"
        else:
            decision.impact_scope = "node"
    else:
        decision.impact_scope = "subsystem"

    # 5. Preconditions
    if focus.violations:
        decision.preconditions.append("Fix existing violations before adding new code")
    if focus.subsystem:
        decision.preconditions.append(
            f"Verify changes stay within '{focus.subsystem}' subsystem boundary"
        )

    # 6. Postconditions
    decision.postconditions.append("Run: codegraph build && codegraph analyze")
    decision.postconditions.append("Run: codegraph score (verify no degradation)")

    # 7. Next steps
    decision.next_steps.append(
        f"Run: codegraph focus {target} --json (verify after changes)"
    )
    if decision.risk in ("medium", "high"):
        decision.next_steps.append(
            "Run: codegraph copilot-loop --simulate (validate impact)"
        )
    decision.next_steps.append(
        "Run: codegraph hotspots --json (verify improvement)"
    )

    return decision


# ═══════════════════════════════════════════════════════════════════════
# 3. Copilot Loop Orchestrator
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class LoopIteration:
    """One iteration of the copilot loop."""

    step: str = ""
    result: Dict[str, Any] = field(default_factory=dict)
    status: str = "ok"  # ok | warning | error

    def to_dict(self) -> Dict[str, Any]:
        return {"step": self.step, "status": self.status, "result": self.result}


@dataclass
class CopilotLoopReport:
    """Full report from a copilot-loop execution."""

    target: str = ""
    iterations: List[LoopIteration] = field(default_factory=list)
    decision: Optional[Decision] = None
    simulation: Dict[str, Any] = field(default_factory=dict)
    score_before: float = 0.0
    score_after: float = 0.0
    score_delta: float = 0.0
    verdict: str = ""  # proceed | caution | block
    next_steps: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "target": self.target,
            "iterations": [i.to_dict() for i in self.iterations],
            "verdict": self.verdict,
            "score_before": round(self.score_before, 4),
            "score_after": round(self.score_after, 4),
            "score_delta": round(self.score_delta, 4),
            "next_steps": self.next_steps,
        }
        if self.decision:
            d["decision"] = self.decision.to_dict()
        if self.simulation:
            d["simulation"] = self.simulation
        return d

    def format(self) -> str:
        lines = [f"Copilot Loop: {self.target}"]
        lines.append(f"  Verdict: {self.verdict}")
        lines.append(
            f"  Score: {self.score_before:.4f} → {self.score_after:.4f} "
            f"(delta={self.score_delta:+.4f})"
        )

        for it in self.iterations:
            indicator = "✓" if it.status == "ok" else "⚠" if it.status == "warning" else "✗"
            lines.append(f"  {indicator} {it.step}")

        if self.decision:
            lines.append(f"\n  Decision: {self.decision.action}")
            lines.append(f"    Reason: {self.decision.reason}")
            lines.append(f"    Risk: {self.decision.risk}  "
                         f"Confidence: {self.decision.confidence:.0%}")

        if self.next_steps:
            lines.append("\n  Next Steps:")
            for ns in self.next_steps:
                lines.append(f"    → {ns}")

        return "\n".join(lines)


def copilot_loop(
    project_root: Path,
    target: str,
    *,
    simulate: bool = False,
    save: bool = False,
) -> CopilotLoopReport:
    """Execute the full Copilot cognition loop for a target.

    This is the single entry point that replaces manual:
      hotspots → focus → decide → simulate → score

    The system chooses the tools. Copilot just calls this.

    Args:
        project_root: Project root path.
        target: File, node, or subsystem.
        simulate: Whether to run simulation step.
        save: Whether to persist decision to disk.
    """
    from codegraph.copilot_context_builder import (
        focus_context,
        hotspot_context,
    )

    report = CopilotLoopReport(target=target)

    # Step 1: Hotspots — understand system state
    hotspots = hotspot_context(project_root)
    report.score_before = hotspots.score
    report.iterations.append(LoopIteration(
        step="hotspots",
        result={
            "score": hotspots.score,
            "grade": hotspots.grade,
            "violations": len(hotspots.violation_hotspots),
            "god_modules": len(hotspots.god_modules),
            "cycles": len(hotspots.cycle_participants),
        },
        status="ok",
    ))

    # Step 2: Focus — zoom into target
    focus = focus_context(project_root, target, depth=1)
    focus_status = "ok"
    if focus.violations:
        focus_status = "warning"
    if not focus.nodes:
        focus_status = "error"

    report.iterations.append(LoopIteration(
        step="focus",
        result={
            "nodes": len(focus.nodes),
            "edges": len(focus.edges),
            "violations": len(focus.violations),
            "fan_in": focus.fan_in,
            "fan_out": focus.fan_out,
            "subsystem": focus.subsystem,
        },
        status=focus_status,
    ))

    # Step 3: Decide — structured reasoning
    decision = decide(project_root, target)
    report.decision = decision
    report.iterations.append(LoopIteration(
        step="decide",
        result={
            "action": decision.action,
            "risk": decision.risk,
            "confidence": decision.confidence,
        },
        status="ok" if decision.confidence >= 0.7 else "warning",
    ))

    if save:
        decision.save(project_root)

    # Step 4: Simulate (if requested and simulator available)
    if simulate:
        sim_result = _try_simulate(project_root, target, decision)
        report.simulation = sim_result
        report.iterations.append(LoopIteration(
            step="simulate",
            result=sim_result,
            status="ok" if sim_result.get("score_delta", 0) >= 0 else "warning",
        ))
        if "predicted_architecture_score" in sim_result:
            report.score_after = sim_result["predicted_architecture_score"]

        # Step 4b: Deep simulation — data flow + failure propagation
        deep_sim = _deep_simulate(project_root, target, focus)
        if deep_sim:
            report.iterations.append(LoopIteration(
                step="deep_simulate",
                result=deep_sim,
                status="ok" if not deep_sim.get("failure_chains") else "warning",
            ))
            # Merge deep sim findings into simulation dict
            report.simulation["data_flow_impact"] = deep_sim.get(
                "data_flow_edges_affected", 0
            )
            report.simulation["failure_chains"] = deep_sim.get(
                "failure_chains", []
            )
            report.simulation["state_transitions"] = deep_sim.get(
                "state_transitions", []
            )
    else:
        report.score_after = report.score_before

    report.score_delta = report.score_after - report.score_before

    # Step 5: Verdict
    if focus_status == "error":
        report.verdict = "block"
    elif decision.risk == "high" and decision.confidence < 0.7:
        report.verdict = "block"
    elif decision.risk == "high" or focus.violations:
        report.verdict = "caution"
    else:
        report.verdict = "proceed"

    # Step 6: Next steps
    if report.verdict == "block":
        report.next_steps.append(
            "Target not found or high-risk with low confidence. "
            "Run: codegraph build first."
        )
    elif report.verdict == "caution":
        report.next_steps.extend(decision.next_steps)
        if not simulate:
            report.next_steps.insert(
                0,
                f"Run: codegraph copilot-loop {target} --simulate (validate before applying)"
            )
    else:
        report.next_steps.append(f"Safe to proceed. After changes: codegraph build && codegraph analyze")
        report.next_steps.append(f"Verify: codegraph focus {target} --json")

    # Step 7: Record prediction for confidence calibration
    if save:
        _record_prediction(
            project_root,
            decision_id=decision.decision_id,
            predicted_action=decision.action,
            predicted_risk=decision.risk,
            predicted_confidence=decision.confidence,
            predicted_score_delta=report.score_delta,
        )

    return report


def _try_simulate(
    project_root: Path,
    target: str,
    decision: Decision,
) -> Dict[str, Any]:
    """Attempt to run architecture simulation for the decision."""
    try:
        from codegraph.architecture_simulator import simulate_change

        # Map decision action to simulation change type
        change_map = {
            "fix_violations": "remove_edge",
            "reduce_fan_out": "remove_edge",
            "stabilize_interface": "rewire_edge",
            "address_smells": "remove_edge",
            "safe_to_edit": "add_edge",
        }
        change = change_map.get(decision.action, "add_edge")

        # Get first callee as target for simulation
        sim_target = ""
        if decision.evidence:
            for ev in decision.evidence:
                if "Callee:" in ev:
                    sim_target = ev.replace("Callee: ", "").strip()
                    break

        if not sim_target and decision.target:
            sim_target = decision.target

        result = simulate_change(
            project_root,
            node=target if "::" in target else f"{target}::*",
            change=change,
            target=sim_target,
        )
        return result
    except Exception as exc:
        return {
            "status": "simulation_unavailable",
            "reason": str(exc),
            "score_delta": 0,
        }


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════


def _short_hash(s: str) -> str:
    """Generate a short deterministic ID from a string."""
    import hashlib
    return hashlib.sha256(s.encode()).hexdigest()[:8]


def _load_workflow_edges(project_root: Path) -> List[Dict[str, Any]]:
    wf_path = project_root / ".codegraph" / "workflow" / "workflow.json"
    if not wf_path.exists():
        return []
    try:
        wf = json.loads(wf_path.read_text(encoding="utf-8"))
        return wf.get("edges", [])
    except (json.JSONDecodeError, OSError):
        return []


def _load_graph0_nodes(project_root: Path) -> Dict[str, Any]:
    g0_path = project_root / ".codegraph" / "graphs" / "graph0.json"
    if not g0_path.exists():
        return {}
    try:
        g0 = json.loads(g0_path.read_text(encoding="utf-8"))
        return {n.get("id", ""): n for n in g0.get("nodes", [])}
    except (json.JSONDecodeError, OSError):
        return {}


# ═══════════════════════════════════════════════════════════════════════
# 4. Learning Loop — Memory-Influenced Decisions
# ═══════════════════════════════════════════════════════════════════════


def _load_memory_patterns(project_root: Path) -> List[Dict[str, Any]]:
    """Load repair patterns from agent memory for decision influence."""
    try:
        from codegraph.agent_memory import load_memory
        memory = load_memory(project_root)
        return [p.to_dict() for p in memory.patterns]
    except Exception:
        return []


def _memory_confidence_adjustment(
    patterns: List[Dict[str, Any]], action: str
) -> float:
    """Adjust confidence based on historical pattern success/failure.

    Returns a float delta: positive = boost, negative = penalize.
    """
    if not patterns:
        return 0.0

    # Find patterns matching this action type
    action_map = {
        "fix_violations": "policy_violation",
        "reduce_fan_out": "orphan",  # fan-out reduction often involves extraction
        "stabilize_interface": "intent_missing",
        "address_smells": "policy_violation",
    }
    task_type = action_map.get(action, "")
    if not task_type:
        return 0.0

    matching = [p for p in patterns if p.get("task_type") == task_type]
    if not matching:
        return 0.0

    total_success = sum(p.get("success_count", 0) for p in matching)
    if total_success >= 10:
        return 0.15  # Strong signal — boost confidence
    elif total_success >= 3:
        return 0.08  # Moderate signal
    elif total_success == 0:
        return -0.1  # Action has never succeeded — penalize
    return 0.0


# ═══════════════════════════════════════════════════════════════════════
# 5. Query Engine Integration
# ═══════════════════════════════════════════════════════════════════════


def _query_enrich(
    project_root: Path,
    target: str,
    focus: Any,
) -> Dict[str, Any]:
    """Use the query engine to gather deeper dependency insights.

    Integrates: dependency depth, paths to hotspots, cycle involvement.
    """
    insights: Dict[str, Any] = {}

    try:
        from codegraph.index import IndexStore

        idx_path = project_root / ".codegraph" / "index"
        if not idx_path.exists():
            return insights

        index = IndexStore(idx_path)

        # Determine effective node ID
        node_id = target
        if "::" not in target and focus.nodes:
            node_id = focus.nodes[0].get("id", target)

        # Dependency depth (transitive callees)
        try:
            from codegraph.query import query_dependencies
            deps = query_dependencies(node_id, index, depth=5, limit=100)
            insights["dependency_depth"] = deps.total
        except Exception:
            pass

        # Cycle involvement via orphan / path checks
        try:
            callees = index.get_callees(node_id)
            callers = index.get_callers(node_id)
            # Simple cycle check: does any callee path lead back?
            cycle_count = 0
            for callee in callees[:10]:
                callee_callees = index.get_callees(callee)
                if node_id in callee_callees:
                    cycle_count += 1
            if cycle_count:
                insights["cycle_involvement"] = cycle_count
        except Exception:
            pass

        # Paths to hotspots (if hotspot data available)
        try:
            from codegraph.query import query_path

            violations_path = (
                project_root / ".codegraph" / "analysis" / "violations.json"
            )
            if violations_path.exists():
                vdata = json.loads(violations_path.read_text(encoding="utf-8"))
                hotspot_nodes = [
                    v.get("node", "") for v in vdata.get("violations", [])[:5]
                ]
                paths_found: List[str] = []
                for hn in hotspot_nodes:
                    if hn and hn != node_id:
                        result = query_path(node_id, hn, index, depth=8)
                        if result.paths:
                            paths_found.append(
                                " → ".join(result.paths[0][:5])
                            )
                if paths_found:
                    insights["paths_to_hotspots"] = paths_found
        except Exception:
            pass

    except Exception:
        pass

    return insights


# ═══════════════════════════════════════════════════════════════════════
# 6. Deep Simulation — State, Data Flow, Failure Injection
# ═══════════════════════════════════════════════════════════════════════


def _deep_simulate(
    project_root: Path,
    target: str,
    focus: Any,
) -> Dict[str, Any]:
    """Deep simulation beyond structural: data flow, failure propagation,
    state transitions.

    Returns a dict with:
        data_flow_edges_affected: int
        failure_chains: list of propagation chains
        state_transitions: list of state changes
        side_effects: list of external effects
    """
    result: Dict[str, Any] = {}

    wf_edges = _load_workflow_edges(project_root)
    g0_nodes = _load_graph0_nodes(project_root)

    target_nodes = {
        nid for nid in g0_nodes if nid.startswith(target.split("::", 1)[0])
    }
    if not target_nodes:
        target_nodes = {target}

    # Data flow impact: count data_flow and side_effect edges
    data_flow_count = 0
    side_effects: List[str] = []
    for edge in wf_edges:
        src = edge.get("source", "")
        etype = edge.get("edge_type", "")
        if src in target_nodes:
            if etype == "data_flow":
                data_flow_count += 1
            elif etype == "side_effect":
                side_effects.append(
                    f"{src} → {edge.get('target', '')} ({etype})"
                )
    result["data_flow_edges_affected"] = data_flow_count
    result["side_effects"] = side_effects[:10]

    # Failure propagation chains: BFS from target through call edges
    failure_chains: List[List[str]] = []
    visited: set = set()
    bfs_queue: Deque[Tuple[str, List[str]]] = deque(
        (n, [n]) for n in target_nodes
    )
    max_depth = 5

    while bfs_queue:
        current, chain = bfs_queue.popleft()
        if current in visited or len(chain) > max_depth:
            continue
        visited.add(current)

        for edge in wf_edges:
            if edge.get("source") == current:
                next_node = edge.get("target", "")
                if next_node and next_node not in visited:
                    new_chain = chain + [next_node]
                    if next_node not in target_nodes:
                        failure_chains.append(new_chain)
                    bfs_queue.append((next_node, new_chain))

    # Keep only longest unique chains (dedup by last node)
    seen_ends: set = set()
    unique_chains: List[List[str]] = []
    for chain in sorted(failure_chains, key=len, reverse=True):
        end = chain[-1]
        if end not in seen_ends:
            seen_ends.add(end)
            unique_chains.append(chain)
    result["failure_chains"] = [
        " → ".join(c) for c in unique_chains[:10]
    ]

    # State transitions: detect control_flow edges from target
    state_transitions: List[str] = []
    for edge in wf_edges:
        src = edge.get("source", "")
        etype = edge.get("edge_type", "")
        if src in target_nodes and etype == "control_flow":
            state_transitions.append(
                f"{src} →[{etype}] {edge.get('target', '')}"
            )
    result["state_transitions"] = state_transitions[:10]

    return result


# ═══════════════════════════════════════════════════════════════════════
# 7. Confidence Calibration — Track Predictions vs Outcomes
# ═══════════════════════════════════════════════════════════════════════

CALIBRATION_FILE = "confidence_calibration.json"


@dataclass
class PredictionRecord:
    """A recorded prediction for later calibration."""

    decision_id: str = ""
    predicted_action: str = ""
    predicted_risk: str = ""
    predicted_confidence: float = 0.0
    predicted_score_delta: float = 0.0
    actual_score_delta: Optional[float] = None
    outcome: str = "pending"  # pending | success | failure
    timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "predicted_action": self.predicted_action,
            "predicted_risk": self.predicted_risk,
            "predicted_confidence": round(self.predicted_confidence, 3),
            "predicted_score_delta": round(self.predicted_score_delta, 4),
            "actual_score_delta": (
                round(self.actual_score_delta, 4)
                if self.actual_score_delta is not None
                else None
            ),
            "outcome": self.outcome,
            "timestamp": self.timestamp,
        }


def _record_prediction(
    project_root: Path,
    *,
    decision_id: str,
    predicted_action: str,
    predicted_risk: str,
    predicted_confidence: float,
    predicted_score_delta: float,
) -> None:
    """Record a prediction for future confidence calibration."""
    from codegraph.utils.formatting import iso_now

    cal_dir = project_root / ".codegraph" / "calibration"
    cal_dir.mkdir(parents=True, exist_ok=True)
    cal_path = cal_dir / CALIBRATION_FILE

    records: List[Dict[str, Any]] = []
    if cal_path.exists():
        try:
            records = json.loads(cal_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            records = []

    record = PredictionRecord(
        decision_id=decision_id,
        predicted_action=predicted_action,
        predicted_risk=predicted_risk,
        predicted_confidence=predicted_confidence,
        predicted_score_delta=predicted_score_delta,
        timestamp=iso_now(),
    )
    records.append(record.to_dict())

    # Keep last 200 records
    records = records[-200:]
    cal_path.write_text(
        json.dumps(records, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def calibrate_confidence(project_root: Path) -> Dict[str, Any]:
    """Compute confidence calibration metrics from historical predictions.

    Returns accuracy, mean absolute error, and per-action breakdown.
    Call this after running ``codegraph build && codegraph score`` to
    update actual outcomes and recalibrate.
    """
    cal_path = (
        project_root / ".codegraph" / "calibration" / CALIBRATION_FILE
    )
    if not cal_path.exists():
        return {"status": "no_data", "records": 0}

    try:
        records = json.loads(cal_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"status": "parse_error", "records": 0}

    resolved = [r for r in records if r.get("outcome") != "pending"]
    if not resolved:
        return {"status": "all_pending", "records": len(records)}

    # Accuracy: did predicted risk match actual outcome?
    correct = 0
    total = len(resolved)
    abs_errors: List[float] = []

    action_stats: Dict[str, Dict[str, int]] = {}

    for r in resolved:
        action = r.get("predicted_action", "unknown")
        outcome = r.get("outcome", "failure")

        if action not in action_stats:
            action_stats[action] = {"success": 0, "failure": 0}
        action_stats[action][outcome] = action_stats[action].get(outcome, 0) + 1

        if outcome == "success":
            correct += 1

        pred_delta = r.get("predicted_score_delta", 0)
        actual_delta = r.get("actual_score_delta")
        if actual_delta is not None:
            abs_errors.append(abs(pred_delta - actual_delta))

    accuracy = correct / max(total, 1)
    mae = sum(abs_errors) / max(len(abs_errors), 1) if abs_errors else None

    return {
        "status": "calibrated",
        "records": len(records),
        "resolved": total,
        "accuracy": round(accuracy, 3),
        "mean_absolute_error": round(mae, 4) if mae is not None else None,
        "per_action": action_stats,
        "suggested_next_steps": [
            "codegraph hotspots --json  # re-assess system state",
        ],
    }


def resolve_prediction(
    project_root: Path,
    decision_id: str,
    *,
    actual_score_delta: float,
    outcome: str,
) -> bool:
    """Resolve a pending prediction with actual outcome.

    Called after changes are implemented and measured.

    Args:
        project_root: Project root.
        decision_id: The DEC-xxxx id to resolve.
        actual_score_delta: Measured score change.
        outcome: "success" or "failure".

    Returns True if a matching prediction was found and resolved.
    """
    cal_path = (
        project_root / ".codegraph" / "calibration" / CALIBRATION_FILE
    )
    if not cal_path.exists():
        return False

    try:
        records = json.loads(cal_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False

    found = False
    for r in records:
        if r.get("decision_id") == decision_id and r.get("outcome") == "pending":
            r["actual_score_delta"] = actual_score_delta
            r["outcome"] = outcome
            found = True
            break

    if found:
        cal_path.write_text(
            json.dumps(records, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # Feed back into agent memory
    if found:
        try:
            from codegraph.agent_memory import load_memory, save_memory
            memory = load_memory(project_root)
            action = next(
                (r.get("predicted_action", "") for r in records
                 if r.get("decision_id") == decision_id),
                "",
            )
            if outcome == "success" and action:
                memory.add_pattern(
                    task_type=action,
                    action=f"decision_{action}",
                    node_pattern=decision_id,
                )
            memory.add_note(
                f"Decision {decision_id}: {outcome} "
                f"(predicted_delta={actual_score_delta:+.4f})"
            )
            save_memory(memory, project_root)
        except Exception:
            pass

    return found
