# Core Concepts

codegraph models your codebase as a layered graph system. This document
explains the key abstractions.

## Graph Layers

### Graph\_0 — Structural Graph

The foundation layer, extracted directly from Python AST:

- **Nodes**: functions, methods, classes, and modules
- **Properties**: `id`, `file`, `line`, `type`, `body_hash`, `layer`
- **Automatic**: fully derived from source code, no manual input

Each node has a deterministic **node ID** in the format `file.py::ClassName.method`
or `file.py::function_name`.

### Graph\_1 — Intent Graph

Annotations that describe *why* code exists:

- **Intent**: human-readable purpose (e.g., "Validates JWT tokens")
- **Status**: `approved`, `needs-review`, `deprecated`
- **Ownership**: which team or agent is responsible

Intents are added via `codegraph intent-apply` or inline `# cg:intent` comments.

### Workflow — Call Graph

Directed edges representing function calls:

- **Source → Target**: caller → callee
- **Edge type**: `call`, `test`, `trace`
- **Confidence**: `static` (from AST), `runtime` (from trace), `ai_inferred`

### Suggested Workflow — Policy Layer

Rules that define how code *should* be connected:

- **must-call**: A must call B (e.g., every handler must call `log_request`)
- **must-not-call**: A must not call B (e.g., no direct DB calls from handlers)
- **layer-lock**: enforce layer boundaries

## Node Identity

Every code entity gets a stable, deterministic identifier:

```
path/to/file.py::ClassName.method_name
path/to/file.py::function_name
path/to/file.py  (module node)
```

**Body hash**: a content hash of the function body (excluding docstrings and
comments) that detects meaningful code changes while ignoring formatting.

## Layer System

Code is classified into layers based on location:

| Layer | Name         | Modifiable | Example                    |
|-------|-------------|------------|----------------------------|
| 0     | STDLIB      | No         | `os`, `sys`, `json`        |
| 1     | EXTERNAL    | No         | `click`, `pytest`, `numpy` |
| 2     | INTERNAL_LIB| No         | Internal shared libraries  |
| 3     | PROJECT     | Yes        | Your application code      |
| 4     | TEST        | Yes        | Test files                 |

Layers enforce boundaries: project code (3) should not be modified to depend
on test code (4), and nobody should modify external libraries (1).

## Confidence Levels

Workflow edges have confidence that indicates how the relationship was discovered:

| Level          | Source                   | Reliability |
|----------------|-------------------------|-------------|
| `static`       | AST analysis            | High        |
| `runtime`      | Coverage trace          | High        |
| `ai_inferred`  | AI agent suggestion     | Medium      |

Higher-confidence edges take priority during deduplication.

## Task System

The task generator produces prioritized work items:

- **Priority**: P0 (critical) through P4 (nice-to-have)
- **Categories**: missing-intent, dead-code, layer-violation, policy-breach
- **Fix suggestions**: each task includes a `SuggestedFix` with action type

## Delta Engine

Tracks changes between builds:

- **Added**: new nodes since last build
- **Removed**: nodes that no longer exist
- **Modified**: nodes whose `body_hash` changed

Used by `codegraph delta` and the repair loop to enable incremental workflows.

## Convergence

The analyzer runs iterative repair cycles:

1. Analyze → find violations
2. Generate tasks
3. Apply fixes
4. Re-analyze
5. Repeat until no violations remain (convergence) or max cycles reached

## Further Reading

- [Configuration](configuration.md) — customize analysis behavior
- [CLI Reference](cli-reference.md) — command documentation
- [Schema Reference](schema-reference.md) — JSON schema details
- [Failure Modes](failure-modes.md) — error handling and recovery
