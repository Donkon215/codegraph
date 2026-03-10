"""codegraph.architecture_advisor — Architecture reasoning and suggestion engine.

Aggregates graph analytics (risk metrics, cycle detection, subsystem
cohesion, coupling analysis) into actionable architecture suggestions.
Detects god modules, cyclic dependencies, high fan-out, critical nodes,
large subsystems, hidden coupling, and dependency depth issues.

Produces structured advice that can be reviewed by humans or used
by the codegraph planner to generate repair tasks.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from codegraph.index import IndexStore
from codegraph.logging_config import get_logger
from codegraph.models.graph0 import Graph0
from codegraph.models.graph1 import Graph1
from codegraph.models.workflow import Workflow
from codegraph.refactor import detect_cycles
from codegraph.risk_metrics import RiskLevel, compute_risk_metrics
from codegraph.subsystem import detect_subsystems

logger = get_logger("architecture_advisor")


# ── Dataclasses ───────────────────────────────────────────────────────


@dataclass
class ArchSmell:
    """A single architecture smell detected by the advisor."""

    smell_type: str  # god_module, cycle, high_fan_out, critical_node,
    #                  large_subsystem, hidden_coupling, deep_chain
    severity: str = "warning"  # info, warning, error
    node: str = ""
    nodes: List[str] = field(default_factory=list)
    metric_value: float = 0.0
    threshold: float = 0.0
    description: str = ""
    suggestion: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "smell_type": self.smell_type,
            "severity": self.severity,
            "description": self.description,
            "suggestion": self.suggestion,
        }
        if self.node:
            d["node"] = self.node
        if self.nodes:
            d["nodes"] = self.nodes[:20]
        if self.metric_value:
            d["metric_value"] = round(self.metric_value, 3)
        if self.threshold:
            d["threshold"] = round(self.threshold, 3)
        return d


@dataclass
class ArchSuggestion:
    """A concrete architecture improvement suggestion."""

    action: str  # split_module, introduce_interface, break_cycle,
    #               extract_subsystem, reduce_coupling, flag_review
    target: str = ""
    reason: str = ""
    priority: int = 5  # 1=highest, 10=lowest
    source_smell: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "target": self.target,
            "reason": self.reason,
            "priority": self.priority,
            "source_smell": self.source_smell,
        }


@dataclass
class ArchAdvice:
    """Complete architecture advisor report."""

    score: float = 1.0  # 0-1 overall health
    grade: str = "A"
    total_nodes: int = 0
    total_edges: int = 0
    total_files: int = 0
    cycle_count: int = 0
    god_module_count: int = 0
    critical_node_count: int = 0
    large_subsystem_count: int = 0
    avg_fan_in: float = 0.0
    avg_fan_out: float = 0.0
    max_fan_in: int = 0
    max_fan_out: int = 0
    max_dependency_depth: int = 0
    modularity: float = 0.0
    smells: List[ArchSmell] = field(default_factory=list)
    suggestions: List[ArchSuggestion] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": round(self.score, 3),
            "grade": self.grade,
            "total_nodes": self.total_nodes,
            "total_edges": self.total_edges,
            "total_files": self.total_files,
            "cycle_count": self.cycle_count,
            "god_module_count": self.god_module_count,
            "critical_node_count": self.critical_node_count,
            "large_subsystem_count": self.large_subsystem_count,
            "avg_fan_in": round(self.avg_fan_in, 2),
            "avg_fan_out": round(self.avg_fan_out, 2),
            "max_fan_in": self.max_fan_in,
            "max_fan_out": self.max_fan_out,
            "max_dependency_depth": self.max_dependency_depth,
            "modularity": round(self.modularity, 3),
            "smells": [s.to_dict() for s in self.smells],
            "suggestions": [s.to_dict() for s in self.suggestions],
        }

    def save(self, project_root: Path) -> Path:
        """Save advice to .codegraph/architecture/architecture_advice.json."""
        out_dir = project_root / ".codegraph" / "architecture"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "architecture_advice.json"
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return path

    def format(self) -> str:
        lines = [
            f"Architecture Advisor: {self.grade} ({self.score:.0%})",
            f"  Nodes: {self.total_nodes}  Edges: {self.total_edges}  Files: {self.total_files}",
            f"  Fan-in avg={self.avg_fan_in:.1f} max={self.max_fan_in}  "
            f"Fan-out avg={self.avg_fan_out:.1f} max={self.max_fan_out}",
            f"  Modularity: {self.modularity:.3f}  "
            f"Max dependency depth: {self.max_dependency_depth}",
            "",
            f"Smells ({len(self.smells)}):",
            f"  Cycles: {self.cycle_count}",
            f"  God modules: {self.god_module_count}",
            f"  Critical nodes: {self.critical_node_count}",
            f"  Large subsystems: {self.large_subsystem_count}",
        ]
        if self.smells:
            lines.append("")
            lines.append("Top issues:")
            for s in self.smells[:15]:
                label = s.node or ", ".join(s.nodes[:3])
                lines.append(f"  [{s.severity:7s}] {s.smell_type}: {label}")
                lines.append(f"           {s.description}")
        if self.suggestions:
            lines.append("")
            lines.append(f"Suggestions ({len(self.suggestions)}):")
            for s in sorted(self.suggestions, key=lambda x: x.priority):
                lines.append(f"  P{s.priority} [{s.action}] {s.target}")
                lines.append(f"     {s.reason}")
        return "\n".join(lines)


# ── Score grading ─────────────────────────────────────────────────────

def _compute_grade(score: float) -> str:
    if score >= 0.9:
        return "A"
    if score >= 0.8:
        return "B"
    if score >= 0.7:
        return "C"
    if score >= 0.5:
        return "D"
    return "F"


# ── Main advisor function ────────────────────────────────────────────


def advise_architecture(
    graph0: Graph0,
    index: IndexStore,
    *,
    god_module_threshold: int = 30,
    fan_in_threshold: int = 20,
    fan_out_threshold: int = 15,
    subsystem_size_threshold: int = 200,
    depth_threshold: int = 10,
    cycle_penalty: float = 0.10,
    god_module_penalty: float = 0.05,
    critical_penalty: float = 0.03,
    large_sub_penalty: float = 0.03,
) -> ArchAdvice:
    """Run full architecture analysis and produce actionable advice.

    Aggregates:
    - Risk metrics (fan-in, fan-out, betweenness centrality)
    - Cycle detection (Tarjan SCC)
    - Subsystem detection (Louvain clustering)
    - God module detection
    - Dependency depth analysis
    - Cross-subsystem hidden coupling
    """
    advice = ArchAdvice()
    advice.total_nodes = len(graph0.nodes)
    advice.total_files = len(set(n.file for n in graph0.nodes))

    conn = index._get_conn()

    # Count edges
    edge_count = conn.execute("SELECT COUNT(*) FROM callees").fetchone()[0]
    advice.total_edges = edge_count

    # 1. Risk metrics
    risk = compute_risk_metrics(index)
    advice.avg_fan_in = risk.avg_fan_in
    advice.avg_fan_out = risk.avg_fan_out
    advice.max_fan_in = risk.max_fan_in
    advice.max_fan_out = risk.max_fan_out
    advice.critical_node_count = len(risk.critical_nodes)

    risk_map = {m.node_id: m for m in risk.node_metrics}

    # 2. Detect god modules
    file_nodes: Dict[str, List[str]] = defaultdict(list)
    for node in graph0.nodes:
        file_nodes[node.file].append(node.id)

    for filepath, node_ids in file_nodes.items():
        if len(node_ids) > god_module_threshold:
            advice.god_module_count += 1
            advice.smells.append(ArchSmell(
                smell_type="god_module",
                severity="warning",
                node=filepath,
                metric_value=len(node_ids),
                threshold=god_module_threshold,
                description=f"{filepath} has {len(node_ids)} nodes (threshold: {god_module_threshold})",
                suggestion=f"Split {filepath} into smaller focused modules",
            ))
            advice.suggestions.append(ArchSuggestion(
                action="split_module",
                target=filepath,
                reason=f"Module has {len(node_ids)} nodes, exceeding threshold of {god_module_threshold}",
                priority=3,
                source_smell="god_module",
            ))

    # 3. Critical/high fan-in nodes
    for m in risk.node_metrics:
        if m.fan_in >= fan_in_threshold:
            advice.smells.append(ArchSmell(
                smell_type="high_fan_in",
                severity="warning" if m.fan_in < fan_in_threshold * 2 else "error",
                node=m.node_id,
                metric_value=m.fan_in,
                threshold=fan_in_threshold,
                description=f"{m.node_id} has fan-in={m.fan_in} (threshold: {fan_in_threshold})",
                suggestion=f"Consider introducing an interface or facade for {m.node_id}",
            ))
        if m.fan_out >= fan_out_threshold:
            advice.smells.append(ArchSmell(
                smell_type="high_fan_out",
                severity="warning",
                node=m.node_id,
                metric_value=m.fan_out,
                threshold=fan_out_threshold,
                description=f"{m.node_id} has fan-out={m.fan_out} (threshold: {fan_out_threshold})",
                suggestion=f"Reduce dependencies of {m.node_id} by extracting helper modules",
            ))
        if m.risk_level == RiskLevel.CRITICAL:
            advice.smells.append(ArchSmell(
                smell_type="critical_node",
                severity="error",
                node=m.node_id,
                metric_value=m.betweenness,
                description=(
                    f"{m.node_id} is critical: fan-in={m.fan_in} "
                    f"fan-out={m.fan_out} betweenness={m.betweenness:.4f}"
                ),
                suggestion=f"Reduce centrality of {m.node_id} — high blast radius if changed",
            ))

    # 4. Cycle detection
    cycles = detect_cycles(index)
    advice.cycle_count = len(cycles)
    for cycle in cycles:
        sev = "error" if cycle.size >= 5 else "warning"
        advice.smells.append(ArchSmell(
            smell_type="cycle",
            severity=sev,
            nodes=cycle.nodes,
            metric_value=cycle.size,
            description=(
                f"Cycle of {cycle.size} nodes across "
                f"{len(cycle.files_involved)} file(s)"
            ),
            suggestion="Break cycle by introducing an interface or inverting a dependency",
        ))
        advice.suggestions.append(ArchSuggestion(
            action="break_cycle",
            target=", ".join(cycle.files_involved[:3]),
            reason=f"Cycle of {cycle.size} nodes across {len(cycle.files_involved)} files",
            priority=2,
            source_smell="cycle",
        ))

    # 5. Subsystem analysis
    sub_report = detect_subsystems(graph0, index)
    advice.modularity = sub_report.modularity_score

    for sub in sub_report.subsystems:
        if len(sub.nodes) > subsystem_size_threshold:
            advice.large_subsystem_count += 1
            advice.smells.append(ArchSmell(
                smell_type="large_subsystem",
                severity="warning",
                node=sub.name,
                metric_value=len(sub.nodes),
                threshold=subsystem_size_threshold,
                description=(
                    f"Subsystem '{sub.name}' has {len(sub.nodes)} nodes "
                    f"(threshold: {subsystem_size_threshold})"
                ),
                suggestion=f"Split subsystem '{sub.name}' into smaller cohesive units",
            ))
            advice.suggestions.append(ArchSuggestion(
                action="extract_subsystem",
                target=sub.name,
                reason=f"Subsystem has {len(sub.nodes)} nodes, exceeding threshold of {subsystem_size_threshold}",
                priority=4,
                source_smell="large_subsystem",
            ))

        if sub.cohesion < 0.3 and len(sub.nodes) > 5:
            advice.smells.append(ArchSmell(
                smell_type="low_cohesion",
                severity="info",
                node=sub.name,
                metric_value=sub.cohesion,
                threshold=0.3,
                description=(
                    f"Subsystem '{sub.name}' has low cohesion "
                    f"({sub.cohesion:.2f})"
                ),
                suggestion=f"Review boundaries of '{sub.name}' — may contain unrelated modules",
            ))

    # 6. Hidden coupling: cross-layer edges
    _detect_hidden_coupling(graph0, index, advice)

    # 7. Dependency depth
    advice.max_dependency_depth = _compute_max_depth(index)
    if advice.max_dependency_depth > depth_threshold:
        advice.smells.append(ArchSmell(
            smell_type="deep_chain",
            severity="warning",
            metric_value=advice.max_dependency_depth,
            threshold=depth_threshold,
            description=(
                f"Maximum dependency chain depth is {advice.max_dependency_depth} "
                f"(threshold: {depth_threshold})"
            ),
            suggestion="Flatten deep call chains to reduce latency and debugging complexity",
        ))

    # Compute overall score
    score = 1.0
    score -= min(0.3, advice.cycle_count * cycle_penalty)
    score -= min(0.2, advice.god_module_count * god_module_penalty)
    score -= min(0.15, advice.critical_node_count * critical_penalty)
    score -= min(0.1, advice.large_subsystem_count * large_sub_penalty)
    if advice.modularity < 0.3:
        score -= 0.05
    advice.score = max(0.0, score)
    advice.grade = _compute_grade(advice.score)

    # Sort smells: errors first, then warnings, then info
    severity_order = {"error": 0, "warning": 1, "info": 2}
    advice.smells.sort(key=lambda s: severity_order.get(s.severity, 3))

    logger.info(
        "Architecture advice: %s (%s) — %d smells, %d suggestions",
        advice.grade, f"{advice.score:.0%}",
        len(advice.smells), len(advice.suggestions),
    )
    return advice


# ── Hidden coupling detection ─────────────────────────────────────────


def _detect_hidden_coupling(
    graph0: Graph0, index: IndexStore, advice: ArchAdvice,
) -> None:
    """Detect cross-layer coupling (e.g. test → production internals)."""
    conn = index._get_conn()
    callee_rows = conn.execute("SELECT node_id, callee_id FROM callees").fetchall()

    node_layer: Dict[str, str] = {}
    for node in graph0.nodes:
        if node.file.startswith("tests/") or node.file.startswith("test_"):
            node_layer[node.id] = "test"
        elif node.file.startswith("benchmarks/") or node.file.startswith("examples/"):
            node_layer[node.id] = "support"
        else:
            node_layer[node.id] = "production"

    # Track test → production internal calls (not public API)
    for src, tgt in callee_rows:
        src_layer = node_layer.get(src, "")
        tgt_layer = node_layer.get(tgt, "")

        # Support code calling production internals (private functions)
        if src_layer == "support" and tgt_layer == "production":
            tgt_name = tgt.split("::")[-1] if "::" in tgt else ""
            if tgt_name.startswith("_") and not tgt_name.startswith("__"):
                advice.smells.append(ArchSmell(
                    smell_type="hidden_coupling",
                    severity="info",
                    node=src,
                    nodes=[src, tgt],
                    description=f"Support code {src} calls private {tgt}",
                    suggestion="Use public API instead of internal implementation",
                ))


# ── Dependency depth via BFS ──────────────────────────────────────────


def _compute_max_depth(index: IndexStore) -> int:
    """Compute maximum dependency chain depth via BFS from root nodes."""
    conn = index._get_conn()
    callee_rows = conn.execute("SELECT node_id, callee_id FROM callees").fetchall()

    adj: Dict[str, List[str]] = defaultdict(list)
    has_caller: Set[str] = set()
    all_nodes: Set[str] = set()

    for src, tgt in callee_rows:
        adj[src].append(tgt)
        has_caller.add(tgt)
        all_nodes.add(src)
        all_nodes.add(tgt)

    # Root nodes: nodes with no callers
    roots = all_nodes - has_caller
    if not roots:
        return 0

    # BFS from a sample of roots to find max depth
    max_depth = 0
    sample = sorted(roots)[:50]  # limit for performance

    for root in sample:
        visited: Set[str] = set()
        queue: List[Tuple[str, int]] = [(root, 0)]
        visited.add(root)

        while queue:
            node, depth = queue.pop(0)
            if depth > max_depth:
                max_depth = depth
            if depth > 50:  # safety limit
                break
            for neighbor in adj.get(node, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, depth + 1))

    return max_depth


# ── Workflow intent enrichment ────────────────────────────────────────


def enrich_workflow_with_intents(
    workflow: Workflow, graph1: Graph1,
) -> Workflow:
    """Add intent annotations to workflow edges from graph1.

    For each edge, looks up source and target intents from graph1
    and adds them as metadata on the edge. Returns a new enriched
    Workflow suitable for serialization.
    """
    from codegraph.models.workflow import WorkflowEdge

    enriched_edges = []
    for edge in workflow.edges:
        # Build enriched edge dict with intent fields
        d = edge.to_dict()
        src_node = graph1.get_node(edge.source)
        tgt_node = graph1.get_node(edge.target)
        if src_node and src_node.intent:
            d["source_intent"] = src_node.intent
        if tgt_node and tgt_node.intent:
            d["target_intent"] = tgt_node.intent
        enriched_edges.append(d)

    # Return enriched workflow data as dict (since WorkflowEdge
    # doesn't have intent fields, we return raw dicts for serialization)
    enriched = Workflow(
        format_version=workflow.format_version,
        built_at=workflow.built_at,
        level=workflow.level,
        edges=workflow.edges,  # keep original edges for lookups
        metadata={
            **workflow.metadata,
            "intent_enriched": True,
        },
    )
    # Store enriched edge data for serialization
    enriched._enriched_edge_dicts = enriched_edges  # type: ignore[attr-defined]
    return enriched


def save_enriched_workflow(
    workflow: Workflow,
    graph1: Graph1,
    project_root: Path,
) -> Path:
    """Enrich workflow with intents and save to enriched_workflow.json."""
    enriched = enrich_workflow_with_intents(workflow, graph1)

    out_dir = project_root / ".codegraph" / "workflow"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "enriched_workflow.json"

    edge_dicts = getattr(enriched, "_enriched_edge_dicts", [e.to_dict() for e in enriched.edges])

    data = {
        "format_version": enriched.format_version,
        "built_at": enriched.built_at,
        "level": enriched.level,
        "intent_enriched": True,
        "edges": edge_dicts,
    }
    if enriched.metadata:
        data["metadata"] = enriched.metadata

    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    logger.info("Saved enriched workflow (%d edges) → %s", len(edge_dicts), path)
    return path
