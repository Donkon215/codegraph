# ADR 003 — Query Language Design

## Status
**Accepted** — 2025-01-01

## Context
Agents and developers need a way to query the codegraph for specific nodes,
relationships, and patterns. The query interface must be simple enough for
CLI usage, expressive enough for common graph queries, and produce both
human-readable and machine-parseable output.

## Decision Drivers
- CLI-first: queries are typed as command arguments.
- JSON output for agent consumption.
- Common operations: find callers, callees, dependencies, filter by type/layer.
- No need for a full graph query language (Cypher, SPARQL) at v0.1.

## Considered Options

### 1. Mini query DSL
Simple text expressions: `callers-of NODE_ID`, `type:function layer:3`.

**Pros**: Easy to type, easy to parse, covers 90% of use cases.
**Cons**: Not extensible to complex graph patterns.

### 2. Cypher subset
Borrowed from Neo4j: `MATCH (a)-[:CALLS]->(b) WHERE b.id = 'x'`.

**Pros**: Powerful, well-known syntax.
**Cons**: Heavy for a CLI tool, requires a real parser, overkill for v0.1.

### 3. Python filter expressions
`--filter "node.type == 'function' and node.layer == 3"`.

**Pros**: Familiar to Python developers.
**Cons**: Security risks with eval, hard to optimize.

## Decision
Use a **mini query DSL** with these expression types:

- `callers-of NODE_ID` — direct callers
- `callees-of NODE_ID` — direct callees
- `depends-on NODE_ID` — transitive dependencies
- `type:TYPENAME` — filter by node type
- `layer:N` — filter by layer number
- `file:PATTERN` — filter by file path pattern

Expressions can be combined: `type:function layer:3 file:src/auth.py`.

Output defaults to text, `--json` for machine-readable, `--format` for
table/csv formats.

## Consequences
- The query parser is a simple tokenizer (no recursive descent needed).
- Adding new query types requires extending the parser and executor.
- A future v0.2 could add Cypher/GQL support as an alternative backend
  while keeping the mini DSL as the default.
- All query results pass through OutputFormatter for consistent rendering.
