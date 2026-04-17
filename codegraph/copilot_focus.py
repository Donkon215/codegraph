"""codegraph.copilot_focus — FocusContext: surgical zoom on a file or node.

Provides fast, minimal architecture context for Copilot's in-loop use.
Answers: "What do I need to know about THIS specific file/node before making
a change?"

Extracted from copilot_context_builder.py for single-responsibility.
Re-exported from copilot_context_builder for backward compatibility.

CLI command: codegraph focus <target> [--depth N] [--json]
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from codegraph.logging_config import get_logger
from codegraph.utils.json_cache import load_json_cached

logger = get_logger("copilot_focus")


@dataclass
class FocusContext:
    """Minimal, focused context for a single file or node.

    Designed for Copilot's in-loop use: fast to build, small payload,
    contains only what's needed to make a decision about a specific area.
    """

    target: str = ""
    target_type: str = ""  # file | node | subsystem
    nodes: List[Dict[str, Any]] = field(default_factory=list)
    edges: List[Dict[str, Any]] = field(default_factory=list)
    violations: List[str] = field(default_factory=list)
    smells: List[Dict[str, Any]] = field(default_factory=list)
    subsystem: str = ""
    layer: str = ""
    fan_in: int = 0
    fan_out: int = 0
    callers: List[str] = field(default_factory=list)
    callees: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    suggested_actions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "target": self.target,
            "target_type": self.target_type,
            "nodes": self.nodes,
            "edges": self.edges,
        }
        if self.violations:
            d["violations"] = self.violations
        if self.smells:
            d["smells"] = self.smells
        if self.subsystem:
            d["subsystem"] = self.subsystem
        if self.layer:
            d["layer"] = self.layer
        if self.fan_in or self.fan_out:
            d["fan_in"] = self.fan_in
            d["fan_out"] = self.fan_out
        if self.callers:
            d["callers"] = self.callers[:20]
        if self.callees:
            d["callees"] = self.callees[:20]
        if self.constraints:
            d["constraints"] = self.constraints
        if self.suggested_actions:
            d["suggested_actions"] = self.suggested_actions
        d["suggested_next_steps"] = _focus_next_steps(self)
        return d

    def format(self) -> str:
        lines = [f"Focus: {self.target} ({self.target_type})"]
        lines.append(f"  Nodes: {len(self.nodes)}  Edges: {len(self.edges)}")
        if self.subsystem:
            lines.append(f"  Subsystem: {self.subsystem}")
        if self.layer:
            lines.append(f"  Layer: {self.layer}")
        if self.fan_in or self.fan_out:
            lines.append(f"  Fan-in: {self.fan_in}  Fan-out: {self.fan_out}")
        if self.callers:
            lines.append(f"  Callers: {', '.join(self.callers[:5])}")
        if self.callees:
            lines.append(f"  Callees: {', '.join(self.callees[:5])}")
        if self.violations:
            lines.append(f"  Violations ({len(self.violations)}):")
            for v in self.violations[:5]:
                lines.append(f"    - {v}")
        if self.smells:
            lines.append(f"  Smells ({len(self.smells)}):")
            for s in self.smells[:5]:
                lines.append(f"    - {s.get('smell_type', '?')}: {s.get('description', '')}")
        if self.constraints:
            lines.append(f"  Constraints:")
            for c in self.constraints[:5]:
                lines.append(f"    - {c}")
        if self.suggested_actions:
            lines.append(f"  Suggested:")
            for a in self.suggested_actions[:5]:
                lines.append(f"    -> {a}")
        return "\n".join(lines)


def focus_context(
    project_root: Path,
    target: str,
    *,
    depth: int = 1,
) -> FocusContext:
    """Build fast, minimal context for a file or node.

    This is the primary entry point for Copilot's in-loop context
    gathering. It answers: "What do I need to know about THIS specific
    file/node before making a change?"

    Args:
        project_root: Project root path.
        target: File path (relative) or node ID.
        depth: BFS depth for expanding neighbors (default 1).

    Returns:
        FocusContext with only the relevant architectural slice.
    """
    ctx = FocusContext(target=target)

    # Determine target type
    if "::" in target:
        ctx.target_type = "node"
    elif target.endswith(".py"):
        ctx.target_type = "file"
    else:
        ctx.target_type = "subsystem"

    g0_path = project_root / ".codegraph" / "graphs" / "graph0.json"
    wf_path = project_root / ".codegraph" / "workflow" / "workflow.json"

    g0 = load_json_cached(g0_path, {})
    wf = load_json_cached(wf_path, {})
    g0_nodes: Dict[str, Any] = {n.get("id", ""): n for n in g0.get("nodes", [])}
    wf_edges: List[Dict[str, Any]] = wf.get("edges", [])

    # Resolve matching nodes
    matching_ids: List[str] = []
    if ctx.target_type == "file":
        normalized = target.replace("\\", "/")
        matching_ids = [
            nid for nid, n in g0_nodes.items()
            if str(n.get("file", "")).replace("\\", "/") == normalized
        ]
    elif ctx.target_type == "node":
        if target in g0_nodes:
            matching_ids = [target]
        else:
            matching_ids = [nid for nid in g0_nodes if target in nid]
    else:
        matching_ids = [
            nid for nid, n in g0_nodes.items()
            if target.lower() in str(n.get("file", "")).lower()
            or target.lower() in nid.lower()
        ]

    # BFS expansion
    expanded: set = set(matching_ids)
    frontier = list(matching_ids)
    callers_map: Dict[str, List[str]] = {}
    callees_map: Dict[str, List[str]] = {}

    for edge in wf_edges:
        src = edge.get("source", "")
        tgt = edge.get("target", "")
        callees_map.setdefault(src, []).append(tgt)
        callers_map.setdefault(tgt, []).append(src)

    for _ in range(depth):
        next_frontier: List[str] = []
        for nid in frontier:
            for neighbor in callees_map.get(nid, []) + callers_map.get(nid, []):
                if neighbor not in expanded:
                    expanded.add(neighbor)
                    next_frontier.append(neighbor)
        frontier = next_frontier

    # Build compact node list
    for nid in sorted(expanded):
        node = g0_nodes.get(nid, {})
        ctx.nodes.append({
            "id": nid,
            "type": node.get("type", ""),
            "file": node.get("file", ""),
            "line": node.get("line", 0),
        })

    # Collect relevant edges
    for edge in wf_edges:
        src = edge.get("source", "")
        tgt = edge.get("target", "")
        if src in expanded or tgt in expanded:
            ctx.edges.append({
                "source": src,
                "target": tgt,
                "type": edge.get("edge_type", ""),
            })

    # Fan metrics for primary target
    if matching_ids:
        primary = matching_ids[0]
        ctx.callers = callers_map.get(primary, [])[:20]
        ctx.callees = callees_map.get(primary, [])[:20]
        ctx.fan_in = len(callers_map.get(primary, []))
        ctx.fan_out = len(callees_map.get(primary, []))

        # Layer and subsystem from graph1
        g1_path = project_root / ".codegraph" / "graphs" / "graph1.json"
        g1 = load_json_cached(g1_path, {})
        g1_map = {n.get("id", ""): n for n in g1.get("nodes", [])}
        primary_g1 = g1_map.get(matching_ids[0], {})
        ctx.layer = primary_g1.get("arch_layer", "")

        # Subsystem from system.json
        sys_path = project_root / ".codegraph" / "architecture" / "system.json"
        sys_data = load_json_cached(sys_path, {})
        for sub in sys_data.get("subsystems", []):
            sub_modules = sub.get("modules", [])
            primary_file = g0_nodes.get(matching_ids[0], {}).get("file", "")
            if any(primary_file.startswith(m) for m in sub_modules):
                ctx.subsystem = sub.get("name", "")
                break
        if ctx.subsystem:
            for constraint in sys_data.get("constraints", []):
                if (constraint.get("source") == ctx.subsystem
                        or constraint.get("target") == ctx.subsystem):
                    ctx.constraints.append(
                        f"{constraint.get('source', '')} -> "
                        f"{constraint.get('target', '')}: "
                        f"{constraint.get('reason', constraint.get('type', ''))}"
                    )

    # Violations from analysis
    violations_path = project_root / ".codegraph" / "analysis" / "violations.json"
    vdata = load_json_cached(violations_path, {})
    for v in vdata.get("violations", []):
        v_node = v.get("node", v.get("source", ""))
        if v_node in expanded:
            ctx.violations.append(
                f"{v.get('type', 'violation')}: {v.get('message', v_node)}"
            )

    # Smells from architecture_advice
    advice_path = project_root / ".codegraph" / "architecture" / "architecture_advice.json"
    advice = load_json_cached(advice_path, {})
    for smell in advice.get("smells", []):
        smell_entity = smell.get("entity", "")
        if smell_entity in expanded or any(smell_entity in nid for nid in matching_ids):
            ctx.smells.append({
                "smell_type": smell.get("smell_type", ""),
                "severity": smell.get("severity", ""),
                "description": smell.get("description", ""),
            })

    # Suggest actions
    if ctx.violations:
        ctx.suggested_actions.append(
            f"Fix {len(ctx.violations)} violation(s) before modifying this area"
        )
    if ctx.fan_out > 15:
        ctx.suggested_actions.append(
            f"High fan-out ({ctx.fan_out}): consider extracting helpers or using dependency inversion"
        )
    if ctx.fan_in > 20:
        ctx.suggested_actions.append(
            f"High fan-in ({ctx.fan_in}): changes here have wide blast radius -- use caution"
        )
    if ctx.smells:
        ctx.suggested_actions.append(
            f"Address {len(ctx.smells)} smell(s): {', '.join(s.get('smell_type', '') for s in ctx.smells[:3])}"
        )

    return ctx


def _focus_next_steps(ctx: FocusContext) -> List[str]:
    """Generate actionable next-step commands based on FocusContext state."""
    steps: List[str] = []
    if ctx.violations:
        steps.append(
            f"codegraph decide {ctx.target}  # get structured reasoning for {len(ctx.violations)} violations"
        )
    if ctx.fan_out > 15:
        steps.append(
            f"codegraph scenario --components {ctx.target}  # explore refactor scenarios"
        )
    if ctx.fan_in > 20:
        steps.append(
            f"codegraph copilot-loop {ctx.target} --simulate  # simulate change impact on {ctx.fan_in} callers"
        )
    if ctx.smells:
        steps.append(
            f"codegraph decide {ctx.target}  # analyze {len(ctx.smells)} architecture smells"
        )
    if not steps:
        steps.append(
            f"codegraph copilot-loop {ctx.target}  # safe to edit; validate with loop after changes"
        )
    steps.append("codegraph build && codegraph analyze  # rebuild after changes")
    return steps
