"""PHASE 2 tests for the canonical ArchitectureChange IR (v1.2 issue #27).

Covers: round-trip, structural schema validation, contradiction rejection,
deterministic normalization. Adapter equivalence is PHASE 4 (not here).
"""

import pytest

from codegraph.architecture_change import (
    ArchitectureChange,
    ArchitectureChangeValidationError,
    ArchitectureOperation,
    OpType,
    EDGE_TYPE_CANONICAL,
)


def _ac(ops, base_version=1, reason="test"):
    return ArchitectureChange(
        base_version=base_version, reason=reason, operations=ops
    )


# ── Round-trip ──────────────────────────────────────────────────────────

def test_round_trip_dict():
    ac = _ac([
        ArchitectureOperation(OpType.ADD_SUBSYSTEM, subsystem="billing"),
        ArchitectureOperation(OpType.ADD_EDGE, source="a", target="b", edge_type="call"),
    ])
    assert ArchitectureChange.from_dict(ac.to_dict()) == ac


def test_round_trip_json():
    ac = _ac([
        ArchitectureOperation(OpType.ADD_COMPONENT, component="svc/pay.py",
                              component_subsystem="billing", component_name="Payment"),
        ArchitectureOperation(OpType.ADD_CONSTRAINT, constraint_type="forbidden_dependency",
                              source="ui", target="db", reason="no direct"),
    ])
    assert ArchitectureChange.from_json(ac.to_json()) == ac


# ── Structural validation (accept) ───────────────────────────────────────

def test_valid_change_passes():
    ac = _ac([
        ArchitectureOperation(OpType.ADD_SUBSYSTEM, subsystem="x"),
        ArchitectureOperation(OpType.REMOVE_SUBSYSTEM, subsystem="y"),
        ArchitectureOperation(OpType.ADD_EDGE, source="x", target="y", edge_type="dependency"),
    ])
    ac.validate()  # no raise


# ── Structural validation (reject) ───────────────────────────────────────

def test_bad_base_version_rejected():
    ac = ArchitectureChange(base_version="not-int", operations=[])
    with pytest.raises(ArchitectureChangeValidationError):
        ac.validate()


def test_unknown_op_rejected():
    with pytest.raises(ArchitectureChangeValidationError):
        ArchitectureOperation.from_dict({"op": "frob"})


def test_edge_missing_endpoints_rejected():
    ac = _ac([ArchitectureOperation(OpType.ADD_EDGE, source="a", edge_type="call")])
    with pytest.raises(ArchitectureChangeValidationError):
        ac.validate()


def test_non_canonical_edge_type_rejected():
    ac = _ac([ArchitectureOperation(OpType.ADD_EDGE, source="a", target="b", edge_type="calls")])
    with pytest.raises(ArchitectureChangeValidationError):
        ac.validate()


def test_constraint_missing_source_rejected():
    ac = _ac([ArchitectureOperation(OpType.ADD_CONSTRAINT, constraint_type="forbidden",
                                    target="db")])
    with pytest.raises(ArchitectureChangeValidationError):
        ac.validate()


def test_add_component_requires_subsystem_rejected():
    ac = _ac([ArchitectureOperation(OpType.ADD_COMPONENT, component="svc/x.py")])
    with pytest.raises(ArchitectureChangeValidationError):
        ac.validate()


# ── Contradiction rejection ──────────────────────────────────────────────

def test_add_remove_same_subsystem_rejected():
    ac = _ac([
        ArchitectureOperation(OpType.ADD_SUBSYSTEM, subsystem="x"),
        ArchitectureOperation(OpType.REMOVE_SUBSYSTEM, subsystem="x"),
    ])
    with pytest.raises(ArchitectureChangeValidationError):
        ac.validate()


def test_duplicate_add_edge_rejected():
    ac = _ac([
        ArchitectureOperation(OpType.ADD_EDGE, source="a", target="b", edge_type="call"),
        ArchitectureOperation(OpType.ADD_EDGE, source="a", target="b", edge_type="call"),
    ])
    with pytest.raises(ArchitectureChangeValidationError):
        ac.validate()


def test_add_remove_same_edge_rejected():
    ac = _ac([
        ArchitectureOperation(OpType.ADD_EDGE, source="a", target="b", edge_type="call"),
        ArchitectureOperation(OpType.REMOVE_EDGE, source="a", target="b", edge_type="call"),
    ])
    with pytest.raises(ArchitectureChangeValidationError):
        ac.validate()


def test_different_edge_types_not_contradictory():
    # (a,b,call) and (a,b,depends) are distinct edges -> allowed
    ac = _ac([
        ArchitectureOperation(OpType.ADD_EDGE, source="a", target="b", edge_type="call"),
        ArchitectureOperation(OpType.ADD_EDGE, source="a", target="b", edge_type="dependency"),
    ])
    ac.validate()  # no raise


# ── Normalization (deterministic, does NOT erase contradictions) ──────────

def test_normalize_is_order_independent():
    a = _ac([
        ArchitectureOperation(OpType.ADD_EDGE, source="a", target="b", edge_type="call"),
        ArchitectureOperation(OpType.ADD_SUBSYSTEM, subsystem="x"),
    ])
    b = _ac([
        ArchitectureOperation(OpType.ADD_SUBSYSTEM, subsystem="x"),
        ArchitectureOperation(OpType.ADD_EDGE, source="a", target="b", edge_type="call"),
    ])
    assert a.normalize() == b.normalize()
    assert a.normalize().to_json() == b.normalize().to_json()


def test_normalize_defaults_edge_type():
    ac = _ac([ArchitectureOperation(OpType.ADD_EDGE, source="a", target="b")])
    norm = ac.normalize()
    assert norm.operations[0].edge_type == "call"
    norm.validate()  # normalized form is structurally valid


def test_normalize_keeps_contradiction_for_validation():
    # The contradiction must survive normalization so validate() can reject it.
    ac = _ac([
        ArchitectureOperation(OpType.ADD_SUBSYSTEM, subsystem="x"),
        ArchitectureOperation(OpType.REMOVE_SUBSYSTEM, subsystem="x"),
    ])
    norm = ac.normalize()
    assert len(norm.operations) == 2  # NOT collapsed
    with pytest.raises(ArchitectureChangeValidationError):
        norm.validate()


def test_edge_type_vocabulary_locked():
    assert EDGE_TYPE_CANONICAL == ("call", "dependency", "data_flow")
