"""codegraph.target_architecture — Target architecture state engine.

Defines WHERE the architecture should move. Computes delta between
current workflow and target workflow to produce actionable tasks.

The target architecture is the desired future state:
  - target_workflow.json: desired call-graph edges
  - target_architecture.json: desired subsystem/component structure

The delta engine computes:
  delta = target - current
  → missing_edges, extra_edges, missing_nodes, extra_nodes

This delta becomes tasks for Copilot to implement.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from codegraph.architecture_delta import ArchitectureDelta, EdgeChange, NodeChange
from codegraph.logging_config import get_logger

logger = get_logger("target_architecture")

TARGET_WORKFLOW_FILE = "target_workflow.json"
TARGET_ARCHITECTURE_FILE = "target_architecture.json"


# ── Target Workflow Edge ───────────────────────────────────────────────


@dataclass
class TargetEdge:
    """A desired call-graph edge in the target workflow."""

    source: str
    target: str
    reason: str = ""
    priority: int = 5
    subsystem: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"source": self.source, "target": self.target}
        if self.reason:
            d["reason"] = self.reason
        if self.priority != 5:
            d["priority"] = self.priority
        if self.subsystem:
            d["subsystem"] = self.subsystem
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> TargetEdge:
        return cls(
            source=d["source"],
            target=d["target"],
            reason=d.get("reason", ""),
            priority=d.get("priority", 5),
            subsystem=d.get("subsystem", ""),
        )


# ── Target Node ────────────────────────────────────────────────────────


@dataclass
class TargetNode:
    """A desired node in the target architecture."""

    node_id: str
    module: str = ""
    subsystem: str = ""
    intent: str = ""
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"node_id": self.node_id}
        if self.module:
            d["module"] = self.module
        if self.subsystem:
            d["subsystem"] = self.subsystem
        if self.intent:
            d["intent"] = self.intent
        if self.reason:
            d["reason"] = self.reason
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> TargetNode:
        return cls(
            node_id=d["node_id"],
            module=d.get("module", ""),
            subsystem=d.get("subsystem", ""),
            intent=d.get("intent", ""),
            reason=d.get("reason", ""),
        )


# ── Target Workflow ────────────────────────────────────────────────────


@dataclass
class TargetWorkflow:
    """The desired future state of the call graph.

    Represents edges and nodes that SHOULD exist in the architecture.
    Compared against current workflow to compute delta.
    """

    version: int = 1
    description: str = ""
    edges: List[TargetEdge] = field(default_factory=list)
    nodes: List[TargetNode] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "description": self.description,
            "edges": [e.to_dict() for e in self.edges],
            "nodes": [n.to_dict() for n in self.nodes],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> TargetWorkflow:
        edges = [TargetEdge.from_dict(e) for e in d.get("edges", [])]
        nodes = [TargetNode.from_dict(n) for n in d.get("nodes", [])]
        return cls(
            version=d.get("version", 1),
            description=d.get("description", ""),
            edges=edges,
            nodes=nodes,
        )

    def save(self, project_root: Path) -> Path:
        path = project_root / ".codegraph" / "workflow" / TARGET_WORKFLOW_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("Saved target workflow → %s", path)
        return path

    @classmethod
    def load(cls, project_root: Path) -> Optional[TargetWorkflow]:
        path = project_root / ".codegraph" / "workflow" / TARGET_WORKFLOW_FILE
        if not path.exists():
            return None
        text = path.read_text(encoding="utf-8")
        return cls.from_dict(json.loads(text))

    def add_edge(self, source: str, target: str, reason: str = "",
                 priority: int = 5, subsystem: str = "") -> None:
        self.edges.append(TargetEdge(
            source=source, target=target,
            reason=reason, priority=priority, subsystem=subsystem,
        ))

    def add_node(self, node_id: str, module: str = "", subsystem: str = "",
                 intent: str = "", reason: str = "") -> None:
        self.nodes.append(TargetNode(
            node_id=node_id, module=module,
            subsystem=subsystem, intent=intent, reason=reason,
        ))


# ── Architecture Delta ─────────────────────────────────────────────────
# The canonical `ArchitectureDelta` now lives in `codegraph.architecture_delta`.
# This module previously defined a duplicate class (missing_*/extra_*); it was
# unified into the single canonical model. `compute_architecture_delta` and
# `delta_to_tasks` below use the canonical `added_*`/`removed_*` vocabulary.


def save_target_delta(delta: ArchitectureDelta, project_root: Path) -> Path:
    """Persist a delta to .codegraph/planning/delta.json in the legacy shape.

    The on-disk format keeps missing_*/extra_* for backward compatibility;
    the in-memory object is the canonical ArchitectureDelta.
    """
    path = project_root / ".codegraph" / "planning" / "delta.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(delta.to_legacy_target_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Saved architecture delta → %s", path)
    return path


# ── Delta Engine ───────────────────────────────────────────────────────


def compute_architecture_delta(
    target: TargetWorkflow,
    current_workflow: Dict[str, Any],
    current_nodes: Set[str],
) -> ArchitectureDelta:
    """Compute delta = target - current.

    Args:
        target: The desired future workflow state.
        current_workflow: Current workflow.json data.
        current_nodes: Set of all current node IDs from graph0.
    """
    delta = ArchitectureDelta()

    # Current edges as set of (source, target)
    current_edges: Set[Tuple[str, str]] = set()
    for edge in current_workflow.get("edges", []):
        src = edge.get("source", "")
        tgt = edge.get("target", "")
        if src and tgt:
            current_edges.add((src, tgt))

    # Target edges
    target_edge_set: Set[Tuple[str, str]] = set()
    target_edge_info: Dict[Tuple[str, str], TargetEdge] = {}
    for te in target.edges:
        key = (te.source, te.target)
        target_edge_set.add(key)
        target_edge_info[key] = te

    # Added edges: in target but not in current
    for key in target_edge_set - current_edges:
        te = target_edge_info[key]
        delta.added_edges.append(EdgeChange(
            source=te.source, target=te.target,
            reason=te.reason, priority=te.priority,
        ))

    # Removed edges: edges in current but explicitly not desired by target
    # (Only report removals if target defines a scope for specific sources)
    target_sources = {te.source for te in target.edges}
    for src, tgt in current_edges:
        if src in target_sources and (src, tgt) not in target_edge_set:
            delta.removed_edges.append(EdgeChange(source=src, target=tgt))

    # Added nodes: in target but not in current
    for tn in target.nodes:
        if tn.node_id not in current_nodes:
            delta.added_nodes.append(NodeChange(
                node_id=tn.node_id, module=tn.module,
                intent=tn.intent, reason=tn.reason,
            ))

    # Sort added edges by priority (preserves prior evolution ordering)
    delta.added_edges.sort(key=lambda e: e.priority)

    return delta


def delta_to_tasks(delta: ArchitectureDelta, graph_version: int) -> Dict[str, Any]:
    """Convert an architecture delta into agent_response.json format.

    Produces connect_call repairs for missing edges and
    flag_for_human_review for missing nodes.
    """
    repairs: List[Dict[str, Any]] = []
    intents: List[Dict[str, Any]] = []

    for edge in delta.added_edges:
        repairs.append({
            "node": edge.source,
            "action": "connect_call",
            "target": edge.target,
            "reason": edge.reason or "Target workflow requires this edge",
        })

    for node in delta.added_nodes:
        repairs.append({
            "node": node.node_id,
            "action": "flag_for_human_review",
            "target": node.module,
            "reason": node.reason or "Target architecture requires this node",
        })
        if node.intent:
            intents.append({
                "node": node.node_id,
                "intent": node.intent,
            })

    for edge in delta.removed_edges:
        repairs.append({
            "node": edge.source,
            "action": "flag_for_human_review",
            "target": edge.target,
            "reason": "Edge exists in current workflow but not in target — review for removal",
        })

    return {
        "cycle": 1,
        "graph_version": graph_version,
        "intents": intents,
        "repairs": repairs,
    }


def generate_target_from_architecture(
    arch: Any,
    current_workflow: Dict[str, Any],
) -> TargetWorkflow:
    """Generate a target_workflow from a SystemArchitecture definition.

    Uses the architecture's subsystem edges and component edges
    to build a target workflow that represents the desired state.
    Matches architecture edges against actual function-level edges.
    """
    target = TargetWorkflow(
        description=f"Auto-generated target from architecture: {arch.name}",
    )

    # Build module → functions mapping from architecture
    module_functions: Dict[str, List[str]] = {}
    for subsystem in arch.subsystems:
        for comp in subsystem.components:
            if comp.module and comp.functions:
                module_functions[comp.module] = comp.functions

    # Build component name → module mapping
    comp_to_module: Dict[str, str] = {}
    for subsystem in arch.subsystems:
        for comp in subsystem.components:
            comp_to_module[comp.name] = comp.module

    # Build subsystem name → modules mapping
    subsys_modules: Dict[str, List[str]] = {}
    for subsystem in arch.subsystems:
        subsys_modules[subsystem.name] = subsystem.module_paths

    # Current function-level edges grouped by file pair
    file_pair_edges: Dict[Tuple[str, str], List[Tuple[str, str]]] = defaultdict(list)
    for edge in current_workflow.get("edges", []):
        src = edge.get("source", "")
        tgt = edge.get("target", "")
        src_file = src.split("::")[0] if "::" in src else src
        tgt_file = tgt.split("::")[0] if "::" in tgt else tgt
        if src_file != tgt_file:
            file_pair_edges[(src_file, tgt_file)].append((src, tgt))

    # Convert inter-subsystem architecture edges to target edges
    for arch_edge in arch.edges:
        src_modules = subsys_modules.get(arch_edge.source, [])
        tgt_modules = subsys_modules.get(arch_edge.target, [])
        # Check if any function-level edge already implements this
        found_any = False
        for sm in src_modules:
            for tm in tgt_modules:
                if (sm, tm) in file_pair_edges:
                    found_any = True
                    # Include existing edges as target to preserve them
                    for src_fn, tgt_fn in file_pair_edges[(sm, tm)]:
                        target.add_edge(
                            src_fn, tgt_fn,
                            reason=f"Architecture: {arch_edge.source} → {arch_edge.target}",
                            subsystem=arch_edge.source,
                        )
        if not found_any:
            # Architecture requires this but no implementation exists
            target.add_edge(
                arch_edge.source, arch_edge.target,
                reason=f"Architecture requires {arch_edge.source} → {arch_edge.target}",
                priority=3,
            )

    # Convert intra-subsystem edges
    for subsystem in arch.subsystems:
        for edge in subsystem.edges:
            src_mod = comp_to_module.get(edge.source, edge.source)
            tgt_mod = comp_to_module.get(edge.target, edge.target)
            if (src_mod, tgt_mod) in file_pair_edges:
                for src_fn, tgt_fn in file_pair_edges[(src_mod, tgt_mod)]:
                    target.add_edge(
                        src_fn, tgt_fn,
                        reason=f"Subsystem {subsystem.name}: {edge.source} → {edge.target}",
                        subsystem=subsystem.name,
                    )

    # Add required nodes from architecture
    for subsystem in arch.subsystems:
        for comp in subsystem.components:
            for fn in comp.functions:
                if "::" in fn:
                    node_id = fn
                elif comp.module:
                    node_id = f"{comp.module}::{fn}"
                else:
                    continue
                target.add_node(
                    node_id,
                    module=comp.module,
                    subsystem=subsystem.name,
                    intent=comp.description,
                )

    return target
