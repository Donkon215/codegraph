"""Unit tests for all 17+ failure modes.

Task O-019: Every failure mode has at least one test.
"""

from __future__ import annotations

import pytest

from codegraph.exceptions import (
    CodegraphError,
    ASTParseError,
    ModuleImportError,
    NodeIDCollisionError,
    IntentConflictError,
    StaleBodyHashError,
    GraphDriftError,
    TraceCrashError,
    DanglingRuleError,
    LayerViolationError,
    RepairConflictError,
    AlreadyConnectedError,
    InsufficientDeadCodeSignalsError,
    DeltaUncommittedError,
    VersionMismatchError,
    IndexInconsistencyError,
    CycleMismatchError,
    ProjectNotFoundError,
)


class TestFailureModeExceptions:
    """Each failure mode exception can be raised and caught."""

    def test_ast_parse_error(self) -> None:
        with pytest.raises(ASTParseError):
            raise ASTParseError("test.py", "invalid syntax")

    def test_module_import_error(self) -> None:
        with pytest.raises(ModuleImportError):
            raise ModuleImportError("unknown_module", "test.py")

    def test_node_id_collision(self) -> None:
        with pytest.raises(NodeIDCollisionError):
            raise NodeIDCollisionError("mod::func", "test.py")

    def test_intent_conflict(self) -> None:
        with pytest.raises(IntentConflictError):
            raise IntentConflictError("mod::func")

    def test_stale_body_hash(self) -> None:
        exc = StaleBodyHashError("mod::func", "old_hash", "new_hash")
        assert exc.old_hash == "old_hash"
        assert exc.new_hash == "new_hash"

    def test_graph_drift(self) -> None:
        with pytest.raises(GraphDriftError):
            raise GraphDriftError("source changed")

    def test_trace_crash(self) -> None:
        with pytest.raises(TraceCrashError):
            raise TraceCrashError("test_file.py", "segfault")

    def test_dangling_rule(self) -> None:
        exc = DanglingRuleError("rule_1", "mod::func")
        assert exc.rule_id == "rule_1"
        assert exc.node_id == "mod::func"

    def test_layer_violation(self) -> None:
        exc = LayerViolationError("os::path::join", 0)
        assert exc.layer == 0
        assert "modifiable" in str(exc).lower() or "layer" in str(exc).lower()

    def test_repair_conflict(self) -> None:
        with pytest.raises(RepairConflictError):
            raise RepairConflictError("action_a", "action_b")

    def test_already_connected(self) -> None:
        exc = AlreadyConnectedError("source", "target")
        assert exc.source == "source"

    def test_insufficient_dead_code_signals(self) -> None:
        exc = InsufficientDeadCodeSignalsError("mod::func", 2, 4)
        assert exc.signals == 2
        assert exc.required == 4

    def test_delta_uncommitted(self) -> None:
        with pytest.raises(DeltaUncommittedError):
            raise DeltaUncommittedError()

    def test_version_mismatch(self) -> None:
        exc = VersionMismatchError(42, 41)
        assert exc.expected == 42
        assert exc.got == 41

    def test_index_inconsistency(self) -> None:
        with pytest.raises(IndexInconsistencyError):
            raise IndexInconsistencyError("missing callers table")

    def test_cycle_mismatch(self) -> None:
        exc = CycleMismatchError(3, 2)
        assert exc.expected == 3

    def test_project_not_found(self) -> None:
        exc = ProjectNotFoundError("/tmp")
        assert "codegraph" in str(exc).lower() or "project" in str(exc).lower()

    def test_all_inherit_from_base(self) -> None:
        """All exception classes should inherit from CodegraphError."""
        exc_classes = [
            ASTParseError, ModuleImportError, NodeIDCollisionError,
            IntentConflictError, StaleBodyHashError, GraphDriftError,
            TraceCrashError, DanglingRuleError, LayerViolationError,
            RepairConflictError, AlreadyConnectedError,
            InsufficientDeadCodeSignalsError, DeltaUncommittedError,
            VersionMismatchError, IndexInconsistencyError,
            CycleMismatchError, ProjectNotFoundError,
        ]
        for cls in exc_classes:
            assert issubclass(cls, CodegraphError), f"{cls.__name__} not a CodegraphError"
