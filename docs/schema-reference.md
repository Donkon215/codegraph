# Schema Reference

codegraph stores all analysis data as JSON files under `.codegraph/`.
This document describes the schema for each file.

## Graph\_0 — `graph_0.json`

The structural graph extracted from source code.

```json
{
  "version": 1,
  "timestamp": "2025-01-01T00:00:00Z",
  "nodes": [
    {
      "id": "src/auth.py::validate_token",
      "file": "src/auth.py",
      "type": "function",
      "line": 42,
      "body_hash": "a1b2c3d4",
      "layer": 3,
      "calls": ["src/db.py::get_user", "src/cache.py::lookup"],
      "decorators": ["require_auth"]
    }
  ]
}
```

### Node Fields

| Field        | Type       | Required | Description                          |
|-------------|-----------|---------|--------------------------------------|
| `id`         | string     | Yes     | Unique node identifier               |
| `file`       | string     | Yes     | Source file path (relative)          |
| `type`       | string     | Yes     | `function`, `method`, `class`, `module` |
| `line`       | integer    | Yes     | Line number in source file           |
| `body_hash`  | string     | Yes     | Content hash of function body        |
| `layer`      | integer    | Yes     | Layer classification (0–4)           |
| `calls`      | string[]   | No      | Node IDs of called functions         |
| `decorators` | string[]   | No      | Decorator names                      |

## Graph\_1 — `graph_1.json`

Intent annotations layered on top of Graph\_0.

```json
{
  "version": 1,
  "timestamp": "2025-01-01T00:00:00Z",
  "nodes": [
    {
      "id": "src/auth.py::validate_token",
      "intent": "Validates JWT tokens from incoming requests",
      "status": "approved",
      "body_hash_at_annotation": "a1b2c3d4",
      "owner": "auth-team"
    }
  ]
}
```

### Intent Node Fields

| Field                    | Type   | Required | Description                        |
|--------------------------|--------|----------|------------------------------------|
| `id`                     | string | Yes      | Must match a Graph\_0 node ID      |
| `intent`                 | string | Yes      | Human-readable purpose             |
| `status`                 | string | Yes      | `approved`, `needs-review`, `deprecated` |
| `body_hash_at_annotation`| string | Yes      | Hash when intent was written       |
| `owner`                  | string | No       | Responsible team or agent          |

## Workflow — `workflow.json`

Call edges between nodes with confidence levels.

```json
{
  "version": 1,
  "timestamp": "2025-01-01T00:00:00Z",
  "edges": [
    {
      "source": "src/api.py::handle_request",
      "target": "src/auth.py::validate_token",
      "edge_type": "call",
      "confidence": "static"
    }
  ]
}
```

### Edge Fields

| Field        | Type   | Required | Description                                |
|-------------|--------|----------|--------------------------------------------|
| `source`     | string | Yes      | Caller node ID                             |
| `target`     | string | Yes      | Callee node ID                             |
| `edge_type`  | string | Yes      | `call`, `test`, `trace`                    |
| `confidence` | string | Yes      | `static`, `runtime`, `ai_inferred`         |

## Tasks — `tasks.json`

Generated work items.

```json
{
  "version": 1,
  "timestamp": "2025-01-01T00:00:00Z",
  "tasks": [
    {
      "id": "T-001",
      "priority": "P1",
      "category": "missing-intent",
      "node_id": "src/auth.py::validate_token",
      "description": "Add intent annotation",
      "suggested_fix": {
        "action": "add_intent",
        "target": "src/auth.py::validate_token",
        "value": "Validates JWT tokens"
      }
    }
  ]
}
```

## Delta — `delta.json`

Changes detected between builds.

```json
{
  "version": 1,
  "timestamp": "2025-01-01T00:00:00Z",
  "added": ["src/new_module.py::new_func"],
  "removed": ["src/old_module.py::deleted_func"],
  "modified": [
    {
      "id": "src/auth.py::validate_token",
      "old_hash": "a1b2c3d4",
      "new_hash": "e5f6g7h8"
    }
  ]
}
```

## Suggested Workflow Rules

Rules stored as individual YAML files under `.codegraph/suggested_workflow/`.

```yaml
id: rule-001
type: must-call
scope:
  source: "src/api.py::*"
  target: "src/logging.py::log_request"
description: "All API handlers must log requests"
```

### Rule Types

| Type           | Description                                    |
|---------------|------------------------------------------------|
| `must-call`    | Source must call target                         |
| `must-not-call`| Source must not call target                     |
| `layer-lock`   | Enforces layer boundary (no cross-layer calls) |

## Version Field

All top-level JSON files include a `version` field (integer) for schema
evolution. The current version is `1`. The CLI will warn if it encounters
a higher version (forward compatibility).
