"""codegraph.architecture_change_adapters — legacy models -> canonical ArchitectureChange IR.

PHASE 3 (issue #27). The canonical IR (architecture_change.py) is FROZEN; this module
owns ALL compatibility translation. Old models are NOT modified. Adapters are PURE
conversion functions; they call ArchitectureChange.validate() at the boundary.

Evidence (worktree audit, file:line):
- RepairAction is implementation/repair-layer (models/agent_response.py:60). Its `node` is a
  function id `module::function` (apply_handlers.py:81-93).
    * connect_call          -> ADD_EDGE(call), verbatim source/target
                               (mirror architecture_delta.py:354, which keeps node verbatim).
    * add_import            -> ADD_EDGE(dependency), source collapsed to module
                               (mirror architecture_delta.py:358-362; import == module dep,
                               apply_handlers.py:334-389). Audited COMPATIBILITY map, not a
                               claim "import" and "dependency" are universally identical.
    * remove_dead_code      -> NO OP. Deletes a function body (apply_handlers.py:555-624),
                               implementation-layer, never a whole component.
    * flag_for_human_review-> NO OP. Stored to reviews/pending.json (apply_handlers.py:632-662),
                               no code mutation.
- AgentResponse.intents / workflow_suggestions are NOT architecture mutations:
    * intents             -> metadata only (IntentProposal is agent intent annotation).
    * workflow_suggestions-> NO OP here: type is a RuleType that promotes to suggested_workflow
                               policy rules (apply.py:272-293), a DIFFERENT channel from
                               ArchChange.add_constraint. Not bridged into architecture constraints.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from .architecture_change import (
    ArchitectureChange,
    ArchitectureChangeValidationError,
    ArchitectureOperation,
    OpType,
    canonical_edge_type,
)
from .models.agent_response import AgentResponse, RepairAction
from .arch_planner import ArchPlan, PlannedTask, plan_architecture
from .architecture_simulator import ArchChange
from .simulator import SimulatedChange
from .target_architecture import compute_architecture_delta

# Adapter-owned legacy edge-token compatibility map (NOT in the canonical IR).
# Evidence: architecture_delta.py:362/400/419 emit "import"/"subsystem"; no
# architecture-layer consumer branches on them (delta constraint check, simulator
# subsystem/layer/transitive key off module/subsystem names). "import" == module-to-module
# dependency (apply_handlers.py:334-389). AUDITED COMPATIBILITY mapping only.
LEGACY_EDGE_TYPE_MAP = {
    "import": "dependency",
    "subsystem": "dependency",
}

__all__ = [
    "from_repair_action",
    "from_agent_response",
    "from_planned_task",
    "from_arch_plan",
    "from_arch_change",
    "from_simulated_change",
    "target_workflow_to_change",
    "system_architecture_to_change",
    "LEGACY_EDGE_TYPE_MAP",
]


def _legacy_edge_type(token: str) -> str:
    if token in ("call", "dependency", "data_flow"):
        return token
    return canonical_edge_type(LEGACY_EDGE_TYPE_MAP.get(token, token))


def from_repair_action(ra: RepairAction) -> ArchitectureChange:
    """Translate one RepairAction to ArchitectureChange.

    connect_call / add_import become edge ops; remove_dead_code and
    flag_for_human_review are implementation-layer and produce NO architecture op
    (recorded in metadata so the skip is explicit, never swallowed).
    """
    if ra.action == "connect_call":
        if ra.node and ra.target:
            ac = ArchitectureChange(
                operations=[
                    ArchitectureOperation(
                        OpType.ADD_EDGE,
                        source=ra.node,
                        target=ra.target,
                        edge_type="call",
                        reason=ra.reason,
                    )
                ]
            )
            ac.validate()
            return ac
        return ArchitectureChange(metadata={"skipped": [f"{ra.action}:missing node/target"]})

    if ra.action == "add_import":
        if ra.node and ra.target:
            module = ra.node.split("::")[0] if "::" in ra.node else ra.node
            ac = ArchitectureChange(
                operations=[
                    ArchitectureOperation(
                        OpType.ADD_EDGE,
                        source=module,
                        target=ra.target,
                        edge_type=_legacy_edge_type("import"),
                        reason=ra.reason,
                    )
                ]
            )
            ac.validate()
            return ac
        return ArchitectureChange(metadata={"skipped": [f"{ra.action}:missing node/target"]})

    # remove_dead_code / flag_for_human_review -> implementation-layer, no architecture op.
    return ArchitectureChange(
        metadata={"skipped_implementation_layer": [ra.action], "reason": ra.reason}
    )


def from_agent_response(resp: AgentResponse) -> ArchitectureChange:
    """Translate an AgentResponse to ArchitectureChange.

    Only `repairs` of architecture-mutation kind become operations. `intents` and
    `workflow_suggestions` are recorded in metadata (non-mutations / different channel).
    """
    operations: List[ArchitectureOperation] = []
    skipped: List[Dict[str, Any]] = []

    for repair in resp.repairs:
        ac = from_repair_action(repair)
        operations.extend(ac.operations)
        if not ac.operations and ac.metadata:
            skipped.append(ac.metadata)

    if resp.intents:
        skipped.append(
            {"intents": len(resp.intents), "note": "agent intent metadata, non-mutation"}
        )
    if resp.workflow_suggestions:
        skipped.append(
            {
                "workflow_suggestions": len(resp.workflow_suggestions),
                "note": "suggested_workflow policy rules, not architecture constraints",
            }
        )

    ac = ArchitectureChange(operations=operations, metadata={"skipped": skipped} if skipped else {})
    ac.validate()
    return ac


def from_planned_task(task: PlannedTask) -> ArchitectureChange:
    """Translate one PlannedTask to ArchitectureChange.

    create_module   -> ADD_COMPONENT (module path is the component identity).
    connect_call    -> ADD_EDGE(call).
    create_function -> NO OP: a `module::function` node, not an architecture component
                      (architecture-layer boundary; matches the planner's own downgrade to
                      flag_for_human_review in plan_to_agent_response).
    flag_violation  -> NO OP: diagnostic, not a mutation.
    add_constraint   -> NO OP here: PlannedTask has no constraint_type field, so an honest
                      ADD_CONSTRAINT cannot be built (validate would reject it). Recorded.
    """
    t = task.task_type
    if t == "create_module":
        if task.module and task.subsystem:
            ac = ArchitectureChange(
                operations=[
                    ArchitectureOperation(
                        OpType.ADD_COMPONENT,
                        component=task.module,
                        component_subsystem=task.subsystem,
                        reason=task.reason,
                    )
                ]
            )
            ac.validate()
            return ac
        return ArchitectureChange(metadata={"skipped": ["create_module:missing module/subsystem"]})

    if t == "create_function":
        return ArchitectureChange(
            metadata={"skipped_implementation_layer": ["create_function"], "reason": task.reason}
        )

    if t == "connect_call":
        if task.source and task.target:
            ac = ArchitectureChange(
                operations=[
                    ArchitectureOperation(
                        OpType.ADD_EDGE,
                        source=task.source,
                        target=task.target,
                        edge_type="call",
                        reason=task.reason,
                    )
                ]
            )
            ac.validate()
            return ac
        return ArchitectureChange(metadata={"skipped": ["connect_call:missing source/target"]})

    if t == "add_constraint":
        # PlannedTask carries no constraint_type; an honest ADD_CONSTRAINT is impossible.
        return ArchitectureChange(
            metadata={
                "skipped": [
                    "add_constraint: PlannedTask lacks constraint_type; "
                    "cannot represent as architecture constraint"
                ]
            }
        )

    if t == "flag_violation":
        return ArchitectureChange(
            metadata={"skipped_diagnostic": ["flag_violation"], "reason": task.reason}
        )

    return ArchitectureChange(metadata={"skipped": [f"unknown task_type: {t}"]})


def from_arch_plan(plan: ArchPlan) -> ArchitectureChange:
    """Translate an ArchPlan to ArchitectureChange.

    Only actionable `plan.tasks` become operations. Coverage numbers and
    missing_modules/missing_functions are NOT turned into operations (they are already
    realized as create_module/create_function tasks, which are mapped above).
    """
    operations: List[ArchitectureOperation] = []
    skipped: List[Dict[str, Any]] = []
    for task in plan.tasks:
        ac = from_planned_task(task)
        operations.extend(ac.operations)
        if not ac.operations and ac.metadata:
            skipped.append(ac.metadata)
    result = ArchitectureChange(
        operations=operations, metadata={"skipped": skipped} if skipped else {}
    )
    result.validate()
    return result


def from_arch_change(change: ArchChange, arch: Optional["SystemArchitecture"] = None) -> ArchitectureChange:
    """Translate one ArchChange (architecture_simulator proposal) to ArchitectureChange.

    Evidence (architecture_simulator.py:_apply_changes):
    - add_edge / remove_edge act on subsystem -> target_subsystem and build ArchEdge with
      default edge_type="dependency" (arch_schema.py:71). Mapped to ADD/REMOVE_EDGE(dependency).
    - add_component: component=module_path, component_subsystem=subsystem, name=component_name.
    - add_constraint: constraint_type kept VERBATIM (forbidden_dependency survives).
    - split_subsystem / merge_subsystems: NOT handled here; decomposed in PHASE 3G via
      subsystem_lifecycle (the semantic authority). Raises until then.
    """
    a = change.action
    if a == "add_subsystem":
        ac = ArchitectureChange(
            operations=[ArchitectureOperation(OpType.ADD_SUBSYSTEM, subsystem=change.subsystem, reason=change.reason)]
        )
        ac.validate()
        return ac
    if a == "add_edge":
        ac = ArchitectureChange(
            operations=[ArchitectureOperation(
                OpType.ADD_EDGE, source=change.subsystem, target=change.target_subsystem,
                edge_type="dependency", reason=change.reason,
            )]
        )
        ac.validate()
        return ac
    if a == "remove_edge":
        ac = ArchitectureChange(
            operations=[ArchitectureOperation(
                OpType.REMOVE_EDGE, source=change.subsystem, target=change.target_subsystem,
                edge_type="dependency", reason=change.reason,
            )]
        )
        ac.validate()
        return ac
    if a == "add_component":
        ac = ArchitectureChange(
            operations=[ArchitectureOperation(
                OpType.ADD_COMPONENT,
                component=change.module_path,
                component_subsystem=change.subsystem,
                component_name=change.component_name,
                reason=change.reason,
            )]
        )
        ac.validate()
        return ac
    if a == "add_constraint":
        ac = ArchitectureChange(
            operations=[ArchitectureOperation(
                OpType.ADD_CONSTRAINT,
                constraint_type=change.constraint_type,
                source=change.subsystem,
                target=change.target_subsystem,
                reason=change.reason,
            )]
        )
        ac.validate()
        return ac
    if a == "split_subsystem":
        if arch is None:
            raise ValueError("split_subsystem decomposition requires the source SystemArchitecture")
        return _decompose_split(change, arch)
    if a == "merge_subsystems":
        if arch is None:
            raise ValueError("merge_subsystems decomposition requires the source SystemArchitecture")
        return _decompose_merge(change, arch)
    raise NotImplementedError(f"unknown ArchChange.action: {a}")


def from_simulated_change(change: SimulatedChange) -> ArchitectureChange:
    """Translate one SimulatedChange (call-graph simulation op) to ArchitectureChange.

    Evidence (simulator.py):
    - add_edge / remove_edge have NO edge_type field; simulator applies them type-agnostic.
      Mapped to canonical default edge_type="call" (normalize() agrees). The dependency/call
      distinction is genuinely lost in the SimulatedChange model — recorded, not invented.
    - add_node / remove_node act on `node_id`, a graph NODE. A `module::function` node is a
      function node (implementation-layer), NOT an architecture component -> NO OP. A bare
      module path may be an architecture component (ADD/REMOVE_COMPONENT).
    """
    a = change.action
    if a == "add_edge":
        ac = ArchitectureChange(
            operations=[ArchitectureOperation(
                OpType.ADD_EDGE, source=change.source, target=change.target,
                edge_type="call", reason=change.reason,
            )]
        )
        ac.validate()
        return ac
    if a == "remove_edge":
        ac = ArchitectureChange(
            operations=[ArchitectureOperation(
                OpType.REMOVE_EDGE, source=change.source, target=change.target,
                edge_type="call", reason=change.reason,
            )]
        )
        ac.validate()
        return ac
    if a in ("add_node", "remove_node"):
        node_id = change.node_id
        if "::" in node_id:
            return ArchitectureChange(metadata={
                "skipped_implementation_layer": [f"{a}:{node_id}"],
                "reason": "function node is not an architecture component",
            })
        # Bare module path: remove_node -> REMOVE_COMPONENT (only `component` required).
        # add_node would need an owning subsystem (component_subsystem), which SimulatedChange
        # does NOT carry, so ADD_COMPONENT cannot be emitted honestly -> skipped, not invented.
        if a == "remove_node":
            ac = ArchitectureChange(
                operations=[ArchitectureOperation(OpType.REMOVE_COMPONENT, component=node_id, reason=change.reason)]
            )
            ac.validate()
            return ac
        return ArchitectureChange(metadata={
            "skipped": [f"add_node:{node_id}"],
            "reason": "SimulatedChange node has no owning subsystem; cannot emit ADD_COMPONENT (component_subsystem required)",
        })
    raise NotImplementedError(f"unknown SimulatedChange.action: {a}")


# ── split/merge decomposition (PHASE 3G) ──────────────────────────────────
# subsystem_lifecycle.py is the semantic authority. A split/merge cannot be
# represented as primitives without the source architecture (to know which
# components/edges/constraints are affected), so these take `arch`. No MOVE_* /
# RENAME_* operations are invented — only ADD/REMOVE of SUBSYSTEM/COMPONENT/EDGE/
# CONSTRAINT.


def _decompose_split(change: ArchChange, arch: "SystemArchitecture") -> ArchitectureChange:
    source_name = change.subsystem
    new_name = change.target_subsystem
    moving = set(change.components)
    src = arch.get_subsystem(source_name)
    if src is None:
        raise ValueError(f"split source subsystem not found: {source_name}")

    ops: List[ArchitectureOperation] = [
        ArchitectureOperation(OpType.ADD_SUBSYSTEM, subsystem=new_name, reason=change.reason)
    ]
    move_comp_names = {c.name for c in src.components if c.name in moving}
    for comp in src.components:
        if comp.name in moving:
            ops.append(ArchitectureOperation(
                OpType.REMOVE_COMPONENT, component=comp.module,
                component_subsystem=source_name, component_name=comp.name,
            ))
            ops.append(ArchitectureOperation(
                OpType.ADD_COMPONENT, component=comp.module,
                component_subsystem=new_name, component_name=comp.name,
            ))
    # Cross edges (exactly one endpoint moving) become inter-subsystem edges N<->S.
    # Dedupe: two moving components both touching the same stationary component yield
    # the identical inter-subsystem edge, which would be a duplicate ADD_EDGE.
    seen_cross_edges = set()
    for edge in src.edges:
        src_moving = edge.source in move_comp_names
        tgt_moving = edge.target in move_comp_names
        if src_moving != tgt_moving:
            source, target = (new_name, source_name) if src_moving else (source_name, new_name)
            key = (source, target, edge.edge_type or "dependency")
            if key in seen_cross_edges:
                continue
            seen_cross_edges.add(key)
            ops.append(ArchitectureOperation(
                OpType.ADD_EDGE, source=source, target=target,
                edge_type=edge.edge_type or "dependency",
            ))
    # validate() runs normally: the canonical IR's component add/remove contradiction
    # detector is subsystem-aware (REMOVE_COMPONENT(S,m) + ADD_COMPONENT(N,m) is a
    # legitimate move, not a contradiction), so split decomposition validates cleanly.
    ac = ArchitectureChange(operations=ops)
    ac.validate()
    return ac


def _decompose_merge(change: ArchChange, arch: "SystemArchitecture") -> ArchitectureChange:
    # subsystem_lifecycle merges into name_a (merged_name defaults to name_a), i.e.
    # "X absorbs Y". The frozen validate() rejects REMOVE_SUBSYSTEM(X)+ADD_SUBSYSTEM(X),
    # so we represent the merge faithfully as: remove Y, migrate Y's components/edges/
    # constraints into X. X is never destroyed/re-created.
    name_a = change.subsystem
    name_b = change.target_subsystem
    final_name = name_a
    ss_a = arch.get_subsystem(name_a)
    ss_b = arch.get_subsystem(name_b)
    if ss_a is None or ss_b is None:
        raise ValueError(f"merge subsystems not found: {name_a}, {name_b}")

    ops: List[ArchitectureOperation] = [
        ArchitectureOperation(OpType.REMOVE_SUBSYSTEM, subsystem=name_b),
    ]
    # Migrate name_b's components into name_a (name_a's own components stay).
    for comp in ss_b.components:
        ops.append(ArchitectureOperation(
            OpType.ADD_COMPONENT, component=comp.module,
            component_subsystem=final_name, component_name=comp.name,
        ))
    for edge in arch.edges:
        if edge.source in (name_a, name_b) or edge.target in (name_a, name_b):
            src = final_name if edge.source in (name_a, name_b) else edge.source
            tgt = final_name if edge.target in (name_a, name_b) else edge.target
            if src == edge.source and tgt == edge.target:
                continue  # unchanged -> no-op (avoid contradictory remove+add)
            ops.append(ArchitectureOperation(
                OpType.REMOVE_EDGE, source=edge.source, target=edge.target,
                edge_type=edge.edge_type or "dependency",
            ))
            if src != tgt:
                ops.append(ArchitectureOperation(
                    OpType.ADD_EDGE, source=src, target=tgt,
                    edge_type=edge.edge_type or "dependency",
                ))
    for c in arch.constraints:
        if c.source in (name_a, name_b) or c.target in (name_a, name_b):
            src = final_name if c.source in (name_a, name_b) else c.source
            tgt = final_name if c.target in (name_a, name_b) else c.target
            if src == c.source and tgt == c.target:
                continue
            ops.append(ArchitectureOperation(
                OpType.REMOVE_CONSTRAINT, constraint_type=c.constraint_type,
                source=c.source, target=c.target,
            ))
            if src != tgt:
                ops.append(ArchitectureOperation(
                    OpType.ADD_CONSTRAINT, constraint_type=c.constraint_type,
                    source=src, target=tgt, reason=c.reason,
                ))
    ac = ArchitectureChange(operations=ops)
    ac.validate()
    return ac


# ── baseline-aware state -> change (PHASE 3I) ──────────────────────────────
# SystemArchitecture / TargetWorkflow describe a DESIRED STATE, not a change.
# Without a baseline they cannot be turned into an ArchitectureChange honestly,
# so these adapters REQUIRE the current state and reuse the existing diff
# machinery (plan_architecture / compute_architecture_delta). No parameterless
# `from_system_architecture` / `from_target_workflow` is provided.


def target_workflow_to_change(
    target_workflow: "TargetWorkflow",
    current_workflow: Dict[str, Any],
    current_nodes: Set[str],
) -> ArchitectureChange:
    """Baseline-aware: change = target - current (reuses compute_architecture_delta).

    Missing edges -> ADD_EDGE(call). Missing nodes -> ADD_COMPONENT when the node is a
    module path; a `module::function` node is a function node (implementation-layer) -> NO OP.
    """
    delta = compute_architecture_delta(target_workflow, current_workflow, current_nodes)
    ops: List[ArchitectureOperation] = []
    skipped: List[Dict[str, Any]] = []
    node_subsys = {tn.node_id: tn.subsystem for tn in target_workflow.nodes}
    for e in delta.added_edges:
        ops.append(ArchitectureOperation(
            OpType.ADD_EDGE, source=e.source, target=e.target,
            edge_type="call", reason=e.reason,
        ))
    for n in delta.added_nodes:
        node_id = n.node_id
        if "::" in node_id:
            skipped.append({"target_node_function": node_id, "note": "function node, not an architecture component"})
            continue
        module = n.module or node_id
        ops.append(ArchitectureOperation(
            OpType.ADD_COMPONENT, component=module,
            component_subsystem=node_subsys.get(node_id, ""), reason=n.reason,
        ))
    metadata: Dict[str, Any] = {}
    if skipped:
        metadata["skipped"] = skipped
    # TargetEdge.priority has no field in the frozen ArchitectureChange IR, so it
    # travels through the funnel via existing metadata (not an IR change).
    # Keyed by full edge identity (incl. edge_type) so distinct edge types never
    # collide, and MIN priority is taken so duplicate same-endpoint edges keep the
    # HIGHER-urgency intent (repo convention: 1=highest, 10=lowest; added_edges
    # are sorted ascending by priority) instead of silently overwriting it.
    if delta.added_edges:
        edge_priorities: Dict[str, int] = {}
        for e in delta.added_edges:
            k = f"{e.source}->{e.target}->{e.edge_type}"
            edge_priorities[k] = min(edge_priorities.get(k, 99), e.priority)
        metadata["target_edge_priorities"] = edge_priorities
    ac = ArchitectureChange(operations=ops, metadata=metadata)
    ac.validate()
    return ac


def system_architecture_to_change(
    architecture: "SystemArchitecture",
    graph0: "Graph0",
    index: "IndexStore",
) -> ArchitectureChange:
    """Baseline-aware: change = architecture vs current graph0/index (reuses plan_architecture)."""
    plan = plan_architecture(architecture, graph0, index)
    return from_arch_plan(plan)


# ── reverse adapter: canonical IR -> legacy ArchChange simulator model ──────
# PHASE 5 (issue #27). Symmetric to the forward adapters: ArchitectureChange ->
# List[ArchChange] so the existing simulate_architecture_changes can run. PURE
# conversion, no architecture mutation. Granularity: the simulator operates at
# SUBSYSTEM level, so edge/module endpoints are PROJECTED to a owning subsystem
# via the live architecture index. A projection that cannot be resolved is an
# ERROR (never a silent collapse) — see PHASE 5 plan (granularity decision).
#
# Constraint vocabulary: the canonical IR keeps constraint_type verbatim
# (Phase 1). The simulator only recognizes "forbidden", so at THIS boundary we
# map the legacy-incompatible vocabulary; the IR itself is unchanged.
#   forbidden_dependency -> forbidden ; forbidden -> forbidden ; required -> required

SIM_CONSTRAINT_MAP = {
    "forbidden_dependency": "forbidden",
    "forbidden": "forbidden",
    "required": "required",
}


def _sim_constraint_type(constraint_type: str) -> str:
    return SIM_CONSTRAINT_MAP.get(constraint_type, constraint_type)


def _build_subsystem_index(architecture: "SystemArchitecture"):
    """Map endpoint ids (subsystem / component / module / module::func) -> subsystem name."""
    subsystem_names: Set[str] = set()
    comp_name_to_sub: Dict[str, str] = {}
    module_to_sub: Dict[str, str] = {}
    for sub in architecture.subsystems:
        subsystem_names.add(sub.name)
        for comp in sub.components:
            if comp.name:
                comp_name_to_sub[comp.name] = sub.name
            if comp.module:
                module_to_sub[comp.module] = sub.name
    return subsystem_names, comp_name_to_sub, module_to_sub


def _project_endpoint(
    endpoint: str,
    subsystem_names: Set[str],
    comp_name_to_sub: Dict[str, str],
    module_to_sub: Dict[str, str],
) -> str:
    """Resolve an edge endpoint to a subsystem name, or fail loudly (no silent collapse)."""
    if endpoint in subsystem_names:
        return endpoint
    if endpoint in comp_name_to_sub:
        return comp_name_to_sub[endpoint]
    mod = endpoint.split("::")[0] if "::" in endpoint else endpoint
    if mod in module_to_sub:
        return module_to_sub[mod]
    if endpoint in module_to_sub:
        return module_to_sub[endpoint]
    raise ArchitectureChangeValidationError(
        f"edge endpoint {endpoint!r} cannot be projected to a subsystem; "
        f"the subsystem simulator cannot represent component/function-level edges"
    )


def architecture_change_to_arch_changes(
    change: ArchitectureChange,
    architecture: "SystemArchitecture",
) -> List[ArchChange]:
    """Convert a canonical ArchitectureChange to the legacy simulator ArchChange list.

    Runs ONCE at the boundary. Each OpType maps to the corresponding ArchChange action;
    removals map to the (now supported) simulation-only remove_* branches. Edge endpoints
    are projected to owning subsystems; unmappable endpoints raise. Constraint types are
    mapped to the simulator's vocabulary. No architecture state is mutated.
    """
    subsystem_names, comp_name_to_sub, module_to_sub = _build_subsystem_index(architecture)
    # A subsystem created within THIS change is a valid projection target even though
    # it is not yet present in the (pre-simulation) architecture index.
    added_subsystems = {op.subsystem for op in change.operations if op.op == OpType.ADD_SUBSYSTEM}
    subsystem_names = subsystem_names | added_subsystems
    out: List[ArchChange] = []

    for op in change.operations:
        if op.op == OpType.ADD_SUBSYSTEM:
            out.append(ArchChange(action="add_subsystem", subsystem=op.subsystem, reason=op.reason))
        elif op.op == OpType.REMOVE_SUBSYSTEM:
            out.append(ArchChange(action="remove_subsystem", subsystem=op.subsystem))
        elif op.op == OpType.ADD_COMPONENT:
            out.append(ArchChange(
                action="add_component", subsystem=op.component_subsystem,
                component_name=op.component_name or _derive_comp_name(op.component),
                module_path=op.component, reason=op.reason,
            ))
        elif op.op == OpType.REMOVE_COMPONENT:
            out.append(ArchChange(
                action="remove_component", subsystem=op.component_subsystem,
                component_name=op.component_name or _derive_comp_name(op.component),
                module_path=op.component,
            ))
        elif op.op in (OpType.ADD_EDGE, OpType.REMOVE_EDGE):
            src = _project_endpoint(op.source, subsystem_names, comp_name_to_sub, module_to_sub)
            tgt = _project_endpoint(op.target, subsystem_names, comp_name_to_sub, module_to_sub)
            action = "add_edge" if op.op == OpType.ADD_EDGE else "remove_edge"
            # ArchChange edge ops carry no edge_type; the subsystem simulator models
            # edges without type (typed edges are a finer IR detail it cannot express).
            out.append(ArchChange(action=action, subsystem=src, target_subsystem=tgt, reason=op.reason))
        elif op.op == OpType.ADD_CONSTRAINT:
            out.append(ArchChange(
                action="add_constraint",
                constraint_type=_sim_constraint_type(op.constraint_type),
                subsystem=op.source, target_subsystem=op.target, reason=op.reason,
            ))
        elif op.op == OpType.REMOVE_CONSTRAINT:
            out.append(ArchChange(
                action="remove_constraint",
                constraint_type=_sim_constraint_type(op.constraint_type),
                subsystem=op.source, target_subsystem=op.target,
            ))
    return out


def _derive_comp_name(module_path: str) -> str:
    """Derive a component name from a module path when the IR op omitted one."""
    base = module_path.rsplit("/", 1)[-1]
    return base[:-3] if base.endswith(".py") else base
