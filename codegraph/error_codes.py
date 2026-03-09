"""codegraph.error_codes — Structured error code registry.

Each error code maps to a specific failure mode with a human-readable
message and suggested recovery action.

Task P-024.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from codegraph.exceptions import (
    ASTParseError,
    AlreadyConnectedError,
    CodegraphError,
    CycleMismatchError,
    DanglingRuleError,
    DeltaUncommittedError,
    GraphDriftError,
    IndexInconsistencyError,
    InsufficientDeadCodeSignalsError,
    IntentConflictError,
    LayerViolationError,
    ModuleImportError,
    NodeIDCollisionError,
    ProjectNotFoundError,
    RepairConflictError,
    StaleBodyHashError,
    TraceCrashError,
    VersionMismatchError,
)


@dataclass(frozen=True)
class ErrorCode:
    """A registered error code with metadata."""

    code: str
    name: str
    message: str
    recovery: str
    exception_type: Optional[type] = None


# ── Registry ───────────────────────────────────────────────────────────

_CODES: dict[str, ErrorCode] = {}


def _register(code: str, name: str, message: str, recovery: str,
              exc_type: Optional[type] = None) -> ErrorCode:
    entry = ErrorCode(code=code, name=name, message=message,
                      recovery=recovery, exception_type=exc_type)
    _CODES[code] = entry
    return entry


# Extraction errors (E1xx)
E100 = _register("E100", "ASTParseError",
                  "Source file could not be parsed",
                  "Fix syntax errors in the file and rebuild",
                  ASTParseError)
E101 = _register("E101", "ModuleImportError",
                  "Module could not be resolved",
                  "Install the missing module or check import paths",
                  ModuleImportError)

# Graph integrity (E2xx)
E200 = _register("E200", "NodeIDCollision",
                  "Two entities produced the same node ID",
                  "Rename conflicting entities and run build --full",
                  NodeIDCollisionError)
E201 = _register("E201", "IntentConflict",
                  "Intent annotation conflicts with existing",
                  "Review and resolve conflicting intents",
                  IntentConflictError)
E202 = _register("E202", "StaleBodyHash",
                  "Function body changed since intent annotation",
                  "Re-annotate the intent after reviewing changes",
                  StaleBodyHashError)
E203 = _register("E203", "GraphDrift",
                  "Graph structure does not match source files",
                  "Run codegraph build to regenerate",
                  GraphDriftError)

# Runtime (E3xx)
E300 = _register("E300", "TraceCrash",
                  "Coverage trace crashed during profiling",
                  "Check test and retry with build --full",
                  TraceCrashError)

# Policy (E4xx)
E400 = _register("E400", "DanglingRule",
                  "Rule references a missing node",
                  "Run suggest validate and remove dangling rules",
                  DanglingRuleError)
E401 = _register("E401", "LayerViolation",
                  "Operation on non-modifiable layer",
                  "Only modify nodes at layer 3 or 4",
                  LayerViolationError)

# Apply / Repair (E5xx)
E500 = _register("E500", "RepairConflict",
                  "Two repair actions conflict",
                  "Apply actions one at a time to isolate conflicts",
                  RepairConflictError)
E501 = _register("E501", "AlreadyConnected",
                  "Edge already exists",
                  "Skip duplicate edge creation",
                  AlreadyConnectedError)
E502 = _register("E502", "InsufficientDeadCodeSignals",
                  "Not enough signals for dead code classification",
                  "Add more analysis passes before pruning",
                  InsufficientDeadCodeSignalsError)

# Delta (E6xx)
E600 = _register("E600", "DeltaUncommitted",
                  "Uncommitted changes prevent delta",
                  "Commit or stash changes first",
                  DeltaUncommittedError)
E601 = _register("E601", "VersionMismatch",
                  "Graph version does not match response",
                  "Re-read graph_0.json for current version",
                  VersionMismatchError)

# Index (E7xx)
E700 = _register("E700", "IndexInconsistency",
                  "Index tables inconsistent with graph data",
                  "Run codegraph index rebuild",
                  IndexInconsistencyError)

# Cycle (E8xx)
E800 = _register("E800", "CycleMismatch",
                  "Response cycle does not match current cycle",
                  "Check current cycle with codegraph status",
                  CycleMismatchError)

# Project (E9xx)
E900 = _register("E900", "ProjectNotFound",
                  "No codegraph project found",
                  "Run codegraph init to initialize a project",
                  ProjectNotFoundError)


def lookup(code: str) -> Optional[ErrorCode]:
    """Look up an error code by its string key."""
    return _CODES.get(code)


def lookup_by_exception(exc: Exception) -> Optional[ErrorCode]:
    """Find the error code for a given exception instance."""
    exc_type = type(exc)
    for entry in _CODES.values():
        if entry.exception_type is not None and isinstance(exc, entry.exception_type):
            return entry
    return None


def all_codes() -> list[ErrorCode]:
    """Return all registered error codes."""
    return list(_CODES.values())
