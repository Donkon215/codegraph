"""codegraph.exceptions — Custom exception hierarchy.

Every failure mode listed in the README's Failure Modes table has a
corresponding exception here.  (Task A-007)
"""

from __future__ import annotations

from typing import Optional


class CodegraphError(Exception):
    """Base exception for all codegraph errors."""


# ── AST / Extraction ───────────────────────────────────────────────────


class ASTParseError(CodegraphError):
    """A source file could not be parsed into an AST."""

    def __init__(self, file: str, reason: str = "") -> None:
        self.file = file
        self.reason = reason
        super().__init__(f"AST parse error in {file}: {reason}" if reason else f"AST parse error in {file}")


class ModuleImportError(CodegraphError):
    """A module could not be resolved during extraction."""

    def __init__(self, module: str, file: str = "") -> None:
        self.module = module
        self.file = file
        super().__init__(f"Cannot resolve module '{module}'" + (f" in {file}" if file else ""))


# ── Graph Integrity ────────────────────────────────────────────────────


class NodeIDCollisionError(CodegraphError):
    """Two distinct AST entities produced the same node ID."""

    def __init__(self, node_id: str, file: str = "") -> None:
        self.node_id = node_id
        self.file = file
        super().__init__(f"Node ID collision: '{node_id}'" + (f" in {file}" if file else ""))


class IntentConflictError(CodegraphError):
    """Graph_1 intent clashes with an existing annotation."""

    def __init__(self, node_id: str) -> None:
        self.node_id = node_id
        super().__init__(f"Intent conflict for node '{node_id}'")


class StaleBodyHashError(CodegraphError):
    """body_hash changed since the last intent annotation."""

    def __init__(self, node_id: str, old_hash: str, new_hash: str) -> None:
        self.node_id = node_id
        self.old_hash = old_hash
        self.new_hash = new_hash
        super().__init__(
            f"Stale body_hash for '{node_id}': {old_hash} → {new_hash}"
        )


class GraphDriftError(CodegraphError):
    """Graph_0 structure no longer matches the source files."""

    def __init__(self, details: str = "") -> None:
        super().__init__(f"Graph drift detected{': ' + details if details else ''}")


# ── Tracing / Runtime ──────────────────────────────────────────────────


class TraceCrashError(CodegraphError):
    """Coverage-trace execution crashed during runtime profiling."""

    def __init__(self, file: str, reason: str = "") -> None:
        self.file = file
        self.reason = reason
        super().__init__(f"Trace crash in {file}: {reason}" if reason else f"Trace crash in {file}")


# ── Policy ─────────────────────────────────────────────────────────────


class DanglingRuleError(CodegraphError):
    """A suggested-workflow rule references a node that no longer exists."""

    def __init__(self, rule_id: str, node_id: str) -> None:
        self.rule_id = rule_id
        self.node_id = node_id
        super().__init__(f"Dangling rule '{rule_id}': references missing node '{node_id}'")


class LayerViolationError(CodegraphError):
    """An operation attempted to modify a node at a non-modifiable layer (0, 1, or 2)."""

    def __init__(self, node_id: str, layer: int) -> None:
        self.node_id = node_id
        self.layer = layer
        super().__init__(
            f"Cannot modify node '{node_id}' at layer {layer}. "
            f"Only layers 3 (project) and 4 (test) are modifiable."
        )


# ── Apply / Repair ─────────────────────────────────────────────────────


class RepairConflictError(CodegraphError):
    """Two repair actions conflict (e.g. overlapping edits)."""

    def __init__(self, action_a: str, action_b: str) -> None:
        self.action_a = action_a
        self.action_b = action_b
        super().__init__(f"Repair conflict between '{action_a}' and '{action_b}'")


class AlreadyConnectedError(CodegraphError):
    """An apply action tries to create an edge that already exists."""

    def __init__(self, source: str, target: str) -> None:
        self.source = source
        self.target = target
        super().__init__(f"Edge already exists: {source} → {target}")


class InsufficientDeadCodeSignalsError(CodegraphError):
    """Not enough signals to confidently mark code as dead."""

    def __init__(self, node_id: str, signals: int, required: int = 4) -> None:
        self.node_id = node_id
        self.signals = signals
        self.required = required
        super().__init__(
            f"Only {signals}/{required} dead-code signals for '{node_id}'"
        )


# ── Delta ──────────────────────────────────────────────────────────────


class DeltaUncommittedError(CodegraphError):
    """Delta was requested but there are uncommitted changes."""

    def __init__(self) -> None:
        super().__init__(
            "Uncommitted changes detected — commit first or run full build"
        )


class VersionMismatchError(CodegraphError):
    """agent_response.json references a different graph_version than current."""

    def __init__(self, expected: int, got: int) -> None:
        self.expected = expected
        self.got = got
        super().__init__(f"Graph version mismatch: expected {expected}, got {got}")


# ── Index ──────────────────────────────────────────────────────────────


class IndexInconsistencyError(CodegraphError):
    """Index tables are inconsistent with the underlying graph data."""

    def __init__(self, details: str = "") -> None:
        super().__init__(
            f"Index inconsistency{': ' + details if details else ''}"
        )


# ── Cycle ──────────────────────────────────────────────────────────────


class CycleMismatchError(CodegraphError):
    """Response cycle number does not match the current task cycle."""

    def __init__(self, expected: int, got: int) -> None:
        self.expected = expected
        self.got = got
        super().__init__(f"Cycle mismatch: expected {expected}, got {got}")


# ── Project ────────────────────────────────────────────────────────────


class ProjectNotFoundError(CodegraphError):
    """Could not locate a codegraph project root."""

    def __init__(self, search_start: str = ".") -> None:
        self.search_start = search_start
        super().__init__(
            f"No codegraph project found (searched upward from {search_start})"
        )


class FormatVersionError(CodegraphError):
    """Data file has an incompatible format_version."""

    def __init__(self, file: str, expected: int, got: int) -> None:
        self.file = file
        self.expected = expected
        self.got = got
        super().__init__(
            f"Format version mismatch in {file}: expected {expected}, got {got}"
        )
