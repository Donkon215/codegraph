"""codegraph.context_builder — LLM prompt context builder.

Extracts only the relevant portion of the dependency graph needed
for an LLM prompt, dramatically reducing context size while preserving
architectural understanding. Builds structured prompts that include
subsystems, dependency paths, architecture rules, and detected problems.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from codegraph.index import IndexStore
from codegraph.logging_config import get_logger
from codegraph.models.graph0 import Graph0
from codegraph.models.graph1 import Graph1
from codegraph.models.workflow import Workflow

logger = get_logger("context_builder")


@dataclass
class NodeContext:
    """Extracted context for a single node."""

    node_id: str
    file: str = ""
    node_type: str = ""
    intent: str = ""
    layer: int = 0
    arch_layer: str = ""
    callers: List[str] = field(default_factory=list)
    callees: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "id": self.node_id,
            "file": self.file,
            "type": self.node_type,
        }
        if self.intent:
            d["intent"] = self.intent
        if self.arch_layer:
            d["arch_layer"] = self.arch_layer
        if self.callers:
            d["callers"] = self.callers[:10]
        if self.callees:
            d["callees"] = self.callees[:10]
        return d


@dataclass
class PromptContext:
    """Complete context package for an LLM prompt."""

    focus_nodes: List[NodeContext] = field(default_factory=list)
    related_nodes: List[NodeContext] = field(default_factory=list)
    edges: List[Dict[str, str]] = field(default_factory=list)
    architecture_rules: List[str] = field(default_factory=list)
    detected_problems: List[str] = field(default_factory=list)
    subsystem_info: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "focus_nodes": [n.to_dict() for n in self.focus_nodes],
            "related_nodes": [n.to_dict() for n in self.related_nodes],
            "edges": self.edges,
            "architecture_rules": self.architecture_rules,
            "detected_problems": self.detected_problems,
            "subsystem_info": self.subsystem_info,
            "metadata": self.metadata,
        }

    def to_prompt(self) -> str:
        """Format as a structured LLM prompt."""
        sections: List[str] = []

        # Focus nodes
        if self.focus_nodes:
            lines = ["FOCUS NODES:"]
            for n in self.focus_nodes:
                intent_str = f" — {n.intent}" if n.intent else ""
                lines.append(f"  {n.node_id} ({n.node_type}){intent_str}")
                if n.callees:
                    lines.append(f"    calls: {', '.join(n.callees[:5])}")
                if n.callers:
                    lines.append(f"    called by: {', '.join(n.callers[:5])}")
            sections.append("\n".join(lines))

        # Related nodes
        if self.related_nodes:
            lines = ["RELATED NODES:"]
            for n in self.related_nodes[:20]:
                intent_str = f" — {n.intent}" if n.intent else ""
                lines.append(f"  {n.node_id} ({n.node_type}){intent_str}")
            sections.append("\n".join(lines))

        # Edges
        if self.edges:
            lines = ["DEPENDENCY EDGES:"]
            for e in self.edges[:30]:
                lines.append(f"  {e['source']} -> {e['target']}")
            sections.append("\n".join(lines))

        # Architecture rules
        if self.architecture_rules:
            lines = ["ARCHITECTURE RULES:"]
            for r in self.architecture_rules:
                lines.append(f"  {r}")
            sections.append("\n".join(lines))

        # Problems
        if self.detected_problems:
            lines = ["DETECTED PROBLEMS:"]
            for i, p in enumerate(self.detected_problems, 1):
                lines.append(f"  {i}. {p}")
            sections.append("\n".join(lines))

        # Subsystem
        if self.subsystem_info:
            sections.append(f"SUBSYSTEM CONTEXT:\n  {self.subsystem_info}")

        return "\n\n".join(sections)

    def token_estimate(self) -> int:
        """Rough estimate of token count for the prompt."""
        text = self.to_prompt()
        return len(text) // 4  # ~4 chars per token


def build_context(
    focus_node_ids: List[str],
    graph0: Graph0,
    graph1: Graph1,
    workflow: Workflow,
    index: IndexStore,
    *,
    max_related: int = 30,
    depth: int = 2,
) -> PromptContext:
    """Build LLM prompt context centered on focus nodes.

    Extracts the focus nodes, their callers/callees up to `depth` hops,
    relevant edges, and any architecture rules that apply.

    Args:
        focus_node_ids: Node IDs to center the context on.
        max_related: Maximum number of related nodes to include.
        depth: How many hops to traverse from focus nodes.
    """
    ctx = PromptContext()

    g0_map = {n.id: n for n in graph0.nodes}
    g1_map = {n.id: n for n in graph1.nodes}

    # Build focus nodes
    focus_set: Set[str] = set(focus_node_ids)
    for nid in focus_node_ids:
        nc = _build_node_context(nid, g0_map, g1_map, index)
        if nc:
            ctx.focus_nodes.append(nc)

    # Expand to related nodes via BFS
    related_set: Set[str] = set()
    frontier = set(focus_node_ids)
    for _ in range(depth):
        next_frontier: Set[str] = set()
        for nid in frontier:
            for callee in index.get_callees(nid):
                if callee not in focus_set and callee not in related_set:
                    related_set.add(callee)
                    next_frontier.add(callee)
            for caller in index.get_callers(nid):
                if caller not in focus_set and caller not in related_set:
                    related_set.add(caller)
                    next_frontier.add(caller)
        frontier = next_frontier
        if len(related_set) >= max_related:
            break

    # Build related node contexts
    for nid in sorted(related_set)[:max_related]:
        nc = _build_node_context(nid, g0_map, g1_map, index)
        if nc:
            ctx.related_nodes.append(nc)

    # Collect relevant edges
    all_relevant = focus_set | related_set
    for edge in workflow.edges:
        if edge.source in all_relevant and edge.target in all_relevant:
            ctx.edges.append({"source": edge.source, "target": edge.target})

    ctx.metadata = {
        "focus_count": len(ctx.focus_nodes),
        "related_count": len(ctx.related_nodes),
        "edge_count": len(ctx.edges),
        "token_estimate": ctx.token_estimate(),
    }

    return ctx


def build_subsystem_context(
    file_pattern: str,
    graph0: Graph0,
    graph1: Graph1,
    workflow: Workflow,
    index: IndexStore,
    *,
    max_nodes: int = 50,
) -> PromptContext:
    """Build context for an entire subsystem/module.

    Includes all nodes matching the file pattern and their cross-boundary edges.
    """
    import fnmatch

    ctx = PromptContext()

    g0_map = {n.id: n for n in graph0.nodes}
    g1_map = {n.id: n for n in graph1.nodes}

    # Find matching nodes
    matching_nodes = [n for n in graph0.nodes if fnmatch.fnmatch(n.file, file_pattern)]
    matching_ids = set(n.id for n in matching_nodes)

    # Build focus nodes (limited)
    for node in matching_nodes[:max_nodes]:
        nc = _build_node_context(node.id, g0_map, g1_map, index)
        if nc:
            ctx.focus_nodes.append(nc)

    # Find cross-boundary edges
    for edge in workflow.edges:
        src_in = edge.source in matching_ids
        tgt_in = edge.target in matching_ids
        if src_in or tgt_in:
            ctx.edges.append({"source": edge.source, "target": edge.target})

    # Related: external nodes that connect to this subsystem
    external_nodes: Set[str] = set()
    for edge in ctx.edges:
        if edge["source"] not in matching_ids:
            external_nodes.add(edge["source"])
        if edge["target"] not in matching_ids:
            external_nodes.add(edge["target"])

    for nid in sorted(external_nodes)[:30]:
        nc = _build_node_context(nid, g0_map, g1_map, index)
        if nc:
            ctx.related_nodes.append(nc)

    ctx.subsystem_info = f"Files matching '{file_pattern}': {len(matching_nodes)} nodes"
    ctx.metadata = {
        "pattern": file_pattern,
        "focus_count": len(ctx.focus_nodes),
        "related_count": len(ctx.related_nodes),
        "edge_count": len(ctx.edges),
        "token_estimate": ctx.token_estimate(),
    }

    return ctx


def build_task_context(
    task: Dict[str, Any],
    graph0: Graph0,
    graph1: Graph1,
    workflow: Workflow,
    index: IndexStore,
) -> PromptContext:
    """Build context for a specific task from tasks.json.

    Extracts the affected nodes and their surrounding graph context.
    """
    node_ids = task.get("nodes", [])
    if isinstance(node_ids, list) and node_ids and isinstance(node_ids[0], dict):
        node_ids = [n.get("id", "") for n in node_ids]

    ctx = build_context(node_ids, graph0, graph1, workflow, index, depth=1)

    # Add task-specific problem info
    task_id = task.get("task_id", "")
    priority = task.get("priority", 10)
    ctx.detected_problems.append(f"Task: {task_id} (priority={priority})")

    node_count = len(node_ids)
    ctx.detected_problems.append(f"Affected nodes: {node_count}")

    return ctx


def _build_node_context(
    node_id: str,
    g0_map: Dict[str, Any],
    g1_map: Dict[str, Any],
    index: IndexStore,
) -> Optional[NodeContext]:
    """Build context for a single node from graph data."""
    g0 = g0_map.get(node_id)
    if not g0:
        return None

    g1 = g1_map.get(node_id)

    nc = NodeContext(
        node_id=node_id,
        file=g0.file,
        node_type=g0.type,
    )
    if g1:
        nc.intent = g1.intent or ""
        nc.layer = g1.layer
        nc.arch_layer = g1.arch_layer or ""

    nc.callers = index.get_callers(node_id)
    nc.callees = index.get_callees(node_id)

    return nc
