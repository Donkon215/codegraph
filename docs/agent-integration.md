# Agent Integration Guide

codegraph is designed to be consumed by AI agents (GitHub Copilot, Claude,
GPT-based coding assistants, etc.). This guide explains how agents interact
with codegraph's JSON interfaces.

## JSON Mode

All commands support `--json` for machine-readable output:

```bash
codegraph status --json
codegraph query "callers-of auth.py::validate" --json
codegraph tasks --json
codegraph delta --json
```

JSON output goes to stdout. Logs and progress go to stderr.

## Agent Workflow

A typical agent session follows this loop:

### 1. Discover the graph

```bash
codegraph status --json
```

Returns node count, edge count, and health metrics.

### 2. Query for context

```bash
codegraph explain NODE_ID --json
codegraph query "callers-of NODE_ID" --json
```

The agent uses these to understand what a function does and who calls it.

### 3. Check for problems

```bash
codegraph archi-test --json
codegraph analyze --json
codegraph tasks --json
```

Returns prioritized issues the agent should fix.

### 4. Apply fixes

After making code changes, the agent runs:

```bash
codegraph build
codegraph delta --json
```

The delta output tells the agent what changed.

### 5. Validate repairs

```bash
codegraph validate --json
codegraph archi-test --json
```

If violations remain, the agent loops back to step 3.

## Repair Loop

For automated convergence, use the `repair` command:

```bash
codegraph repair --max-cycles 5 --json
```

This runs the full analyze → apply → delta loop until convergence
or the cycle limit is reached.

## Intent Payloads

Agents can annotate code with intents by producing a JSON payload:

```json
{
  "intents": [
    {
      "node_id": "src/auth.py::validate_token",
      "intent": "Validates JWT tokens from incoming requests",
      "status": "approved"
    }
  ]
}
```

Then apply it:

```bash
codegraph intent-apply payload.json
```

## Task Consumption

Tasks in `tasks.json` follow this schema:

```json
{
  "id": "T-001",
  "priority": "P1",
  "category": "missing-intent",
  "node_id": "src/auth.py::validate_token",
  "description": "Add intent annotation for validate_token",
  "suggested_fix": {
    "action": "add_intent",
    "target": "src/auth.py::validate_token"
  }
}
```

Priority levels:
- **P0**: Critical — blocks convergence
- **P1**: High — should be fixed soon
- **P2**: Medium — standard maintenance
- **P3**: Low — improvement opportunity
- **P4**: Informational — nice to have

## Error Handling

When a command fails, the exit code indicates the category:

| Exit Code | Meaning            | Agent Action                        |
|-----------|--------------------|------------------------------------|
| 0         | Success            | Continue                           |
| 1         | General error      | Log and report to user             |
| 2         | Validation failure | Fix validation issues and retry    |
| 3         | Version mismatch   | Update agent_response version      |
| 4         | Config error       | Check .codegraph/config.yaml       |

With `--json`, errors include structured details:

```json
{
  "error": "VersionMismatchError",
  "message": "Graph version mismatch: expected 3, got 2",
  "recovery": "Re-read the current graph_0.json version before responding"
}
```

## Test Impact

After modifying files, determine which tests to run:

```bash
codegraph test-impact --changed src/auth.py --json
```

Returns a list of test files and functions affected by the change.

## Best Practices for Agents

1. Always use `--json` for parsing output.
2. Check `codegraph status --json` before starting work.
3. Run `codegraph validate` after making changes.
4. Use `codegraph explain` to understand unfamiliar code.
5. Respect layer boundaries — don't modify layer 0/1/2 code.
6. Apply intents to document what you changed and why.
7. Use `codegraph delta` to verify your changes had the intended effect.
