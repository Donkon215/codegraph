# Failure Modes & Recovery

codegraph defines specific exception types for each failure mode. This
document lists all failure modes, their causes, and recovery actions.

## Exception Hierarchy

All exceptions inherit from `CodegraphError`:

```
CodegraphError
├── ASTParseError
├── ModuleImportError
├── NodeIDCollisionError
├── IntentConflictError
├── StaleBodyHashError
├── GraphDriftError
├── TraceCrashError
├── DanglingRuleError
├── LayerViolationError
├── RepairConflictError
├── AlreadyConnectedError
├── InsufficientDeadCodeSignalsError
├── DeltaUncommittedError
├── VersionMismatchError
├── IndexInconsistencyError
├── CycleMismatchError
└── ProjectNotFoundError
```

## Failure Mode Reference

### ASTParseError

**Cause**: A source file contains syntax errors that prevent AST parsing.

**Recovery**:
1. Fix the syntax error in the source file.
2. Run `codegraph build` again.
3. If the file is intentionally unparseable, exclude it via config.

### ModuleImportError

**Cause**: A module referenced in an import statement cannot be resolved.

**Recovery**:
1. Ensure the module is installed (`pip install <module>`).
2. Check for typos in import statements.
3. If it's an optional dependency, this warning can be ignored.

### NodeIDCollisionError

**Cause**: Two distinct AST entities produced the same node ID — typically
caused by duplicate function names in the same file scope.

**Recovery**:
1. Rename one of the conflicting entities.
2. Run `codegraph build --full` for a clean rebuild.

### IntentConflictError

**Cause**: An intent annotation conflicts with an existing one for the
same node.

**Recovery**:
1. Review existing intents with `codegraph explain NODE_ID`.
2. Remove the conflicting intent or update it.

### StaleBodyHashError

**Cause**: The function body changed after an intent was annotated.
The `body_hash` no longer matches.

**Recovery**:
1. Review the code change.
2. Re-annotate the intent: `codegraph intent-apply`.
3. This confirms the intent still applies after the code change.

### GraphDriftError

**Cause**: The Graph\_0 structure no longer matches the source files — typically
after manual file edits without rebuilding.

**Recovery**:
1. Run `codegraph build` to regenerate Graph\_0.
2. Use `codegraph delta` to see what changed.

### TraceCrashError

**Cause**: Coverage tracing crashed during runtime profiling.

**Recovery**:
1. Check the test that triggered the trace.
2. Run tests normally to verify they pass.
3. Retry with `codegraph build --full`.

### DanglingRuleError

**Cause**: A suggested workflow rule references a node that no longer exists
in Graph\_0.

**Recovery**:
1. Run `codegraph suggest validate` to find dangling rules.
2. Remove or update the dangling rule.

### LayerViolationError

**Cause**: An operation attempted to modify a node at a non-modifiable layer
(0 = stdlib, 1 = external, 2 = internal lib).

**Recovery**:
1. Only modify nodes at layer 3 (project) or 4 (test).
2. If the layer assignment is wrong, use `--layer-override`.

### RepairConflictError

**Cause**: Two repair actions conflict — e.g., both try to modify the same
code region.

**Recovery**:
1. Review conflicting actions in `tasks.json`.
2. Apply one at a time with `codegraph apply --dry-run`.
3. Resolve the conflict manually.

### AlreadyConnectedError

**Cause**: An apply action tries to create an edge that already exists.

**Recovery**:
1. This is usually harmless — the edge is already present.
2. Skip the action or remove the duplicate from the task list.

### InsufficientDeadCodeSignalsError

**Cause**: Not enough signals to confidently mark code as dead (requires
4 independent signals).

**Recovery**:
1. Add more analysis passes (runtime trace, test coverage).
2. Do not prune code until sufficient signals are gathered.

### DeltaUncommittedError

**Cause**: Delta was requested but there are uncommitted changes in the
working directory.

**Recovery**:
1. Commit or stash changes first.
2. Or run `codegraph build --full` for a clean rebuild.

### VersionMismatchError

**Cause**: `agent_response.json` references a different `graph_version`
than the current graph.

**Recovery**:
1. Re-read the current `graph_0.json` to get the latest version.
2. Generate a new agent response based on the current version.

### IndexInconsistencyError

**Cause**: Index tables are inconsistent with the underlying graph data.

**Recovery**:
1. Run `codegraph index rebuild` to regenerate the index.
2. Run `codegraph index check` to verify consistency.

### CycleMismatchError

**Cause**: The response cycle number does not match the current task cycle.

**Recovery**:
1. Check the current cycle with `codegraph status`.
2. Update the response to reference the correct cycle.

### ProjectNotFoundError

**Cause**: No `.codegraph/` directory was found in the current directory
or any parent directory.

**Recovery**:
1. Run `codegraph init` to initialize a project.
2. Navigate to the project root.
3. Check that `.codegraph/` exists and is not git-ignored.

## Exit Codes

| Code | Constant              | Meaning              |
|------|-----------------------|----------------------|
| 0    | `EXIT_SUCCESS`        | Success              |
| 1    | `EXIT_ERROR`          | General error        |
| 2    | `EXIT_VALIDATION_FAIL`| Validation failure   |
| 3    | `EXIT_VERSION_MISMATCH`| Version mismatch    |
| 4    | `EXIT_CONFIG_ERROR`   | Configuration error  |
