"""codegraph.architecture_change — canonical ArchitectureChange IR (v1.2 issue #27).

This module is the INTERMEDIATE REPRESENTATION (IR) for a proposed architectural
transformation. It is a DESCRIPTION ONLY: it does NOT apply changes to
SystemArchitecture, does NOT contain source-code edits, and does NOT perform
simulation. Mutating the architecture / simulating is a separate later stage.

Pipeline:
    raw ArchitectureChange -> normalize() -> validate() -> accept / reject
    normalize() canonicalizes ordering + defaults; it NEVER erases contradictory
    intent. Contradictions are rejected by validate(), not hidden by normalize().

Identity (from repo evidence, PHASE 1 audit):
    subsystem   = SubsystemDef.name
    component   = module path (the de-facto architecture<->code link key)
    edge        = (source, target, edge_type)
    constraint  = (constraint_type, source, target)  # constraint_type kept VERBATIM

Edge-type vocabulary is LOCKED to the architecture layer's tokens
(arch_schema.ArchEdge: "call" / "dependency" / "data_flow"). Legacy tokens such as
"calls" / "depends" / "depends_on" are mapped to canonical form ONLY at adapter
boundaries (PHASE 3) via EDGE_TYPE_ALIASES below — no casual invention.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

__all__ = [
    "OpType",
    "ArchitectureOperation",
    "ArchitectureChange",
    "ArchitectureChangeError",
    "ArchitectureChangeValidationError",
    "EDGE_TYPE_CANONICAL",
    "EDGE_TYPE_ALIASES",
    "canonical_edge_type",
]


class ArchitectureChangeError(Exception):
    """Base error for ArchitectureChange."""


class ArchitectureChangeValidationError(ArchitectureChangeError):
    """Raised when an ArchitectureChange fails structural validation."""


class OpType(str, Enum):
    ADD_SUBSYSTEM = "add_subsystem"
    REMOVE_SUBSYSTEM = "remove_subsystem"
    ADD_COMPONENT = "add_component"
    REMOVE_COMPONENT = "remove_component"
    ADD_EDGE = "add_edge"
    REMOVE_EDGE = "remove_edge"
    ADD_CONSTRAINT = "add_constraint"
    REMOVE_CONSTRAINT = "remove_constraint"


_ADD_OPS = {
    OpType.ADD_SUBSYSTEM,
    OpType.ADD_COMPONENT,
    OpType.ADD_EDGE,
    OpType.ADD_CONSTRAINT,
}
_REMOVE_OPS = {
    OpType.REMOVE_SUBSYSTEM,
    OpType.REMOVE_COMPONENT,
    OpType.REMOVE_EDGE,
    OpType.REMOVE_CONSTRAINT,
}

# Canonical edge types — exactly ArchEdge.edge_type vocabulary (arch_schema.py:71).
EDGE_TYPE_CANONICAL = ("call", "dependency", "data_flow")

# Adapter vocabulary lock (used in PHASE 3). Legacy token -> canonical token.
# The IR itself only accepts EDGE_TYPE_CANONICAL; adapters translate via this map.
EDGE_TYPE_ALIASES = {
    "call": "call",
    "calls": "call",
    "dependency": "dependency",
    "depends": "dependency",
    "depends_on": "dependency",
    "data_flow": "data_flow",
    "dataflow": "data_flow",
}


def canonical_edge_type(token: str) -> str:
    """Map a (possibly legacy) edge-type token to its canonical form.

    Unknown tokens are returned unchanged; validate() will reject them. This is
    the single place adapters resolve vocabulary divergence — no other code may
    invent its own translation.
    """
    if token in EDGE_TYPE_CANONICAL:
        return token
    return EDGE_TYPE_ALIASES.get(token, token)


_OP_RANK = {
    OpType.ADD_SUBSYSTEM: 0,
    OpType.REMOVE_SUBSYSTEM: 1,
    OpType.ADD_COMPONENT: 2,
    OpType.REMOVE_COMPONENT: 3,
    OpType.ADD_EDGE: 4,
    OpType.REMOVE_EDGE: 5,
    OpType.ADD_CONSTRAINT: 6,
    OpType.REMOVE_CONSTRAINT: 7,
}

_OP_FIELDS = (
    "subsystem",
    "component",
    "component_subsystem",
    "component_name",
    "source",
    "target",
    "edge_type",
    "constraint_type",
    "reason",
)


@dataclass
class ArchitectureOperation:
    """A single typed operation of an ArchitectureChange."""

    op: OpType
    subsystem: str = ""
    component: str = ""  # module path (component identity)
    component_subsystem: str = ""  # owning subsystem for add_component
    component_name: str = ""  # optional label
    source: str = ""
    target: str = ""
    edge_type: str = ""
    constraint_type: str = ""  # VERBATIM (e.g. forbidden / forbidden_dependency)
    reason: str = ""

    def _identity(self) -> tuple:
        """Identity used for contradiction/duplicate detection (op-independent)."""
        if self.op in (OpType.ADD_SUBSYSTEM, OpType.REMOVE_SUBSYSTEM):
            return ("subsystem", self.subsystem)
        if self.op in (OpType.ADD_COMPONENT, OpType.REMOVE_COMPONENT):
            return ("component", self.component)
        if self.op in (OpType.ADD_EDGE, OpType.REMOVE_EDGE):
            return ("edge", self.source, self.target, self.edge_type)
        if self.op in (OpType.ADD_CONSTRAINT, OpType.REMOVE_CONSTRAINT):
            return ("constraint", self.constraint_type, self.source, self.target)
        return ("?",)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"op": self.op.value}
        for f in _OP_FIELDS:
            v = getattr(self, f)
            if v:
                d[f] = v
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ArchitectureOperation":
        try:
            op = OpType(d["op"])
        except (ValueError, KeyError):
            raise ArchitectureChangeValidationError(
                f"unknown or missing operation type: {d.get('op')!r}"
            )
        return cls(
            op=op,
            subsystem=d.get("subsystem", ""),
            component=d.get("component", ""),
            component_subsystem=d.get("component_subsystem", ""),
            component_name=d.get("component_name", ""),
            source=d.get("source", ""),
            target=d.get("target", ""),
            edge_type=d.get("edge_type", ""),
            constraint_type=d.get("constraint_type", ""),
            reason=d.get("reason", ""),
        )


@dataclass
class ArchitectureChange:
    """Canonical representation of a proposed architectural transformation.

    Description only. States intent; does not apply or simulate.
    """

    base_version: int = 0
    reason: str = ""
    operations: List[ArchitectureOperation] = field(default_factory=list)
    id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ── Serialization ────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "base_version": self.base_version,
            "operations": [o.to_dict() for o in self.operations],
        }
        if self.id is not None:
            d["id"] = self.id
        if self.reason:
            d["reason"] = self.reason
        if self.metadata:
            d["metadata"] = self.metadata
        return d

    def to_json(self, compact: bool = False) -> str:
        return json.dumps(self.to_dict(), indent=None if compact else 2, ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ArchitectureChange":
        if not isinstance(d, dict):
            raise ArchitectureChangeValidationError("ArchitectureChange must be an object")
        try:
            base_version = int(d.get("base_version", 0))
        except (TypeError, ValueError):
            raise ArchitectureChangeValidationError("base_version must be an integer")
        return cls(
            base_version=base_version,
            reason=d.get("reason", "") or "",
            operations=[ArchitectureOperation.from_dict(o) for o in d.get("operations", [])],
            id=d.get("id"),
            metadata=d.get("metadata", {}) or {},
        )

    @classmethod
    def from_json(cls, text: str) -> "ArchitectureChange":
        return cls.from_dict(json.loads(text))

    # ── Validation (structural) ───────────────────────────────────────────

    def validate(self) -> None:
        """Structural validation. Raises ArchitectureChangeValidationError.

        Catches: bad base_version, missing required fields, unknown/non-canonical
        edge_type, and CONTRADICTORY or DUPLICATE operations. Malformed proposed
        changes are rejected here, never silently normalized away.
        """
        if isinstance(self.base_version, bool) or not isinstance(self.base_version, int):
            raise ArchitectureChangeValidationError("base_version must be an integer")
        if not isinstance(self.reason, str):
            raise ArchitectureChangeValidationError("reason must be a string")

        seen_exact: set = set()
        add_seen: Dict[tuple, bool] = {}
        remove_seen: Dict[tuple, bool] = {}
        for op in self.operations:
            self._validate_op(op)
            ident = op._identity()
            exact = (op.op.value, ident)
            if exact in seen_exact:
                raise ArchitectureChangeValidationError(
                    f"duplicate operation: {op.op.value} {ident}"
                )
            seen_exact.add(exact)
            if op.op in _ADD_OPS:
                if ident in remove_seen:
                    raise ArchitectureChangeValidationError(
                        f"contradictory operation: add and remove same target {ident}"
                    )
                add_seen[ident] = True
            else:
                if ident in add_seen:
                    raise ArchitectureChangeValidationError(
                        f"contradictory operation: add and remove same target {ident}"
                    )
                remove_seen[ident] = True

    @staticmethod
    def _validate_op(op: ArchitectureOperation) -> None:
        if not isinstance(op.op, OpType):
            raise ArchitectureChangeValidationError(f"unknown operation type: {op.op!r}")
        t = op.op
        if t in (OpType.ADD_SUBSYSTEM, OpType.REMOVE_SUBSYSTEM):
            if not op.subsystem:
                raise ArchitectureChangeValidationError("subsystem operation requires 'subsystem'")
        elif t in (OpType.ADD_COMPONENT, OpType.REMOVE_COMPONENT):
            if not op.component:
                raise ArchitectureChangeValidationError(
                    "component operation requires 'component' (module path)"
                )
            if t == OpType.ADD_COMPONENT and not op.component_subsystem:
                raise ArchitectureChangeValidationError(
                    "add_component requires 'component_subsystem'"
                )
        elif t in (OpType.ADD_EDGE, OpType.REMOVE_EDGE):
            if not op.source or not op.target:
                raise ArchitectureChangeValidationError("edge operation requires 'source' and 'target'")
            if op.edge_type and op.edge_type not in EDGE_TYPE_CANONICAL:
                raise ArchitectureChangeValidationError(
                    f"edge_type must be one of {EDGE_TYPE_CANONICAL}, got {op.edge_type!r}"
                )
        elif t in (OpType.ADD_CONSTRAINT, OpType.REMOVE_CONSTRAINT):
            if not op.constraint_type:
                raise ArchitectureChangeValidationError(
                    "constraint operation requires 'constraint_type' (kept verbatim)"
                )
            if not op.source or not op.target:
                raise ArchitectureChangeValidationError(
                    "constraint operation requires 'source' and 'target'"
                )

    # ── Normalization (representation only) ──────────────────────────────

    def normalize(self) -> "ArchitectureChange":
        """Return a canonical form: sorted operations + default edge_type.

        Deliberately does NOT dedupe or cancel add/remove pairs — contradictions
        remain detectable and are the job of validate(). Two descriptions of the
        same intent normalize to the same object (deterministic serialization).
        """
        normed: List[ArchitectureOperation] = []
        for op in self.operations:
            if op.op in (OpType.ADD_EDGE, OpType.REMOVE_EDGE) and not op.edge_type:
                op = ArchitectureOperation(
                    op.op,
                    subsystem=op.subsystem,
                    component=op.component,
                    component_subsystem=op.component_subsystem,
                    component_name=op.component_name,
                    source=op.source,
                    target=op.target,
                    edge_type="call",
                    constraint_type=op.constraint_type,
                    reason=op.reason,
                )
            normed.append(op)
        normed.sort(key=lambda o: (_OP_RANK[o.op], o.op.value, str(o._identity())))
        return ArchitectureChange(
            base_version=self.base_version,
            reason=self.reason,
            operations=normed,
            id=self.id,
            metadata=self.metadata,
        )
