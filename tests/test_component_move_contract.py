"""PHASE 4 — component-move contract (issue #27, Option A resolved).

Component identity is the module path, but validate()'s component add/remove
contradiction detector is subsystem-aware: REMOVE_COMPONENT(A, m) + ADD_COMPONENT(B, m)
is a legitimate move, not a contradiction. Ordinary same-subsystem remove+add remains
a contradiction; duplicates are still rejected. Split decomposition validates normally.
"""

import pytest
from codegraph.architecture_change import (
    ArchitectureChange,
    ArchitectureOperation,
    OpType,
    ArchitectureChangeValidationError,
)


def _remove(module, subsystem):
    return ArchitectureOperation(OpType.REMOVE_COMPONENT, component=module, component_subsystem=subsystem)


def _add(module, subsystem):
    return ArchitectureOperation(OpType.ADD_COMPONENT, component=module, component_subsystem=subsystem)


def test_ordinary_remove_component_is_valid():
    ArchitectureChange(operations=[_remove("m.py", "A")]).validate()


def test_ordinary_add_component_is_valid():
    ArchitectureChange(operations=[_add("m.py", "A")]).validate()


def test_remove_then_add_same_component_same_subsystem_is_contradiction():
    # Genuinely meaningless (no-op): identical component removed and added.
    ac = ArchitectureChange(operations=[_remove("m.py", "A"), _add("m.py", "A")])
    with pytest.raises(ArchitectureChangeValidationError):
        ac.validate()


def test_remove_then_add_same_module_different_subsystem_is_move():
    # LEGITIMATE MOVE: removing from A and adding to B (different owning subsystem)
    # is meaningful, not a contradiction (component identity is still the module path;
    # only the contradiction detector is subsystem-aware).
    ac = ArchitectureChange(operations=[_remove("m.py", "A"), _add("m.py", "B")])
    ac.validate()  # must NOT raise


def test_duplicate_add_component_same_subsystem_still_rejected():
    # Adding the same module to the same subsystem twice is still a duplicate/no-op.
    ac = ArchitectureChange(operations=[
        _add("m.py", "A"), _add("m.py", "A"),
    ])
    with pytest.raises(ArchitectureChangeValidationError):
        ac.validate()


def test_move_then_duplicate_add_in_target_subsystem_rejected():
    # REMOVE(A,m)+ADD(B,m) is a move; a second ADD(B,m) is a genuine duplicate.
    ac = ArchitectureChange(operations=[
        _remove("m.py", "A"), _add("m.py", "B"), _add("m.py", "B"),
    ])
    with pytest.raises(ArchitectureChangeValidationError):
        ac.validate()


def test_split_subsystem_produces_expected_canonical_ops():
    from codegraph.arch_schema import SystemArchitecture, SubsystemDef, ArchComponent, ArchEdge
    from codegraph.architecture_simulator import ArchChange
    from codegraph.architecture_change_adapters import from_arch_change

    arch = SystemArchitecture(name="fixture", subsystems=[
        SubsystemDef(name="S", components=[
            ArchComponent(name="A", module="a.py"),
            ArchComponent(name="B", module="b.py"),
        ], edges=[ArchEdge("A", "B")]),
    ], edges=[], constraints=[])
    ac = from_arch_change(
        ArchChange(action="split_subsystem", subsystem="S", target_subsystem="N", components=["A"]),
        arch,
    )
    assert any(o.op == OpType.ADD_SUBSYSTEM and o.subsystem == "N" for o in ac.operations)
    assert any(o.op == OpType.REMOVE_COMPONENT and o.component == "a.py" and o.component_subsystem == "S" for o in ac.operations)
    assert any(o.op == OpType.ADD_COMPONENT and o.component == "a.py" and o.component_subsystem == "N" for o in ac.operations)
    assert any(o.op == OpType.ADD_EDGE and o.source == "N" and o.target == "S" and o.edge_type == "dependency" for o in ac.operations)
