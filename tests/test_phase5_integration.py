"""PHASE 5 — integration: ArchitectureChange as the simulator boundary (issue #27).

Proves the IR round-trips through the existing simulator identically to the
legacy ArchChange path, without changing simulator semantics, without #28,
and WITHOUT silently collapsing component/function edges to subsystem edges.

Legacy A = simulate_architecture_changes([ArchChange], arch)
IR B    = simulate(ArchitectureChange, arch)   # validate -> reverse adapter -> same engine
Assert A == B on predictions/safe/recommendation.
"""

import pytest
from codegraph.architecture_change import (
    ArchitectureChange,
    ArchitectureOperation,
    OpType,
    ArchitectureChangeValidationError,
)
from codegraph.architecture_simulator import (
    simulate,
    simulate_architecture_changes,
    ArchChange,
)
from codegraph.arch_schema import (
    SystemArchitecture,
    SubsystemDef,
    ArchComponent,
    ArchEdge,
    ArchConstraint,
)


def _arch() -> SystemArchitecture:
    return SystemArchitecture(name="fx", subsystems=[
        SubsystemDef(name="S", components=[
            ArchComponent(name="A", module="a.py"),
            ArchComponent(name="B", module="b.py"),
        ], edges=[ArchEdge("A", "B")]),
        SubsystemDef(name="T", components=[ArchComponent(name="C", module="c.py")]),
        SubsystemDef(name="N", components=[]),
    ], edges=[ArchEdge("S", "T")],
       constraints=[ArchConstraint(constraint_type="forbidden_dependency",
                                    source="T", target="S")])


def _sim_equal(a, b) -> None:
    da, db = a.to_dict(), b.to_dict()
    assert da["safe"] == db["safe"]
    assert da["recommendation"] == db["recommendation"]
    key = lambda p: (p["metric"], p["description"])
    assert sorted(da["predictions"], key=key) == sorted(db["predictions"], key=key)


def test_add_subsystem_equivalence():
    A = simulate_architecture_changes([ArchChange(action="add_subsystem", subsystem="Z")], _arch())
    B = simulate(ArchitectureChange(operations=[
        ArchitectureOperation(OpType.ADD_SUBSYSTEM, subsystem="Z")]), _arch())
    _sim_equal(A, B)


def test_add_edge_equivalence():
    A = simulate_architecture_changes([ArchChange(action="add_edge", subsystem="T", target_subsystem="S")], _arch())
    B = simulate(ArchitectureChange(operations=[
        ArchitectureOperation(OpType.ADD_EDGE, source="T", target="S", edge_type="dependency")]), _arch())
    _sim_equal(A, B)


def test_add_component_equivalence():
    A = simulate_architecture_changes([ArchChange(action="add_component", subsystem="S",
                                                   component_name="D", module_path="d.py")], _arch())
    B = simulate(ArchitectureChange(operations=[
        ArchitectureOperation(OpType.ADD_COMPONENT, component="d.py", component_subsystem="S",
                              component_name="D")]), _arch())
    _sim_equal(A, B)


def test_remove_subsystem_equivalence():
    A = simulate_architecture_changes([ArchChange(action="remove_subsystem", subsystem="T")], _arch())
    B = simulate(ArchitectureChange(operations=[
        ArchitectureOperation(OpType.REMOVE_SUBSYSTEM, subsystem="T")]), _arch())
    _sim_equal(A, B)


def test_remove_component_equivalence():
    A = simulate_architecture_changes([ArchChange(action="remove_component", subsystem="S",
                                                   component_name="A", module_path="a.py")], _arch())
    B = simulate(ArchitectureChange(operations=[
        ArchitectureOperation(OpType.REMOVE_COMPONENT, component="a.py", component_subsystem="S",
                              component_name="A")]), _arch())
    _sim_equal(A, B)


def test_remove_edge_equivalence():
    A = simulate_architecture_changes([ArchChange(action="remove_edge", subsystem="S", target_subsystem="T")], _arch())
    B = simulate(ArchitectureChange(operations=[
        ArchitectureOperation(OpType.REMOVE_EDGE, source="S", target="T", edge_type="dependency")]), _arch())
    _sim_equal(A, B)


