# ADR 001 — Storage Backend Design

## Status
**Proposed** — 2026-03-06

## Context
codegraph stores all graph data as JSON files under `.codegraph/`. This works
well for small-to-medium repositories (up to ~500 files, ~5 000 nodes).  For
larger codebases the JSON backend becomes a bottleneck: full file I/O on every
operation, no partial reads/writes, and no native query capability.

## Decision Drivers
- **Read/write patterns**: Frequent reads (queries, explain, status),
  batch writes (build, delta).
- **Index integration**: The index layer already uses SQLite — ideally
  the graph layer would share the same database connection.
- **Migration overhead**: Existing projects have JSON graphs; migration
  must be seamless.
- **Tooling**: SQLite has excellent Python stdlib support (`sqlite3`).
  DuckDB offers analytical queries but adds a dependency.

## Considered Options

### 1. SQLite
- **Pros**: stdlib support, WAL mode for concurrent reads, single-file DB,
  well-understood. The index module already uses SQLite.
- **Cons**: not columnar, slightly more complex writes than JSON.

### 2. DuckDB
- **Pros**: columnar, fast analytical queries, Parquet export.
- **Cons**: extra dependency (~50 MB), less battle-tested embedded use,
  overkill for write-heavy graph mutations.

### 3. Keep JSON only
- **Pros**: zero dependencies, human-readable files.
- **Cons**: O(N) load/save, no partial update, no query support.

## Decision
Start with a **JSON + SQLite hybrid**:
- **JSON** for `.codegraph/graphs/*.json` (human-readable, git-diffable).
- **SQLite** for the index layer and as a future primary backend.
- Define a `GraphStore` Protocol (A-035) that both JSON and DB backends
  implement, allowing transparent migration.

When a project exceeds ~500 files, the CLI will suggest switching to the
SQLite backend via `codegraph migrate --to-sqlite`.

## Consequences
- All modules use the `GraphStore` Protocol, never concrete file paths.
- The JSON backend is the default for v0.1.
- A SQLite backend can be added in v0.2 without touching business logic.
- Migration tooling must handle both directions (JSON → SQLite, SQLite → JSON).
