# ArchitectureChange — Canonical Proposed-Change IR

CodeGraph must let you **simulate a proposed architectural change before any
source code is modified**. `ArchitectureChange` (in `codegraph/architecture_change.py`)
is the frozen, canonical intermediate representation (IR) for *proposed* changes.
It is the common currency between the many legacy "proposed change" models and the
existing simulation / delta machinery.

Issue #27 tracks its introduction (Phases 0–6).

## Design principles

- **Description-only.** An `ArchitectureChange` *describes* operations; it never
  executes them. Validation → conversion → simulation, in that order.
- **Single frozen contract.** Component identity, edge vocabulary, and validation
  rules are locked (Phase 1). Old models are not modified; all translation lives in
  `codegraph/architecture_change_adapters.py`.
- **Reuse, don't reimplement.** The IR is wired into the *existing* simulator
  (`architecture_simulator.simulate_architecture_changes`); there is no second
  architecture engine.

## Identity

| Concept   | Identity                                  | Notes |
|-----------|-------------------------------------------|-------|
| subsystem | `name`                                    |       |
| component | **module path**                           | owning subsystem is `component_subsystem` (an attribute, not part of identity) |
| edge      | `(source, target, edge_type)`             |       |
| constraint| `(constraint_type, source, target)`       | `constraint_type` kept **verbatim** |

Edge-type vocabulary: `call`, `dependency`, `data_flow` (plus `EDGE_TYPE_ALIASES`).

## Operations (all description-only)

`ADD_SUBSYSTEM`, `REMOVE_SUBSYSTEM`, `ADD_COMPONENT`, `REMOVE_COMPONENT`,
`ADD_EDGE`, `REMOVE_EDGE`, `ADD_CONSTRAINT`, `REMOVE_CONSTRAINT`.

A cross-subsystem **move** is `REMOVE_COMPONENT(A, m)` + `ADD_COMPONENT(B, m)`.
There is deliberately **no `MOVE_COMPONENT`** op; a move is a pair of primitives.
`validate()` is subsystem-aware for component add/remove, so a move
(different `component_subsystem`) is allowed, while `REMOVE(A,m)+ADD(A,m)` (same
subsystem) is correctly rejected as a no-op.

`normalize()` canonicalizes ordering/defaults; `validate()` rejects contradictions
and duplicates. They are different passes.

## Adapters (single translation module)

`codegraph/architecture_change_adapters.py` owns all compatibility translation:

- **Forward** (legacy → IR): `from_repair_action`, `from_agent_response`,
  `from_planned_task`, `from_arch_plan`, `from_arch_change`, `from_simulated_change`,
  `target_workflow_to_change`, `system_architecture_to_change`. Each calls
  `validate()` at the boundary. Implementation-layer intents that are not
  architecture mutations (`remove_dead_code`, `workflow_suggestions`, …) are
  deliberate **NO-OPs**, never silently invented.
- **Reverse** (IR → legacy simulator): `architecture_change_to_arch_changes(ac, arch)`
  maps each `OpType` to the corresponding `ArchChange` action so the existing
  simulator can run.

## Simulation boundary (Phase 5)

```python
from codegraph.architecture_simulator import simulate

result = simulate(architecture_change, system_architecture)
```

`simulate()` is the single public boundary:

1. `architecture_change.validate()` (rejects contradictions/duplicates).
2. `architecture_change_to_arch_changes(...)` — one conversion to
   `List[ArchChange]` (simulation-only `remove_subsystem` / `remove_component` /
   `remove_constraint` branches were added to the existing `_apply_changes`).
3. `simulate_architecture_changes(...)` — the **existing** engine, which deep-copies
   the architecture, so persistent state is never mutated here.

Legacy callers keep calling `simulate_architecture_changes(List[ArchChange], ...)`
directly; nothing about that path changed.

## Granularity & constraint vocabulary

- The subsystem simulator operates at **subsystem level**. The reverse adapter
  projects edge/module endpoints to their owning subsystem via the live
  `SystemArchitecture` index. An endpoint that cannot be projected (e.g. a
  `module::function` whose module belongs to no subsystem) **raises
  `ArchitectureChangeValidationError`** — it is never silently collapsed to a wrong
  meaning.
- `constraint_type` is preserved verbatim in the IR. The simulator only recognizes
  `forbidden`, so **at the boundary only** `forbidden_dependency → forbidden`
  (and `forbidden → forbidden`, `required → required`). The IR itself is unchanged.

## Known limitations

- The subsystem simulator's `ArchChange` edges carry no `edge_type`; typed edges
  (`call` vs `dependency`) are an IR-level detail the subsystem simulator cannot
  express. The IR retains the finer type; the delta path preserves node/edge
  granularity.
- The legacy `split_subsystem` / `merge_subsystems` actions **under-model crossed
  edges** (they do not reclassify an intra-subsystem edge into an inter-subsystem
  edge when a component moves). The IR decomposition is *more* faithful and emits
  the crossing edge. This is a pre-existing simulator limitation, intentionally left
  as-is; the divergence is documented, not "fixed" by reimplementing the simulator.
- Function/module-level edges must be projected to subsystems before simulation;
  unmappable endpoints fail loudly rather than degrade silently.

## Further reading

- `codegraph/architecture_change.py` — the frozen IR and `validate()`/`normalize()`.
- `codegraph/architecture_change_adapters.py` — all forward/reverse translation.
- `tests/test_architecture_change.py`, `tests/test_architecture_change_adapters.py`,
  `tests/test_phase4_proof.py`, `tests/test_phase5_integration.py` — contract and
  equivalence proofs (legacy A == IR-mediated B).
