"""codegraph.architecture_change — canonical proposed-change model (v1.2 issue #27/A).

A single schema that unifies the four parallel "proposed change" models that
already exist in the codebase:

  - AgentResponse.repairs   (codegraph.models.agent_response.RepairAction)
  - SimulatedChange         (codegraph.simulator.SimulatedChange)
  - ArchChange              (codegraph.architecture_simulator.ArchChange)
  - PlannedTask             (codegraph.arch_planner.PlannedTask)

It is the input contract every later stage (delta, simulate, policy, agent
loop) consumes. Public JSON shape matches the product vision:

    {
      "add": ["service.payment"],
      "remove": [],
      "modify": ["service.order"],
      "relationships": [{"action": "add", "from": "order", "to": "payment", "type": "calls"}],
      "constraints": [{"action": "add", "type": "forbidden", "source": "ui", "target": "db", "reason": ""}]
    }
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List

from codegraph.arch_schema import ArchConstraint
from codegraph.logging_config import get_logger

logger = get_logger("architecture_change")


@dataclass
class ArchRelationship:
    """An edge change between two nodes (add or remove)."""

    action: str = "add"  # "add" | "remove"
    from_: str = ""
    to: str = ""
    type: str = "calls"  # "calls" | "depends" | "data_flow"

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"action": self.action, "from": self.from_, "to": self.to}
        if self.type != "calls":
            d["type"] = self.type
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ArchRelationship":
        if isinstance(d, list) and len(d) >= 2:
            return cls(action="add", from_=d[0], to=d[1])
        return cls(
            action=d.get("action", "add"),
            from_=d.get("from", ""),
            to=d.get("to", ""),
            type=d.get("type", "calls"),
        )


@dataclass
class ConstraintChange:
    """Add or remove an architectural constraint (reuses ArchConstraint)."""

    action: str = "add"  # "add" | "remove"
    constraint: ArchConstraint = field(default_factory=ArchConstraint)

    def to_dict(self) -> Dict[str, Any]:
        d = self.constraint.to_dict()
        d["action"] = self.action
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ConstraintChange":
        return cls(action=d.get("action", "add"), constraint=ArchConstraint.from_dict(d))


@dataclass
class ArchitectureChange:
    """The single canonical representation of a proposed architectural change."""

    add: List[str] = field(default_factory=list)
    remove: List[str] = field(default_factory=list)
    modify: List[str] = field(default_factory=list)
    relationships: List[ArchRelationship] = field(default_factory=list)
    constraints: List[ConstraintChange] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {}
        if self.add:
            d["add"] = list(self.add)
        if self.remove:
            d["remove"] = list(self.remove)
        if self.modify:
            d["modify"] = list(self.modify)
        if self.relationships:
            d["relationships"] = [r.to_dict() for r in self.relationships]
        if self.constraints:
            d["constraints"] = [c.to_dict() for c in self.constraints]
        return d

    def to_json(self, compact: bool = False) -> str:
        return json.dumps(self.to_dict(), indent=None if compact else 2, ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ArchitectureChange":
        return cls(
            add=list(d.get("add", [])),
            remove=list(d.get("remove", [])),
            modify=list(d.get("modify", [])),
            relationships=[ArchRelationship.from_dict(x) for x in d.get("relationships", [])],
            constraints=[ConstraintChange.from_dict(x) for x in d.get("constraints", [])],
        )

    @classmethod
    def from_json(cls, text: str) -> "ArchitectureChange":
        return cls.from_dict(json.loads(text))

    # ── Adapters from the legacy parallel models ─────────────────────────

    @classmethod
    def from_agent_response(cls, ar: "Any") -> "ArchitectureChange":
        """Map AgentResponse.repairs into a proposed change.

        connect_call/add_import -> relationship; remove_dead_code -> remove node
        or edge; flag_for_human_review is a review note, not a topology change.
        """
        from codegraph.models.agent_response import RepairActionType

        ch = cls()
        for r in ar.repairs:
            if r.action == RepairActionType.CONNECT_CALL.value:
                ch.relationships.append(
                    ArchRelationship(action="add", from_=r.node, to=r.target or "", type="calls")
                )
            elif r.action == RepairActionType.ADD_IMPORT.value:
                ch.relationships.append(
                    ArchRelationship(action="add", from_=r.node, to=r.target or "", type="depends")
                )
            elif r.action == RepairActionType.REMOVE_DEAD_CODE.value:
                if r.target:
                    ch.relationships.append(
                        ArchRelationship(action="remove", from_=r.node, to=r.target, type="calls")
                    )
                else:
                    ch.remove.append(r.node)
            # FLAG_FOR_HUMAN_REVIEW is intentionally ignored (review, not change)
        return ch

    @classmethod
    def from_planned_tasks(cls, tasks: "List[Any]") -> "ArchitectureChange":
        """Map arch_planner.PlannedTask list into a proposed change."""
        ch = cls()
        for t in tasks:
            if t.task_type == "create_module":
                if t.module:
                    ch.add.append(t.module)
            elif t.task_type == "create_function":
                ident = f"{t.module}::{t.function}" if t.module else (t.function or t.source)
                if ident:
                    ch.add.append(ident)
            elif t.task_type == "connect_call":
                src = t.source or t.module
                tgt = t.target or t.function
                if src and tgt:
                    ch.relationships.append(
                        ArchRelationship(action="add", from_=src, to=tgt, type="calls")
                    )
            elif t.task_type == "add_constraint":
                ch.constraints.append(
                    ConstraintChange(
                        action="add",
                        constraint=ArchConstraint(
                            constraint_type="forbidden",
                            source=t.source,
                            target=t.target,
                            reason=t.reason,
                        ),
                    )
                )
            # flag_violation is intentionally ignored (review, not change)
        return ch

    @classmethod
    def from_simulated_changes(cls, changes: "List[Any]") -> "ArchitectureChange":
        """Map simulator.SimulatedChange list into a proposed change."""
        ch = cls()
        for c in changes:
            if c.action == "add_node":
                ch.add.append(c.node_id or c.source)
            elif c.action == "remove_node":
                ch.remove.append(c.node_id or c.source)
            elif c.action == "add_edge":
                ch.relationships.append(
                    ArchRelationship(action="add", from_=c.source, to=c.target)
                )
            elif c.action == "remove_edge":
                ch.relationships.append(
                    ArchRelationship(action="remove", from_=c.source, to=c.target)
                )
        return ch

    @classmethod
    def from_arch_changes(cls, changes: "List[Any]") -> "ArchitectureChange":
        """Map architecture_simulator.ArchChange list into a proposed change."""
        ch = cls()
        for c in changes:
            if c.action == "add_subsystem":
                if c.subsystem:
                    ch.add.append(c.subsystem)
            elif c.action in ("remove_subsystem", "split_subsystem", "merge_subsystems"):
                if c.subsystem:
                    ch.modify.append(c.subsystem)
                ch.modify.extend(c.components)
            elif c.action == "add_component":
                ch.add.append(c.component_name or c.module_path)
            elif c.action == "add_edge":
                ch.relationships.append(
                    ArchRelationship(action="add", from_=c.subsystem, to=c.target_subsystem)
                )
            elif c.action == "remove_edge":
                ch.relationships.append(
                    ArchRelationship(action="remove", from_=c.subsystem, to=c.target_subsystem)
                )
            elif c.action == "add_constraint":
                ch.constraints.append(
                    ConstraintChange(
                        action="add",
                        constraint=ArchConstraint(
                            constraint_type=c.constraint_type or "forbidden",
                            source=c.subsystem,
                            target=c.target_subsystem,
                            reason=c.reason,
                        ),
                    )
                )
        return ch

    # ── Bridge to the existing simulation engine ──────────────────────────

    def to_simulated_changes(self) -> "List[Any]":
        """Emit SimulatedChange objects the existing simulator can consume.

        Constraints are policy-layer, not dependency-graph mutations, so they
        are not expressed here (handled by issues B/E on the architecture graph).
        """
        from codegraph.simulator import SimulatedChange

        out: List[SimulatedChange] = []
        for node in self.add:
            out.append(SimulatedChange(action="add_node", node_id=node))
        for node in self.remove:
            out.append(SimulatedChange(action="remove_node", node_id=node))
        for rel in self.relationships:
            out.append(
                SimulatedChange(
                    action="add_edge" if rel.action == "add" else "remove_edge",
                    source=rel.from_,
                    target=rel.to,
                )
            )
        return out
