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

from codegraph.copilot_context import CONTEXT_DIR, CopilotContext, build_copilot_context
from codegraph.logging_config import get_logger

logger = get_logger("copilot_context_builder")

MAX_CONTEXT_BYTES = 100 * 1024
PUBLISHED_CONTEXT_FILE = "copilot_context.json"
STAGED_CONTEXT_FILE = "copilot_context.staged.json"


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
    architecture_queries: List[str] = field(default_factory=list)
    refactor_suggestions: List[Dict[str, Any]] = field(default_factory=list)
    architecture_stability: Dict[str, Any] = field(default_factory=dict)
    architecture_patterns: Dict[str, Any] = field(default_factory=dict)
    architecture_violations: List[Dict[str, Any]] = field(default_factory=list)
    subsystem_context: Dict[str, Any] = field(default_factory=dict)

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
        if self.architecture_queries:
            d["architecture_queries"] = self.architecture_queries
        if self.refactor_suggestions:
            d["refactor_suggestions"] = self.refactor_suggestions
        if self.architecture_stability:
            d["architecture_stability"] = self.architecture_stability
        if self.architecture_patterns:
            d["architecture_patterns"] = self.architecture_patterns
        if self.architecture_violations:
            d["architecture_violations"] = self.architecture_violations
        if self.subsystem_context:
            d["subsystem_context"] = self.subsystem_context
        return d

    def save(self, project_root: Path) -> Path:
        context_dir = project_root / ".codegraph" / CONTEXT_DIR
        context_dir.mkdir(parents=True, exist_ok=True)

        payload = _build_capped_payload(self)
        staged_path = context_dir / STAGED_CONTEXT_FILE
        staged_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        publish_status_path = context_dir / "copilot_context_publish_status.json"
        publish_status = {
            "published": False,
            "reason": "proof_not_proven_safe",
            "proof_status": self.proof_status.get("status", "UNKNOWN"),
            "staged_path": str(staged_path),
            "size_bytes": len(json.dumps(payload, ensure_ascii=False).encode("utf-8")),
        }

        if _is_proven_safe(self.proof_status):
            published_path = context_dir / PUBLISHED_CONTEXT_FILE
            published_path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            publish_status = {
                "published": True,
                "reason": "proof_proven_safe",
                "proof_status": self.proof_status.get("status", "UNKNOWN"),
                "published_path": str(published_path),
                "staged_path": str(staged_path),
                "size_bytes": len(json.dumps(payload, ensure_ascii=False).encode("utf-8")),
            }
            publish_status_path.write_text(
                json.dumps(publish_status, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            return published_path

        publish_status_path.write_text(
            json.dumps(publish_status, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return staged_path

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

        if self.refactor_suggestions:
            lines.append(f"\nRefactor Suggestions: {len(self.refactor_suggestions)}")
        if self.architecture_patterns:
            primary = self.architecture_patterns.get("primary_pattern", "unknown")
            lines.append(f"Architecture Pattern: {primary}")
        if self.architecture_violations:
            lines.append(f"Architecture Violations: {len(self.architecture_violations)}")

        return "\n".join(lines)


def build_enriched_context(
    project_root: Path,
    *,
    affected_node: str = "",
    affected_file: str = "",
) -> EnrichedCopilotContext:
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

    # 8. Common architecture queries
    ctx.architecture_queries = [
        "SELECT services WHERE depends_on(PaymentService)",
        "SELECT frontend_components WHERE calls_api('/api/orders')",
        "SELECT modules WHERE in_layer(service)",
        "SELECT cycles WHERE in_layer(service)",
        "SELECT events WHERE produced_by(OrderService)",
        "SELECT smells WHERE type='god_module'",
    ]

    # 9. Refactor suggestions and structured violations
    try:
        from codegraph.architecture_refactor_planner import generate_refactor_plan

        plan = generate_refactor_plan(project_root, max_items=8)
        ctx.refactor_suggestions = plan.get("refactor_plan", [])
        ctx.architecture_violations = plan.get("architecture_violations", [])
    except Exception:
        ctx.refactor_suggestions = []
        ctx.architecture_violations = []

    # 10. Architecture stability (churn)
    ctx.architecture_stability = _build_architecture_stability(project_root)

    # 11. Pattern summary
    ctx.architecture_patterns = _load_architecture_patterns(project_root)

    # 12. Optional subsystem-aware context (best-effort)
    ctx.subsystem_context = _build_subsystem_context(
        project_root,
        affected_node=affected_node,
        affected_file=affected_file,
    )

    return ctx


def _build_subsystem_context(
    project_root: Path,
    *,
    affected_node: str = "",
    affected_file: str = "",
) -> Dict[str, Any]:
    try:
        from codegraph.architecture_graph import ArchitectureGraph
        from codegraph.subsystem_extractor import extract_subsystem
        from codegraph.subsystem_context_builder import build_subsystem_context

        graph = ArchitectureGraph.load(project_root)
        if not graph.nodes:
            return {}

        root_node = affected_node.strip()
        if not root_node and affected_file:
            target_file = affected_file.replace("\\", "/")
            for node in graph.nodes:
                if str(node.get("file", "")) == target_file:
                    root_node = str(node.get("id", ""))
                    break
        if not root_node:
            root_node = str(graph.nodes[0].get("id", ""))
        if not root_node:
            return {}

        subsystem = extract_subsystem(graph, root_node, depth=2, max_nodes=200)
        subsystem_context = build_subsystem_context(project_root, root_node, depth=2, max_nodes=200)

        return {
            "subsystem": root_node,
            "architecture_slice": {
                "nodes": len(subsystem.nodes),
                "edges": len(subsystem.edges),
                "boundary_nodes": len(subsystem.boundary_nodes),
            },
            "smells": subsystem_context.smells[:10],
            "refactor_options": subsystem_context.refactor_suggestions[:5],
        }
    except Exception:
        return {}


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


def _build_architecture_stability(project_root: Path) -> Dict[str, Any]:
    graph0_path = project_root / ".codegraph" / "graphs" / "graph0.json"
    graph1_path = project_root / ".codegraph" / "graphs" / "graph1.json"
    history_path = project_root / ".codegraph" / "architecture" / "architecture_history.json"

    changed_nodes = 0
    top_churn_modules: List[Dict[str, Any]] = []

    try:
        g0 = json.loads(graph0_path.read_text(encoding="utf-8")) if graph0_path.exists() else {}
        g1 = json.loads(graph1_path.read_text(encoding="utf-8")) if graph1_path.exists() else {}
        g0_nodes = {n.get("id", ""): n for n in g0.get("nodes", [])}
        g1_nodes = g1.get("nodes", [])

        churn_by_module: Dict[str, int] = {}
        for node in g1_nodes:
            node_id = node.get("id", "")
            if not node_id:
                continue
            g0_node = g0_nodes.get(node_id)
            if not g0_node:
                continue
            if node.get("intent_body_hash", "") and node.get("intent_body_hash", "") != g0_node.get("body_hash", ""):
                changed_nodes += 1
                module = node_id.split("::", 1)[0]
                churn_by_module[module] = churn_by_module.get(module, 0) + 1

        top_churn_modules = [
            {"module": module, "changes": count}
            for module, count in sorted(churn_by_module.items(), key=lambda x: -x[1])[:10]
        ]
    except Exception:
        pass

    score_trend: Dict[str, Any] = {}
    if history_path.exists():
        try:
            history = json.loads(history_path.read_text(encoding="utf-8"))
            entries = history.get("entries", [])
            if entries:
                last = entries[-1]
                prev = entries[-2] if len(entries) >= 2 else None
                score_trend = {
                    "latest_cycles": last.get("cycles_count", 0),
                    "latest_coupling_index": last.get("coupling_index", 0.0),
                    "delta_cycles": (last.get("cycles_count", 0) - prev.get("cycles_count", 0)) if prev else 0,
                }
        except Exception:
            pass

    return {
        "changed_intent_nodes": changed_nodes,
        "top_churn_modules": top_churn_modules,
        "score_trend": score_trend,
    }


def _load_architecture_patterns(project_root: Path) -> Dict[str, Any]:
    pattern_path = project_root / ".codegraph" / "architecture" / "architecture_patterns.json"
    if not pattern_path.exists():
        return {}
    try:
        data = json.loads(pattern_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}

    patterns = data.get("patterns", [])
    compact_patterns = [
        {
            "architecture_type": p.get("architecture_type", ""),
            "confidence": p.get("confidence", 0.0),
            "consistency": p.get("consistency", 0.0),
        }
        for p in patterns[:10]
    ]

    return {
        "primary_pattern": data.get("primary_pattern", "unknown"),
        "patterns": compact_patterns,
    }


def _is_proven_safe(proof_status: Dict[str, Any]) -> bool:
    return str(proof_status.get("status", "")).strip().upper() == "PROVEN_SAFE"


def _build_capped_payload(ctx: EnrichedCopilotContext) -> Dict[str, Any]:
    payload = ctx.to_dict()
    payload["intelligence_summary"] = _summarize_intelligence(ctx)

    _apply_base_caps(payload)
    payload = _shrink_to_size(payload, MAX_CONTEXT_BYTES)
    payload["publish_constraints"] = {
        "max_bytes": MAX_CONTEXT_BYTES,
        "proof_required": "PROVEN_SAFE",
        "actual_bytes": len(json.dumps(payload, ensure_ascii=False).encode("utf-8")),
    }
    return payload


def _summarize_intelligence(ctx: EnrichedCopilotContext) -> Dict[str, Any]:
    base = ctx.base_context

    smells = [
        {
            "type": s.get("smell_type", ""),
            "severity": s.get("severity", ""),
            "where": s.get("location", s.get("module", "")),
        }
        for s in base.architecture_smells[:20]
    ]

    policies = [
        {
            "policy_id": p.get("policy_id", ""),
            "name": p.get("name", ""),
            "action": p.get("action", ""),
        }
        for p in base.active_policies[:20]
    ]

    refactors = [
        {
            "strategy": r.get("strategy", ""),
            "targets": r.get("target_modules", [])[:4],
            "risk": r.get("risk", r.get("risk_estimate", "")),
        }
        for r in base.recommended_refactors[:20]
    ]

    rankings = [
        {
            "strategy": s.get("strategy", ""),
            "effectiveness": s.get("effectiveness", 0),
        }
        for s in base.strategy_rankings[:20]
    ]

    return {
        "smells": smells,
        "active_policies": policies,
        "recommended_refactors": refactors,
        "strategy_rankings": rankings,
        "refactor_suggestions": ctx.refactor_suggestions[:10],
        "architecture_patterns": ctx.architecture_patterns,
        "stability": ctx.architecture_stability,
        "architecture_violations": ctx.architecture_violations[:20],
    }


def _apply_base_caps(payload: Dict[str, Any]) -> None:
    if "active_tasks" in payload and isinstance(payload["active_tasks"], list):
        payload["active_tasks"] = payload["active_tasks"][:50]

    if "recent_decisions" in payload and isinstance(payload["recent_decisions"], list):
        payload["recent_decisions"] = payload["recent_decisions"][:25]

    if "architecture_smells" in payload and isinstance(payload["architecture_smells"], list):
        payload["architecture_smells"] = payload["architecture_smells"][:50]

    if "recommended_refactors" in payload and isinstance(payload["recommended_refactors"], list):
        payload["recommended_refactors"] = payload["recommended_refactors"][:25]

    if "strategy_rankings" in payload and isinstance(payload["strategy_rankings"], list):
        payload["strategy_rankings"] = payload["strategy_rankings"][:25]

    if "active_policies" in payload and isinstance(payload["active_policies"], list):
        payload["active_policies"] = payload["active_policies"][:50]

    if "refactor_suggestions" in payload and isinstance(payload["refactor_suggestions"], list):
        payload["refactor_suggestions"] = payload["refactor_suggestions"][:15]

    if "architecture_violations" in payload and isinstance(payload["architecture_violations"], list):
        payload["architecture_violations"] = payload["architecture_violations"][:25]


def _shrink_to_size(payload: Dict[str, Any], max_bytes: int) -> Dict[str, Any]:
    def size_of(data: Dict[str, Any]) -> int:
        return len(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    if size_of(payload) <= max_bytes:
        return payload

    keys_to_trim = [
        "active_tasks",
        "recent_decisions",
        "architecture_smells",
        "recommended_refactors",
        "strategy_rankings",
        "active_policies",
        "policy_rules",
        "refactor_suggestions",
        "architecture_violations",
        "architecture_queries",
    ]

    shrunk = dict(payload)
    for key in keys_to_trim:
        value = shrunk.get(key)
        if not isinstance(value, list) or len(value) <= 5:
            continue

        current = value
        while len(current) > 5 and size_of(shrunk) > max_bytes:
            current = current[: max(5, len(current) // 2)]
            shrunk[key] = current

        if size_of(shrunk) <= max_bytes:
            break

    if size_of(shrunk) > max_bytes:
        shrunk["active_tasks"] = []
        shrunk["recent_decisions"] = []
        shrunk["architecture_smells"] = []
        shrunk["recommended_refactors"] = []
        shrunk["strategy_rankings"] = []
        shrunk["active_policies"] = []
        shrunk["policy_rules"] = []
        shrunk["refactor_suggestions"] = []
        shrunk["architecture_violations"] = []
        shrunk["architecture_queries"] = []

    return shrunk
