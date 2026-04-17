"""codegraph.copilot_scope — ScopeContext: subsystem boundary context.

Returns the full architectural picture for one subsystem: its modules,
edges, boundaries, constraints, and violations.

Extracted from copilot_context_builder.py for single-responsibility.
Re-exported from copilot_context_builder for backward compatibility.

CLI command: codegraph scope <subsystem> [--json]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from codegraph.logging_config import get_logger
from codegraph.utils.json_cache import load_json_cached

logger = get_logger("copilot_scope")


@dataclass
class ScopeContext:
    """Scoped architecture context for a subsystem.

    Returns the full architectural picture for one subsystem --
    its modules, edges, boundaries, constraints, and violations.
    Copilot uses this when working within a subsystem boundary.
    """

    subsystem_name: str = ""
    modules: List[str] = field(default_factory=list)
    internal_edges: List[Dict[str, str]] = field(default_factory=list)
    boundary_edges: List[Dict[str, str]] = field(default_factory=list)
    constraints: List[Dict[str, str]] = field(default_factory=list)
    allowed_deps: List[str] = field(default_factory=list)
    forbidden_deps: List[str] = field(default_factory=list)
    node_count: int = 0
    boundary_node_count: int = 0
    smells: List[Dict[str, Any]] = field(default_factory=list)
    violations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "subsystem": self.subsystem_name,
            "modules": self.modules,
            "node_count": self.node_count,
            "boundary_node_count": self.boundary_node_count,
            "internal_edges": self.internal_edges[:50],
            "boundary_edges": self.boundary_edges[:30],
            "constraints": self.constraints,
            "allowed_deps": self.allowed_deps,
            "forbidden_deps": self.forbidden_deps,
            "smells": self.smells[:10],
            "violations": self.violations[:10],
            "suggested_next_steps": _scope_next_steps(self),
        }

    def format(self) -> str:
        lines = [f"Scope: {self.subsystem_name}"]
        lines.append(f"  Modules: {len(self.modules)}  Nodes: {self.node_count}")
        lines.append(f"  Internal edges: {len(self.internal_edges)}")
        lines.append(
            f"  Boundary edges: {len(self.boundary_edges)} "
            f"({self.boundary_node_count} boundary nodes)"
        )
        if self.allowed_deps:
            lines.append(f"  Allowed deps: {', '.join(self.allowed_deps)}")
        if self.forbidden_deps:
            lines.append(f"  Forbidden deps: {', '.join(self.forbidden_deps)}")
        if self.violations:
            lines.append(f"  Violations ({len(self.violations)}):")
            for v in self.violations[:5]:
                lines.append(f"    - {v}")
        if self.smells:
            lines.append(f"  Smells ({len(self.smells)}):")
            for s in self.smells[:5]:
                lines.append(f"    - {s.get('smell_type', '')}: {s.get('description', '')}")
        return "\n".join(lines)


def scope_context(
    project_root: Path,
    subsystem_name: str,
) -> ScopeContext:
    """Build scoped context for a named subsystem.

    Returns the architectural boundary for one subsystem: what's inside,
    what crosses the boundary, and what constraints apply.
    """
    ctx = ScopeContext(subsystem_name=subsystem_name)

    sys_path = project_root / ".codegraph" / "architecture" / "system.json"
    sys_data = load_json_cached(sys_path, {})
    if not sys_data:
        return ctx

    # Find the target subsystem (exact then fuzzy match)
    target_sub = None
    for sub in sys_data.get("subsystems", []):
        if sub.get("name", "").lower() == subsystem_name.lower():
            target_sub = sub
            break
    if not target_sub:
        for sub in sys_data.get("subsystems", []):
            if subsystem_name.lower() in sub.get("name", "").lower():
                target_sub = sub
                break
    if not target_sub:
        return ctx

    ctx.subsystem_name = target_sub.get("name", subsystem_name)
    ctx.modules = target_sub.get("modules", [])

    for edge in sys_data.get("edges", []):
        if edge.get("source") == ctx.subsystem_name:
            ctx.allowed_deps.append(edge.get("target", ""))
    for constraint in sys_data.get("constraints", []):
        if constraint.get("source") == ctx.subsystem_name:
            ctx.forbidden_deps.append(constraint.get("target", ""))
            ctx.constraints.append({
                "target": constraint.get("target", ""),
                "reason": constraint.get("reason", ""),
            })

    g0_path = project_root / ".codegraph" / "graphs" / "graph0.json"
    wf_path = project_root / ".codegraph" / "workflow" / "workflow.json"

    g0 = load_json_cached(g0_path, {})
    subsystem_nodes: set = set()
    for node in g0.get("nodes", []):
        nfile = str(node.get("file", ""))
        if any(nfile.startswith(m) for m in ctx.modules):
            subsystem_nodes.add(node.get("id", ""))

    ctx.node_count = len(subsystem_nodes)
    boundary_nodes: set = set()

    wf = load_json_cached(wf_path, {})
    for edge in wf.get("edges", []):
        src = edge.get("source", "")
        tgt = edge.get("target", "")
        src_in = src in subsystem_nodes
        tgt_in = tgt in subsystem_nodes
        if src_in and tgt_in:
            ctx.internal_edges.append({
                "source": src, "target": tgt,
                "type": edge.get("edge_type", ""),
            })
        elif src_in or tgt_in:
            ctx.boundary_edges.append({
                "source": src, "target": tgt,
                "type": edge.get("edge_type", ""),
                "direction": "outbound" if src_in else "inbound",
            })
            if src_in:
                boundary_nodes.add(src)
            if tgt_in:
                boundary_nodes.add(tgt)

    ctx.boundary_node_count = len(boundary_nodes)

    violations_path = project_root / ".codegraph" / "analysis" / "violations.json"
    vdata = load_json_cached(violations_path, {})
    for v in vdata.get("violations", []):
        v_node = v.get("node", v.get("source", ""))
        if v_node in subsystem_nodes:
            ctx.violations.append(
                f"{v.get('type', 'violation')}: {v.get('message', v_node)}"
            )

    advice_path = project_root / ".codegraph" / "architecture" / "architecture_advice.json"
    advice = load_json_cached(advice_path, {})
    for smell in advice.get("smells", []):
        entity = smell.get("entity", "")
        if entity in subsystem_nodes or any(entity.startswith(m) for m in ctx.modules):
            ctx.smells.append({
                "smell_type": smell.get("smell_type", ""),
                "severity": smell.get("severity", ""),
                "description": smell.get("description", ""),
            })

    return ctx


def _scope_next_steps(ctx: ScopeContext) -> List[str]:
    """Generate actionable next-step commands based on scope context."""
    steps: List[str] = []
    if ctx.violations:
        steps.append(f"codegraph focus {ctx.subsystem_name} --json  # zoom into violations")
    if ctx.boundary_edges:
        steps.append(
            f"codegraph query \"SELECT edges WHERE crosses_subsystem=true"
            f" AND subsystem={ctx.subsystem_name}\"  # trace boundary crossings"
        )
    if ctx.forbidden_deps:
        steps.append(
            f"codegraph decide {ctx.modules[0] if ctx.modules else ctx.subsystem_name}"
            f"  # analyze forbidden dep usage"
        )
    if not steps:
        steps.append(f"codegraph hotspots --json  # subsystem is clean, check system-wide")
    return steps
