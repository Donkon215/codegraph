# Error Codes Reference

codegraph uses structured error codes for machine-readable error reporting.
Each code maps to a specific failure mode.

## Error Code Format

Codes follow the pattern `Ennn` where the first digit indicates the category:

| Range  | Category            |
|--------|---------------------|
| E1xx   | Extraction errors   |
| E2xx   | Graph integrity     |
| E3xx   | Runtime / tracing   |
| E4xx   | Policy violations   |
| E5xx   | Apply / repair      |
| E6xx   | Delta / versioning  |
| E7xx   | Index               |
| E8xx   | Cycle management    |
| E9xx   | Project setup       |

## Complete Reference

### E100 — ASTParseError

Source file could not be parsed into an AST.

**Recovery**: Fix syntax errors in the file and run `codegraph build`.

### E101 — ModuleImportError

A module referenced in an import could not be resolved.

**Recovery**: Install the missing module or verify import paths.

### E200 — NodeIDCollision

Two distinct AST entities produced the same node identifier.

**Recovery**: Rename conflicting entities and run `codegraph build --full`.

### E201 — IntentConflict

An intent annotation conflicts with an existing one for the same node.

**Recovery**: Review and resolve conflicting intents with `codegraph explain NODE_ID`.

### E202 — StaleBodyHash

The function body changed after the intent was annotated.

**Recovery**: Re-annotate the intent after reviewing the code changes.

### E203 — GraphDrift

Graph\_0 structure does not match the current source files.

**Recovery**: Run `codegraph build` to regenerate the graph.

### E300 — TraceCrash

Coverage trace execution crashed during runtime profiling.

**Recovery**: Check the failing test and retry with `codegraph build --full`.

### E400 — DanglingRule

A suggested workflow rule references a node that no longer exists.

**Recovery**: Run `codegraph suggest validate` to find and remove dangling rules.

### E401 — LayerViolation

An operation attempted to modify a node at a non-modifiable layer.

**Recovery**: Only modify nodes at layer 3 (project) or 4 (test).

### E500 — RepairConflict

Two repair actions conflict (overlapping edits).

**Recovery**: Apply actions one at a time with `--dry-run` to isolate conflicts.

### E501 — AlreadyConnected

An apply action tried to create an edge that already exists.

**Recovery**: Skip the duplicate edge creation.

### E502 — InsufficientDeadCodeSignals

Not enough independent signals to classify code as dead.

**Recovery**: Add more analysis passes (runtime trace, test coverage) before pruning.

### E600 — DeltaUncommitted

Delta was requested but there are uncommitted changes.

**Recovery**: Commit or stash changes first, or run `codegraph build --full`.

### E601 — VersionMismatch

`agent_response.json` references a different graph version than current.

**Recovery**: Re-read `graph_0.json` to get the latest version.

### E700 — IndexInconsistency

Index tables are inconsistent with the underlying graph data.

**Recovery**: Run `codegraph index rebuild`.

### E800 — CycleMismatch

Response cycle number does not match the current task cycle.

**Recovery**: Check the current cycle with `codegraph status`.

### E900 — ProjectNotFound

No codegraph project found in the current or parent directories.

**Recovery**: Run `codegraph init` to initialize a new project.

## Programmatic Access

```python
from codegraph.error_codes import lookup, lookup_by_exception, all_codes

# Look up by code
code = lookup("E200")
print(code.message)   # "Two entities produced the same node ID"
print(code.recovery)  # "Rename conflicting entities and run build --full"

# Look up by exception
from codegraph.exceptions import ASTParseError
exc = ASTParseError("bad.py", "invalid syntax")
code = lookup_by_exception(exc)
print(code.code)  # "E100"
```
