# ADR 002 — Layer System Design

## Status
**Accepted** — 2025-01-01

## Context
codegraph needs to classify code into categories that control which nodes
agents are allowed to modify. The system must distinguish between standard
library code, third-party packages, internal shared libraries, project code,
and test code.

## Decision Drivers
- Agents should never modify stdlib or third-party code.
- Internal shared libraries may be read but not modified by feature agents.
- Test code has different modification rules than production code.
- Layer detection must be automatic with override capability.

## Decision
Use a 5-tier integer layer system (0–4):

| Layer | Name         | Modifiable | Detection                           |
|-------|-------------|------------|-------------------------------------|
| 0     | STDLIB      | No         | Module in `sys.stdlib_module_names`  |
| 1     | EXTERNAL    | No         | File in `site-packages`             |
| 2     | INTERNAL_LIB| No         | File under `internal_libs` config   |
| 3     | PROJECT     | Yes        | Default for project files           |
| 4     | TEST        | Yes        | Matches test patterns or `test_dirs`|

Detection order: EXTERNAL → INTERNAL_LIB → TEST → PROJECT (default).

Layer overrides are supported via CLI (`--layer-override path:layer`)
and config file (`internal_libs`, `test_dirs`).

## Consequences
- Every node in Graph\_0 carries a `layer` integer field.
- Architecture tests can enforce "no calls from layer 3 to layer 4".
- The layer system is extensible — additional layers can be added by
  incrementing the enum without breaking existing data.
- Layer 2 (INTERNAL\_LIB) requires explicit configuration; it is never
  auto-detected.