def test_forbidden_dependency_boundary_mapping_equivalence():
    # IR keeps forbidden_dependency verbatim; boundary maps to simulator "forbidden".
    # Adding the forbidden edge T->S must be flagged in BOTH paths.
    A = simulate_architecture_changes([
        ArchChange(action="add_edge", subsystem="T", target_subsystem="S"),
        ArchChange(action="add_constraint", constraint_type="forbidden", subsystem="T", target_subsystem="S"),
    ], _arch())
    B = simulate(ArchitectureChange(operations=[
        ArchitectureOperation(OpType.ADD_EDGE, source="T", target="S", edge_type="dependency"),
        ArchitectureOperation(OpType.ADD_CONSTRAINT, constraint_type="forbidden_dependency",
                              source="T", target="S")]), _arch())
    _sim_equal(A, B)
    assert B.safe is False  # violation surfaced


def test_cross_subsystem_move_equivalence():
    # REMOVE(S,m) + ADD(N,m) is a legitimate move (Phase 4 resolved).
    A = simulate_architecture_changes([
        ArchChange(action="remove_component", subsystem="S", component_name="A", module_path="a.py"),
        ArchChange(action="add_component", subsystem="N", component_name="A", module_path="a.py"),
    ], _arch())
    B = simulate(ArchitectureChange(operations=[
        ArchitectureOperation(OpType.REMOVE_COMPONENT, component="a.py", component_subsystem="S", component_name="A"),
        ArchitectureOperation(OpType.ADD_COMPONENT, component="a.py", component_subsystem="N", component_name="A"),
    ]), _arch())
    _sim_equal(A, B)


def test_split_equivalence_via_archchange_producer():
    from codegraph.architecture_change_adapters import from_arch_change, architecture_change_to_arch_changes
    arch = SystemArchitecture(name="fx", subsystems=[
        SubsystemDef(name="S", components=[
            ArchComponent(name="A", module="a.py"),
            ArchComponent(name="B", module="b.py"),
        ], edges=[ArchEdge("A", "B")]),
    ], edges=[])
    ir = from_arch_change(ArchChange(action="split_subsystem", subsystem="S",
                                      target_subsystem="N", components=["A"]), arch)
    # The IR decomposition is faithful: moving A out of S reclassifies the A->B edge as
    # inter-subsystem (N->S). The legacy split_subsystem ACTION does NOT do this (a pre-existing
    # simulator limitation), so we prove the boundary is internally consistent — the IR round-trips
    # through the simulator identically to its own decomposed ArchChange list.
    B = simulate(ir, arch)
    A = simulate_architecture_changes(architecture_change_to_arch_changes(ir, arch), arch)
    _sim_equal(A, B)


def test_merge_simulates_without_error():
    from codegraph.architecture_change_adapters import from_arch_change, architecture_change_to_arch_changes
    arch = SystemArchitecture(name="fx", subsystems=[
        SubsystemDef(name="X", components=[ArchComponent(name="P", module="p.py"),
                                           ArchComponent(name="Q", module="q.py")]),
        SubsystemDef(name="Y", components=[ArchComponent(name="R", module="r.py")]),
    ], edges=[ArchEdge("X", "Y")],
       constraints=[ArchConstraint(constraint_type="forbidden_dependency", source="X", target="Y")])
    # Merge decomposition is absorb-style (documented PHASE 3G); the boundary must run it
    # through the simulator deterministically and consistently with its own reverse adapter.
    ir = from_arch_change(ArchChange(action="merge_subsystems", subsystem="X", target_subsystem="Y"), arch)
    B = simulate(ir, arch)
    A = simulate_architecture_changes(architecture_change_to_arch_changes(ir, arch), arch)
    _sim_equal(A, B)


def test_granularity_safety_unmappable_function_edge_raises():
    # A function-level edge whose module maps to NO subsystem must NOT be silently collapsed.
    with pytest.raises(ArchitectureChangeValidationError):
        simulate(ArchitectureChange(operations=[
            ArchitectureOperation(OpType.ADD_EDGE, source="z.py::foo", target="b.py::bar",
                                  edge_type="call")]), _arch())


def test_granularity_safe_projection_when_module_known():
    # A function-level edge whose module maps to a subsystem projects to that subsystem.
    out = simulate(ArchitectureChange(operations=[
        ArchitectureOperation(OpType.ADD_EDGE, source="a.py::foo", target="c.py::bar",
                              edge_type="call")]), _arch())
    # a.py -> S, c.py -> T: same as adding edge S->T (which already exists, so no new violation).
    assert out.safe is True
