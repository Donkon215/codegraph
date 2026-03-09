# CLI Reference

Complete reference for all codegraph commands. Run `codegraph --help` for
a summary or `codegraph <command> --help` for command-specific options.

## Global Options

```
--verbose / -v    Enable verbose output (debug logging, timing)
--quiet / -q      Suppress non-essential output
--json            Emit machine-readable JSON output
--no-color        Disable colored output
```

## Project Management

### `codegraph init`

Initialize a new codegraph project in the current directory.

```bash
codegraph init [--force]
```

Creates `.codegraph/` with default configuration. Use `--force` to
reinitialize an existing project.

### `codegraph status`

Show project status — node counts, edge counts, graph health.

```bash
codegraph status [--json]
```

### `codegraph version`

Display version information.

```bash
codegraph version [--verbose]
```

Shows codegraph version, Python version, and executable path.

## Building

### `codegraph build`

Extract graphs from source code.

```bash
codegraph build [--full] [--layer-override PATH:LAYER]
```

Options:
- `--full` — force full rebuild (ignore cache)
- `--layer-override` — override layer for specific paths (repeatable)

### `codegraph validate`

Validate graph consistency and schema compliance.

```bash
codegraph validate [--json]
```

## Querying

### `codegraph query`

Run a graph query.

```bash
codegraph query "EXPRESSION" [--format FORMAT] [--limit N]
```

Query expressions:
- `callers-of NODE_ID` — find all callers
- `callees-of NODE_ID` — find all callees
- `depends-on NODE_ID` — transitive dependencies
- `type:function` — filter by node type
- `layer:3` — filter by layer
- `file:path.py` — filter by file

### `codegraph explain`

Explain a node's role, callers, callees, and intent.

```bash
codegraph explain NODE_ID [--json]
```

## Intent Annotations

### `codegraph intent-missing`

List nodes missing intent annotations.

```bash
codegraph intent-missing [--format FORMAT]
```

### `codegraph intent-apply`

Apply intent annotations from a JSON payload.

```bash
codegraph intent-apply PAYLOAD_FILE [--dry-run]
```

### `codegraph annotate`

Add inline intent annotations to source files.

```bash
codegraph annotate [--format FORMAT]
```

## Workflow & Policy

### `codegraph workflow`

Display or manage the workflow graph.

```bash
codegraph workflow [--json] [--stats]
```

### `codegraph suggest`

Manage suggested workflow rules.

```bash
codegraph suggest add RULE_FILE
codegraph suggest remove RULE_ID
codegraph suggest list [--format FORMAT]
codegraph suggest validate
codegraph suggest diff
codegraph suggest stats
codegraph suggest import-template TEMPLATE
```

## Analysis

### `codegraph analyze`

Run convergence analysis.

```bash
codegraph analyze [--max-iterations N] [--json]
```

### `codegraph archi-test`

Run architecture tests (layer violations, circular deps).

```bash
codegraph archi-test [--json]
```

### `codegraph test-impact`

Analyze test impact from changed files.

```bash
codegraph test-impact [--changed FILE ...] [--json]
```

## Task Management

### `codegraph tasks`

Generate or display tasks.

```bash
codegraph tasks [--format FORMAT] [--priority P0-P4]
```

### `codegraph apply`

Apply repair actions.

```bash
codegraph apply [--dry-run] [--json]
```

## Change Detection

### `codegraph delta`

Compute changes since last build.

```bash
codegraph delta [--json]
```

### `codegraph diff`

Show human-readable diff of graph changes.

```bash
codegraph diff [--target graph|workflow|all] [--json]
```

## Maintenance

### `codegraph prune`

Remove dead nodes from the graph.

```bash
codegraph prune [--dry-run] [--json]
```

### `codegraph repair`

Run automated repair loop (analyze → apply → delta).

```bash
codegraph repair [--max-cycles N] [--dry-run] [--json]
```

### `codegraph index`

Manage the SQLite index.

```bash
codegraph index rebuild [--json]
codegraph index dump [--format FORMAT]
codegraph index check [--json]
```

### `codegraph schema`

Display or validate JSON schemas.

```bash
codegraph schema [--json]
```

## Shell Completion

### `codegraph completion`

Generate shell completion scripts.

```bash
codegraph completion --shell bash >> ~/.bashrc
codegraph completion --shell zsh >> ~/.zshrc
codegraph completion --shell fish > ~/.config/fish/completions/codegraph.fish
```

## Exit Codes

| Code | Meaning              |
|------|----------------------|
| 0    | Success              |
| 1    | General error        |
| 2    | Validation failure   |
| 3    | Version mismatch     |
| 4    | Configuration error  |
