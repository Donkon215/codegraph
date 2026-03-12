"""codegraph.copilot_context_builder — Structured context builder for Copilot.

Enhanced context builder that provides Copilot with full architecture-aware
context including:
  - Subsystem definitions from system.json
  - Architecture constraints and forbidden dependencies
  - Dependency graph summary
  - Workflow graph overview
  - Architecture risks and current smells
  - Simulator rules (layer rules, subsystem constraints)
  - Current architecture score and grade
  - Architecture delta (if available)
  - Proof status (if available)

This wraps and extends the existing CopilotContext with additional
decision-support data that prevents architecture-breaking decisions.

CLI command: codegraph context

Output: .codegraph/context/copilot_context.json
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from codegraph.copilot_context import CopilotContext, build_copilot_context
from codegraph.logging_config import get_logger

logger = get_logger("copilot_context_builder")


@dataclass
class SimulatorRules:
    """Rules that the simulator enforces."""

    layer_rules: List[Dict[str, str]] = field(default_factory=list)
    forbidden_subsystem_deps: List[Dict[str, str]] = field(default_factory=list)
    dependency_limits: List[Dict[str, Any]] = field(default_factory=list)
    safety_tiers: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "layer_rules": self.layer_rules,
            "forbidden_subsystem_deps": self.forbidden_subsystem_deps,
            "dependency_limits": self.dependency_limits,
            "safety_tiers": self.safety_tiers,
        }


@dataclass
class GraphSummary:
    """Condensed dependency graph summary."""

    total_nodes: int = 0
    total_edges: int = 0
    modules: int = 0
    functions: int = 0
    classes: int = 0
    orphan_nodes: int = 0
    avg_fan_in: float = 0.0
    avg_fan_out: float = 0.0
    max_fan_in: int = 0
    max_fan_out: int = 0
    cycle_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_nodes": self.total_nodes,
            "total_edges": self.total_edges,
            "modules": self.modules,
            "functions": self.functions,
            "classes": self.classes,
            "orphan_nodes": self.orphan_nodes,
            "avg_fan_in": round(self.avg_fan_in, 2),
            "avg_fan_out": round(self.avg_fan_out, 2),
            "max_fan_in": self.max_fan_in,
            "max_fan_out": self.max_fan_out,
            "cycle_count": self.cycle_count,
        }


@dataclass
class EnrichedCopilotContext:
    """Full enriched context for Copilot with decision-support data."""

    base_context: CopilotContext = field(default_factory=CopilotContext)
    graph_summary: GraphSummary = field(default_factory=GraphSummary)
    simulator_rules: SimulatorRules = field(default_factory=SimulatorRules)
    architecture_delta: Dict[str, Any] = field(default_factory=dict)
    proof_status: Dict[str, Any] = field(default_factory=dict)
    refactor_budget: Dict[str, int] = field(default_factory=dict)
    authority_levels: Dict[str, List[str]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = self.base_context.to_dict()
        d["graph_summary"] = self.graph_summary.to_dict()
        d["simulator_rules"] = self.simulator_rules.to_dict()
        if self.architecture_delta:
            d["architecture_delta"] = self.architecture_delta
        if self.proof_status:
            d["proof_status"] = self.proof_status
        if self.refactor_budget:
            d["refactor_budget"] = self.refactor_budget
        if self.authority_levels:
            d["authority_levels"] = self.authority_levels
        return d

    def save(self, project_root: Path) -> Path:
        return self.base_context.save(project_root)

    def format(self) -> str:
        lines = [self.base_context.format()]
        lines.append(f"\nGraph Summary:")
        gs = self.graph_summary
        lines.append(f"  Nodes: {gs.total_nodes} ({gs.functions} functions, "
                      f"{gs.classes} classes, {gs.modules} modules)")
        lines.append(f"  Edges: {gs.total_edges}")
        lines.append(f"  Orphans: {gs.orphan_nodes}")
        lines.append(f"  Fan: in avg={gs.avg_fan_in:.1f} max={gs.max_fan_in}, "
                      f"out avg={gs.avg_fan_out:.1f} max={gs.max_fan_out}")
        lines.append(f"  Cycles: {gs.cycle_count}")

        sr = self.simulator_rules
        if sr.layer_rules:
            lines.append(f"\nSimulator Rules:")
            lines.append(f"  Layer rules: {len(sr.layer_rules)}")
            lines.append(f"  Forbidden subsystem deps: {len(sr.forbidden_subsystem_deps)}")
            lines.append(f"  Dependency limits: {len(sr.dependency_limits)}")

        if self.architecture_delta:
            risk = self.architecture_delta.get("risk_estimate", "?")
            changes = self.architecture_delta.get("total_changes", 0)
            lines.append(f"\nPending Delta: {changes} changes (risk={risk})")

        if self.proof_status:
            status = self.proof_status.get("status", "?")
            lines.append(f"\nProof Status: {status}")

        if self.refactor_budget:
            lines.append(f"\nRefactor Budget:")
            for k, v in self.refactor_budget.items():
                lines.append(f"  {k}: {v}")

        return "\n".join(lines)


def build_enriched_context(project_root: Path) -> EnrichedCopilotContext:
    """Build a full architecture-aware context for Copilot.

    Combines the base CopilotContext with graph metrics,
    simulator rules, delta, and proof status.
    """
    ctx = EnrichedCopilotContext()

    # 1. Base context (existing)
    ctx.base_context = build_copilot_context(project_root)

    # 2. Graph summary
    ctx.graph_summary = _build_graph_summary(project_root)

    # 3. Simulator rules
    ctx.simulator_rules = _build_simulator_rules(project_root)

    # 4. Architecture delta (if available)
    delta_path = project_root / ".codegraph" / "architecture_delta.json"
    if delta_path.exists():
        try:
            ctx.architecture_delta = json.loads(
                delta_path.read_text(encoding="utf-8")
            )
        except (json.JSONDecodeError, OSError):
            pass

    # 5. Proof status (if available)
    proof_path = project_root / ".codegraph" / "proofs" / "latest_proof.json"
    if proof_path.exists():
        try:
            ctx.proof_status = json.loads(
                proof_path.read_text(encoding="utf-8")
            )
        except (json.JSONDecodeError, OSError):
            pass

    # 6. Refactor budget
    ctx.refactor_budget = _load_refactor_budget(project_root)

    # 7. Authority levels
    ctx.authority_levels = {
        "auto": ["repair_import", "add_intent", "connect_call", "flag_review"],
        "review": ["module_split", "fan_out_reduction", "cycle_break",
                    "component_extraction", "dependency_inversion"],
        "human": ["subsystem_merge", "subsystem_delete", "rewrite",
                   "modify_constraints", "modify_subsystem_edges"],
    }

    return ctx


def _build_graph_summary(project_root: Path) -> GraphSummary:
    """Build graph metrics summary from graph0 and workflow."""
    summary = GraphSummary()

    g0_path = project_root / ".codegraph" / "graphs" / "graph0.json"
    if g0_path.exists():
        try:
            g0 = json.loads(g0_path.read_text(encoding="utf-8"))
            nodes = g0.get("nodes", [])
            summary.total_nodes = len(nodes)
            for node in nodes:
                nt = node.get("type", "")
                if nt == "function":
                    summary.functions += 1
                elif nt == "class":
                    summary.classes += 1
                elif nt == "module":
                    summary.modules += 1
        except (json.JSONDecodeError, OSError):
            pass

    wf_path = project_root / ".codegraph" / "workflow" / "workflow.json"
    if wf_path.exists():
        try:
            wf = json.loads(wf_path.read_text(encoding="utf-8"))
            edges = wf.get("edges", [])
            summary.total_edges = len(edges)

            # Compute fan-in/fan-out
            fan_in: Dict[str, int] = {}
            fan_out: Dict[str, int] = {}
            nodes_in_edges: set[str] = set()
            for edge in edges:
                src = edge.get("source", "")
                tgt = edge.get("target", "")
                if src:
                    fan_out[src] = fan_out.get(src, 0) + 1
                    nodes_in_edges.add(src)
                if tgt:
                    fan_in[tgt] = fan_in.get(tgt, 0) + 1
                    nodes_in_edges.add(tgt)

            if fan_in:
                summary.max_fan_in = max(fan_in.values())
                summary.avg_fan_in = sum(fan_in.values()) / len(fan_in)
            if fan_out:
                summary.max_fan_out = max(fan_out.values())
                summary.avg_fan_out = sum(fan_out.values()) / len(fan_out)

            # Orphan count
            summary.orphan_nodes = max(
                0, summary.total_nodes - len(nodes_in_edges)
            )
        except (json.JSONDecodeError, OSError):
            pass

    # Cycle count from advice
    advice_path = (project_root / ".codegraph" / "architecture"
                   / "architecture_advice.json")
    if advice_path.exists():
        try:
            advice = json.loads(advice_path.read_text(encoding="utf-8"))
            cycles = advice.get("cycles", [])
            summary.cycle_count = len(cycles) if isinstance(cycles, list) else int(cycles)
        except (json.JSONDecodeError, OSError, ValueError):
            pass

    return summary


def _build_simulator_rules(project_root: Path) -> SimulatorRules:
    """Extract simulator rules from system.json and suggested_workflow."""
    rules = SimulatorRules()

    # System.json constraints
    system_path = project_root / ".codegraph" / "architecture" / "system.json"
    if system_path.exists():
        try:
            system = json.loads(system_path.read_text(encoding="utf-8"))
            for constraint in system.get("constraints", []):
                if constraint.get("type") == "forbidden_dependency":
                    rules.forbidden_subsystem_deps.append({
                        "source": constraint.get("source", ""),
                        "target": constraint.get("target", ""),
                        "reason": constraint.get("reason", ""),
                    })
        except (json.JSONDecodeError, OSError):
            pass

    # Suggested workflow rules
    sw_path = (project_root / ".codegraph" / "workflow"
               / "suggested_workflow.json")
    if sw_path.exists():
        try:
            sw = json.loads(sw_path.read_text(encoding="utf-8"))
            for rule in sw.get("rules", []):
                rt = rule.get("type", "")
                if rt == "layer_boundary":
                    rules.layer_rules.append({
                        "source": rule.get("source", ""),
                        "target": rule.get("target", ""),
                    })
                elif rt == "dependency_limit":
                    rules.dependency_limits.append({
                        "module": rule.get("source", ""),
                        "max_fan_out": rule.get("max_fan_out", 20),
                    })
        except (json.JSONDecodeError, OSError):
            pass

    # Safety tiers
    from codegraph.arch_evolution import STRATEGY_TIERS
    rules.safety_tiers = dict(STRATEGY_TIERS)

    return rules


def _load_refactor_budget(project_root: Path) -> Dict[str, int]:
    """Load refactor budget from agent_config or return defaults."""
    config_path = project_root / ".codegraph" / "agent_config.json"
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            budget = config.get("refactor_budget", {})
            if budget:
                return budget
        except (json.JSONDecodeError, OSError):
            pass

    # Defaults
    return {
        "max_files_modified": 12,
        "max_edges_added": 25,
        "max_edges_removed": 25,
        "max_nodes_added": 15,
        "max_nodes_removed": 10,
    }
