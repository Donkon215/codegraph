"""codegraph.architecture_delta — Architecture delta generator.

Generates a structural diff between the current graph state and
a proposed plan (or between two graph snapshots). The delta describes
exactly what will change before implementation begins.

Output: .codegraph/architecture_delta.json

Contents:
  - added_nodes: nodes that will be created
  - removed_nodes: nodes that will be removed
  - added_edges: new dependencies/calls
  - removed_edges: dependencies that will be removed
  - affected_subsystems: subsystems impacted by changes
  - constraint_violations: potential architecture violations
  - risk_estimate: overall risk level (LOW / MEDIUM / HIGH / BLOCKED)

CLI command: codegraph delta
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from codegraph.logging_config import get_logger

logger = get_logger("architecture_delta")

DELTA_OUTPUT_FILE = "architecture_delta.json"


# ═══════════════════════════════════════════════════════════════════════
# Data Structures
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class EdgeChange:
    """Describes an edge addition or removal."""

    source: str
    target: str
    edge_type: str = "call"
    reason: str = ""
    priority: int = 5

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"source": self.source, "target": self.target}
        if self.edge_type != "call":
            d["edge_type"] = self.edge_type
        if self.reason:
            d["reason"] = self.reason
        if self.priority != 5:
            d["priority"] = self.priority
        return d


@dataclass
class NodeChange:
    """Describes a node addition or removal."""

    node_id: str
    module: str = ""
    node_type: str = ""  # function, class, method, module, subsystem
    reason: str = ""
    subsystem: str = ""  # owning subsystem; preserved verbatim (no silent loss)
    intent: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"node_id": self.node_id}
        if self.module:
            d["module"] = self.module
        if self.node_type:
            d["node_type"] = self.node_type
        if self.reason:
            d["reason"] = self.reason
        if self.subsystem:
            d["subsystem"] = self.subsystem
        if self.intent:
            d["intent"] = self.intent
        return d


@dataclass
class ConstraintViolation:
    """A potential architecture constraint violation."""

    constraint_type: str  # forbidden_dep, boundary, layer
    description: str
    source: str = ""
    target: str = ""
    severity: str = "error"

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "type": self.constraint_type,
            "description": self.description,
            "severity": self.severity,
        }
        if self.source:
            d["source"] = self.source
        if self.target:
            d["target"] = self.target
        return d


@dataclass
class ArchitectureDelta:
    """Complete architecture delta between current and proposed state."""

    added_nodes: List[NodeChange] = field(default_factory=list)
    removed_nodes: List[NodeChange] = field(default_factory=list)
    added_edges: List[EdgeChange] = field(default_factory=list)
    removed_edges: List[EdgeChange] = field(default_factory=list)
    affected_subsystems: List[str] = field(default_factory=list)
    constraint_violations: List[ConstraintViolation] = field(default_factory=list)
    risk_estimate: str = "LOW"
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def has_changes(self) -> bool:
        return bool(
            self.added_nodes or self.removed_nodes
            or self.added_edges or self.removed_edges
        )

    @property
    def total_changes(self) -> int:
        return (
            len(self.added_nodes) + len(self.removed_nodes)
            + len(self.added_edges) + len(self.removed_edges)
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "added_nodes": [n.to_dict() for n in self.added_nodes],
            "removed_nodes": [n.to_dict() for n in self.removed_nodes],
            "added_edges": [e.to_dict() for e in self.added_edges],
            "removed_edges": [e.to_dict() for e in self.removed_edges],
            "affected_subsystems": self.affected_subsystems,
            "constraint_violations": [v.to_dict() for v in self.constraint_violations],
            "risk_estimate": self.risk_estimate,
            "total_changes": self.total_changes,
            "metadata": self.metadata,
        }

    # ── Legacy target-delta compatibility (planning/delta.json) ──────────
    # The evolution pipeline persisted delta as missing_*/extra_*. The
    # canonical model uses added_*/removed_*. These two helpers translate
    # without changing the on-disk contract.

    def to_legacy_target_dict(self) -> Dict[str, Any]:
        """Emit the legacy ``missing_*`` / ``extra_*`` shape for planning/delta.json."""
        return {
            "summary": {
                "missing_edges": len(self.added_edges),
                "extra_edges": len(self.removed_edges),
                "missing_nodes": len(self.added_nodes),
                "extra_nodes": len(self.removed_nodes),
                "total_changes": self.total_changes,
            },
            "missing_edges": [e.to_dict() for e in self.added_edges],
            "extra_edges": [e.to_dict() for e in self.removed_edges],
            "missing_nodes": [n.to_dict() for n in self.added_nodes],
            "extra_nodes": [n.to_dict() for n in self.removed_nodes],
        }

    @classmethod
    def from_legacy_target_dict(cls, data: Dict[str, Any]) -> "ArchitectureDelta":
        """Build a canonical delta from the legacy ``missing_*`` / ``extra_*`` shape."""
        delta = cls(
            risk_estimate=data.get("risk_estimate", "LOW"),
            affected_subsystems=data.get("affected_subsystems", []),
            metadata=data.get("metadata", {}),
        )
        for e in data.get("missing_edges", []):
            delta.added_edges.append(EdgeChange(
                source=e["source"], target=e["target"],
                edge_type=e.get("edge_type", "call"),
                reason=e.get("reason", ""),
                priority=e.get("priority", 5),
            ))
        for e in data.get("extra_edges", []):
            delta.removed_edges.append(EdgeChange(
                source=e["source"], target=e["target"],
                edge_type=e.get("edge_type", "call"),
                reason=e.get("reason", ""),
                priority=e.get("priority", 5),
            ))
        for n in data.get("missing_nodes", []):
            delta.added_nodes.append(NodeChange(
                node_id=n["node_id"],
                module=n.get("module", ""),
                node_type=n.get("node_type", ""),
                reason=n.get("reason", ""),
                subsystem=n.get("subsystem", ""),
                intent=n.get("intent", ""),
            ))
        for n in data.get("extra_nodes", []):
            delta.removed_nodes.append(NodeChange(
                node_id=n["node_id"],
                module=n.get("module", ""),
                node_type=n.get("node_type", ""),
                reason=n.get("reason", ""),
                subsystem=n.get("subsystem", ""),
                intent=n.get("intent", ""),
            ))
        return delta

    def format(self) -> str:
        lines = ["Architecture Delta"]
        lines.append(f"  Risk: {self.risk_estimate}")
        lines.append(f"  Changes: {self.total_changes}")
        if self.added_nodes:
            lines.append(f"  Added nodes: {len(self.added_nodes)}")
            for n in self.added_nodes[:5]:
                lines.append(f"    + {n.node_id}")
        if self.removed_nodes:
            lines.append(f"  Removed nodes: {len(self.removed_nodes)}")
            for n in self.removed_nodes[:5]:
                lines.append(f"    - {n.node_id}")
        if self.added_edges:
            lines.append(f"  Added edges: {len(self.added_edges)}")
            for e in self.added_edges[:5]:
                lines.append(f"    + {e.source} -> {e.target}")
        if self.removed_edges:
            lines.append(f"  Removed edges: {len(self.removed_edges)}")
            for e in self.removed_edges[:5]:
                lines.append(f"    - {e.source} -> {e.target}")
        if self.affected_subsystems:
            lines.append(f"  Affected subsystems: {', '.join(self.affected_subsystems)}")
        if self.constraint_violations:
            lines.append(f"  Constraint violations: {len(self.constraint_violations)}")
            for v in self.constraint_violations:
                lines.append(f"    [{v.severity}] {v.description}")
        return "\n".join(lines)

    def save(self, project_root: Path) -> Path:
        """Save delta to .codegraph/architecture_delta.json."""
        out_dir = project_root / ".codegraph"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / DELTA_OUTPUT_FILE
        out_path.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("Architecture delta saved: %s", out_path)
        return out_path

    @classmethod
    def load(cls, project_root: Path) -> Optional["ArchitectureDelta"]:
        """Load a previously saved delta."""
        path = project_root / ".codegraph" / DELTA_OUTPUT_FILE
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return _dict_to_delta(data)
        except (json.JSONDecodeError, OSError, KeyError) as exc:
            logger.warning("Failed to load delta: %s", exc)
            return None


def _dict_to_delta(data: Dict[str, Any]) -> ArchitectureDelta:
    """Convert a dict (from JSON) back to an ArchitectureDelta."""
    delta = ArchitectureDelta(
        risk_estimate=data.get("risk_estimate", "LOW"),
        affected_subsystems=data.get("affected_subsystems", []),
        metadata=data.get("metadata", {}),
    )
    for n in data.get("added_nodes", []):
        delta.added_nodes.append(NodeChange(
            node_id=n["node_id"],
            module=n.get("module", ""),
            node_type=n.get("node_type", ""),
            reason=n.get("reason", ""),
            subsystem=n.get("subsystem", ""),
            intent=n.get("intent", ""),
        ))
    for n in data.get("removed_nodes", []):
        delta.removed_nodes.append(NodeChange(
            node_id=n["node_id"],
            module=n.get("module", ""),
            node_type=n.get("node_type", ""),
            reason=n.get("reason", ""),
            subsystem=n.get("subsystem", ""),
            intent=n.get("intent", ""),
        ))
    for e in data.get("added_edges", []):
        delta.added_edges.append(EdgeChange(
            source=e["source"],
            target=e["target"],
            edge_type=e.get("edge_type", "call"),
            reason=e.get("reason", ""),
            priority=e.get("priority", 5),
        ))
    for e in data.get("removed_edges", []):
        delta.removed_edges.append(EdgeChange(
            source=e["source"],
            target=e["target"],
            edge_type=e.get("edge_type", "call"),
            reason=e.get("reason", ""),
            priority=e.get("priority", 5),
        ))
    for v in data.get("constraint_violations", []):
        delta.constraint_violations.append(ConstraintViolation(
            constraint_type=v.get("type", ""),
            description=v.get("description", ""),
            source=v.get("source", ""),
            target=v.get("target", ""),
            severity=v.get("severity", "error"),
        ))
    return delta


# ═══════════════════════════════════════════════════════════════════════
# Delta Generation
# ═══════════════════════════════════════════════════════════════════════


def _delta_from_change(change: "ArchitectureChange", project_root: Path) -> ArchitectureDelta:
    """Derive ArchitectureDelta from a canonical ArchitectureChange.

    ProposedState = CurrentState + ArchitectureChange
    ArchitectureDelta = diff(CurrentState, ProposedState)

    Constraint operations are policy changes (recorded in metadata), never
    violations; violations are detected only in the proposed state.
    """
    from codegraph.architecture_change import OpType

    delta = ArchitectureDelta()
    system_path = project_root / ".codegraph" / "architecture" / "system.json"
    mod_to_sub: Dict[str, str] = {}
    forbidden: Dict[tuple[str, str], str] = {}
    current_nodes: Set[str] = set()
    if system_path.exists():
        try:
            system = json.loads(system_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            system = {}
        for sub in system.get("subsystems", []):
            sub_name = sub.get("name", "")
            if sub_name:
                current_nodes.add(sub_name)
            for comp in sub.get("components", []):
                mod = comp.get("module", "")
                if mod:
                    mod_to_sub[mod] = sub_name
                    current_nodes.add(mod)
        for c in system.get("constraints", []):
            ctype = c.get("type", "")
            if ctype:
                forbidden[(c["source"], c["target"])] = ctype

    # Current node state (function/module ids from graph0)
    graph0_path = project_root / ".codegraph" / "graphs" / "graph0.json"
    if graph0_path.exists():
        try:
            g0 = json.loads(graph0_path.read_text(encoding="utf-8"))
            for node in g0.get("nodes", []):
                nid = node.get("id", "")
                if nid:
                    current_nodes.add(nid)
        except (json.JSONDecodeError, OSError):
            pass

    # Current edge state, keyed by (source, target, edge_type) so that
    # changing an edge's type is detected as a removal + addition.
    current_edges: Set[tuple[str, str, str]] = set()
    wf_path = project_root / ".codegraph" / "workflow" / "workflow.json"
    if wf_path.exists():
        try:
            wf = json.loads(wf_path.read_text(encoding="utf-8"))
            for e in wf.get("edges", []):
                src = e.get("source", "")
                tgt = e.get("target", "")
                if src and tgt:
                    current_edges.add((src, tgt, e.get("edge_type", "call")))
        except (json.JSONDecodeError, OSError):
            pass

    # ProposedState = CurrentState + ArchitectureChange
    proposed_edges: Set[tuple[str, str, str]] = set(current_edges)
    proposed_nodes: Set[str] = set(current_nodes)
    add_edge_meta: Dict[tuple[str, str, str], Dict[str, Any]] = {}
    remove_edge_meta: Dict[tuple[str, str, str], Dict[str, Any]] = {}
    add_node_meta: Dict[str, Dict[str, Any]] = {}
    remove_node_meta: Dict[str, Dict[str, Any]] = {}

    constraint_changes: List[Dict[str, Any]] = []

    def _sub_of(thing: str) -> str:
        mod = thing.split("::")[0] if "::" in thing else thing
        return mod_to_sub.get(mod, "")

    for op in change.operations:
        if op.op == OpType.ADD_COMPONENT:
            nid = op.component
            proposed_nodes.add(nid)
            add_node_meta[nid] = {"module": op.component, "node_type": "module",
                                  "reason": op.reason, "subsystem": op.component_subsystem}
        elif op.op == OpType.REMOVE_COMPONENT:
            nid = op.component
            proposed_nodes.discard(nid)
            remove_node_meta[nid] = {"module": op.component, "node_type": "module",
                                     "reason": op.reason, "subsystem": op.component_subsystem}
        elif op.op == OpType.ADD_SUBSYSTEM:
            nid = op.subsystem
            proposed_nodes.add(nid)
            add_node_meta[nid] = {"module": op.subsystem, "node_type": "subsystem", "reason": op.reason}
        elif op.op == OpType.REMOVE_SUBSYSTEM:
            nid = op.subsystem
            proposed_nodes.discard(nid)
            remove_node_meta[nid] = {"module": op.subsystem, "node_type": "subsystem", "reason": op.reason}
        elif op.op == OpType.ADD_EDGE:
            key = (op.source, op.target, op.edge_type or "call")
            proposed_edges.add(key)
            edge_priority = change.metadata.get("target_edge_priorities", {}).get(
                f"{op.source}->{op.target}", 5)
            add_edge_meta[key] = {"edge_type": op.edge_type or "call",
                                  "reason": op.reason, "priority": edge_priority}
        elif op.op == OpType.REMOVE_EDGE:
            key = (op.source, op.target, op.edge_type or "call")
            proposed_edges.discard(key)
            remove_edge_meta[key] = {"edge_type": op.edge_type or "call", "reason": op.reason}
        elif op.op == OpType.ADD_CONSTRAINT:
            constraint_changes.append({
                "op": "ADD_CONSTRAINT",
                "constraint_type": op.constraint_type,
                "source": op.source, "target": op.target})
            forbidden[(op.source, op.target)] = op.constraint_type
        elif op.op == OpType.REMOVE_CONSTRAINT:
            constraint_changes.append({
                "op": "REMOVE_CONSTRAINT",
                "constraint_type": op.constraint_type,
                "source": op.source, "target": op.target})
            forbidden.pop((op.source, op.target), None)

    # ArchitectureDelta = diff(CurrentState, ProposedState)
    for (s, t, et) in sorted(proposed_edges - current_edges):
        m = add_edge_meta.get((s, t, et), {})
        delta.added_edges.append(EdgeChange(
            source=s, target=t,
            edge_type=m.get("edge_type", et),
            reason=m.get("reason", ""),
            priority=m.get("priority", 5),
        ))
    delta.added_edges.sort(key=lambda e: e.priority)
    for (s, t, et) in sorted(current_edges - proposed_edges):
        m = remove_edge_meta.get((s, t, et), {})
        delta.removed_edges.append(EdgeChange(
            source=s, target=t,
            edge_type=m.get("edge_type", et),
            reason=m.get("reason", ""),
        ))
    for nid in sorted(proposed_nodes - current_nodes):
        m = add_node_meta.get(nid, {})
        delta.added_nodes.append(NodeChange(
            node_id=nid, module=m.get("module", nid),
            node_type=m.get("node_type", ""), reason=m.get("reason", ""),
            subsystem=m.get("subsystem", ""),
        ))
    for nid in sorted(current_nodes - proposed_nodes):
        m = remove_node_meta.get(nid, {})
        delta.removed_nodes.append(NodeChange(
            node_id=nid, module=m.get("module", nid),
            node_type=m.get("node_type", ""), reason=m.get("reason", ""),
            subsystem=m.get("subsystem", ""),
        ))

    # affected subsystems (subsystem-type nodes carry the name directly)
    affected: Set[str] = set()
    for n in delta.added_nodes + delta.removed_nodes:
        if n.node_type == "subsystem":
            affected.add(n.node_id)
        else:
            s = n.subsystem or _sub_of(n.module or n.node_id)
            if s:
                affected.add(s)
    for e in delta.added_edges + delta.removed_edges:
        s = _sub_of(e.source)
        t = _sub_of(e.target)
        if s:
            affected.add(s)
        if t:
            affected.add(t)
    delta.affected_subsystems = sorted(affected)

    for (s, t, _et) in proposed_edges:
        ssub = _sub_of(s)
        tsub = _sub_of(t)
        if ssub and tsub and (ssub, tsub) in forbidden:
            delta.constraint_violations.append(ConstraintViolation(
                constraint_type=forbidden[(ssub, tsub)],
                description=f"Forbidden dependency: {ssub} -> {tsub} ({s} -> {t})",
                source=s, target=t))

    if constraint_changes:
        delta.metadata["constraint_changes"] = constraint_changes

    delta.risk_estimate = _classify_delta_risk(delta)
    return delta


def generate_architecture_delta(
    project_root: Path,
    *,
    change: "Optional[ArchitectureChange]" = None,
    plan: Optional[Dict[str, Any]] = None,
    agent_response: Optional[Dict[str, Any]] = None,
) -> ArchitectureDelta:
    """Generate architecture delta from current state vs proposed changes.

    Inputs (precedence): change > plan > agent_response > auto-load.
      - change: canonical ArchitectureChange (#27)
      - plan: an architecture plan (from codegraph compile --save)
      - agent_response: an agent_response.json with repairs

    If none provided, loads the plan from
    .codegraph/planning/architecture_plan.json or agent_response.json.
    """
    if change is not None:
        return _delta_from_change(change, project_root)

    delta = ArchitectureDelta()

    # Load current graph state
    graph0_path = project_root / ".codegraph" / "graphs" / "graph0.json"
    current_nodes: Set[str] = set()
    current_edges: Set[tuple[str, str]] = set()
    if graph0_path.exists():
        try:
            g0 = json.loads(graph0_path.read_text(encoding="utf-8"))
            for node in g0.get("nodes", []):
                nid = node.get("id", "")
                if nid:
                    current_nodes.add(nid)
        except (json.JSONDecodeError, OSError):
            pass

    # Load current workflow edges
    wf_path = project_root / ".codegraph" / "workflow" / "workflow.json"
    if wf_path.exists():
        try:
            wf = json.loads(wf_path.read_text(encoding="utf-8"))
            for edge in wf.get("edges", []):
                src = edge.get("source", "")
                tgt = edge.get("target", "")
                if src and tgt:
                    current_edges.add((src, tgt))
        except (json.JSONDecodeError, OSError):
            pass

    # Resolve input
    if plan is None and agent_response is None:
        plan = _try_load_plan(project_root)
    if plan is None and agent_response is None:
        agent_response = _try_load_agent_response(project_root)

    if agent_response:
        _process_agent_response(delta, agent_response, current_nodes, current_edges)
    elif plan:
        _process_plan(delta, plan, current_nodes, current_edges)

    # Determine affected subsystems
    delta.affected_subsystems = _find_affected_subsystems(
        project_root, delta,
    )

    # Check constraint violations
    delta.constraint_violations = _check_constraints(
        project_root, delta,
    )

    # Classify risk
    delta.risk_estimate = _classify_delta_risk(delta)

    return delta


def _try_load_plan(root: Path) -> Optional[Dict[str, Any]]:
    """Try to load architecture plan."""
    for name in ("architecture_plan.json", ".plan.json"):
        path = root / ".codegraph" / "planning" / name
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
    return None


def _try_load_agent_response(root: Path) -> Optional[Dict[str, Any]]:
    """Try to load agent_response.json."""
    path = root / "agent_response.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return None


def _process_agent_response(
    delta: ArchitectureDelta,
    response: Dict[str, Any],
    current_nodes: Set[str],
    current_edges: Set[tuple[str, str]],
) -> None:
    """Extract delta from an agent_response.json."""
    for repair in response.get("repairs", []):
        action = repair.get("action", "")
        node = repair.get("node", "")
        target = repair.get("target", "")
        reason = repair.get("reason", "")

        if action == "connect_call" and node and target:
            if (node, target) not in current_edges:
                delta.added_edges.append(EdgeChange(
                    source=node, target=target, reason=reason,
                ))
        elif action == "add_import" and node and target:
            module = node.split("::")[0] if "::" in node else node
            delta.added_edges.append(EdgeChange(
                source=module, target=target,
                edge_type="import", reason=reason,
            ))
        elif action == "remove_dead_code" and node:
            delta.removed_nodes.append(NodeChange(
                node_id=node,
                module=node.split("::")[0] if "::" in node else node,
                reason=reason,
            ))


def _process_plan(
    delta: ArchitectureDelta,
    plan: Dict[str, Any],
    current_nodes: Set[str],
    current_edges: Set[tuple[str, str]],
) -> None:
    """Extract delta from an architecture plan."""
    for task in plan.get("tasks", []):
        action = task.get("action", "")
        target = task.get("target", "")
        module = task.get("module", "")

        if action == "create_function" and target:
            if target not in current_nodes:
                delta.added_nodes.append(NodeChange(
                    node_id=target, module=module,
                    node_type="function",
                ))
        elif action == "create_file" and module:
            delta.added_nodes.append(NodeChange(
                node_id=module, module=module,
                node_type="module",
            ))
        elif action == "add_import":
            src = task.get("source", module)
            tgt = task.get("target", "")
            if src and tgt:
                delta.added_edges.append(EdgeChange(
                    source=src, target=tgt, edge_type="import",
                ))
        elif action == "add_test":
            test_mod = task.get("test_module", "")
            if test_mod:
                delta.added_nodes.append(NodeChange(
                    node_id=test_mod, module=test_mod,
                    node_type="test",
                ))

    # Subsystem changes from the plan
    for sub_change in plan.get("subsystem_changes", []):
        action = sub_change.get("action", "")
        if action in ("add_component", "add_edge"):
            src = sub_change.get("source", "")
            tgt = sub_change.get("target", "")
            if src and tgt:
                delta.added_edges.append(EdgeChange(
                    source=src, target=tgt,
                    edge_type="subsystem",
                    reason=sub_change.get("reason", ""),
                ))


def _find_affected_subsystems(
    project_root: Path,
    delta: ArchitectureDelta,
) -> List[str]:
    """Determine which subsystems are affected by the delta."""
    system_path = project_root / ".codegraph" / "architecture" / "system.json"
    if not system_path.exists():
        return []

    try:
        system = json.loads(system_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    # Build module → subsystem mapping
    mod_to_sub: Dict[str, str] = {}
    for sub in system.get("subsystems", []):
        sub_name = sub["name"]
        for comp in sub.get("components", []):
            mod = comp.get("module", "")
            if mod:
                mod_to_sub[mod] = sub_name

    affected: Set[str] = set()
    all_modules: Set[str] = set()

    for n in delta.added_nodes + delta.removed_nodes:
        mod = n.module or (n.node_id.split("::")[0] if "::" in n.node_id else n.node_id)
        all_modules.add(mod)
    for e in delta.added_edges + delta.removed_edges:
        for nid in (e.source, e.target):
            mod = nid.split("::")[0] if "::" in nid else nid
            all_modules.add(mod)

    for mod in all_modules:
        sub = mod_to_sub.get(mod, "")
        if sub:
            affected.add(sub)

    return sorted(affected)


def _check_constraints(
    project_root: Path,
    delta: ArchitectureDelta,
) -> List[ConstraintViolation]:
    """Check if the delta violates architecture constraints."""
    system_path = project_root / ".codegraph" / "architecture" / "system.json"
    if not system_path.exists():
        return []

    try:
        system = json.loads(system_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    violations: List[ConstraintViolation] = []

    # Build module → subsystem mapping
    mod_to_sub: Dict[str, str] = {}
    for sub in system.get("subsystems", []):
        sub_name = sub["name"]
        for comp in sub.get("components", []):
            mod = comp.get("module", "")
            if mod:
                mod_to_sub[mod] = sub_name

    # Build forbidden deps
    forbidden: Set[tuple[str, str]] = set()
    for constraint in system.get("constraints", []):
        if constraint.get("type") == "forbidden_dependency":
            forbidden.add((constraint["source"], constraint["target"]))

    # Check added edges against constraints
    for edge in delta.added_edges:
        src_mod = edge.source.split("::")[0] if "::" in edge.source else edge.source
        tgt_mod = edge.target.split("::")[0] if "::" in edge.target else edge.target
        src_sub = mod_to_sub.get(src_mod, "")
        tgt_sub = mod_to_sub.get(tgt_mod, "")

        if src_sub and tgt_sub and (src_sub, tgt_sub) in forbidden:
            violations.append(ConstraintViolation(
                constraint_type="forbidden_dep",
                description=(
                    f"Forbidden dependency: {src_sub} -> {tgt_sub} "
                    f"({edge.source} -> {edge.target})"
                ),
                source=edge.source,
                target=edge.target,
            ))

    # Check that new nodes belong to a subsystem
    known_modules = set(mod_to_sub.keys())
    for node in delta.added_nodes:
        mod = node.module or node.node_id
        if mod and mod not in known_modules:
            # Check if any subsystem claims a prefix
            matched = any(mod.startswith(km.rstrip("*")) for km in known_modules)
            if not matched and node.node_type != "test":
                violations.append(ConstraintViolation(
                    constraint_type="undeclared_module",
                    description=f"Module {mod} not declared in any subsystem",
                    source=mod,
                    severity="warning",
                ))

    return violations


def _classify_delta_risk(delta: ArchitectureDelta) -> str:
    """Classify overall risk level of the delta."""
    errors = [v for v in delta.constraint_violations if v.severity == "error"]
    warnings = [v for v in delta.constraint_violations if v.severity == "warning"]

    if errors:
        return "BLOCKED"

    # High risk: many changes or multiple warnings
    if delta.total_changes > 30 or len(warnings) > 3:
        return "HIGH"

    if delta.total_changes > 15 or warnings:
        return "MEDIUM"

    return "LOW"
