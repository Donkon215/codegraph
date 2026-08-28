# Changelog

All notable changes to codegraph will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] — 2026-08-28

First stable foundation release. CodeGraph provides a persistent code graph and
indexed query/analysis system that survives iterative code changes through
`build → delta → query/analyze` without becoming inconsistent.

### Added
- CLI interface with 30+ commands via Click (`codegraph build`, `query`, `explain`, etc.)
- Graph\_0 extraction from Python AST (functions, classes, methods, modules)
- Graph\_1 intent annotation layer with validation
- Workflow edge builder (static, runtime, AI-inferred confidence)
- Suggested workflow policy engine (must-call, must-not-call, layer-lock)
- Task generation system with priority-based ordering
- Apply module for automated code repair actions
- Delta engine for incremental change detection
- Query language (callers, callees, depends-on, type/layer filters)
- Architecture test runner (layer violations, circular dependencies)
- Test impact analysis from changed nodes
- SQLite-backed graph index with WAL mode
- Output formatting (text, JSON, table, CSV, count)
- Shell completion for bash, zsh, and fish
- Structured logging with JSON and human-readable formats
- Performance benchmarks for index and query subsystems
- Comprehensive test suite (18 test files)
- CI/CD with GitHub Actions (Python 3.9–3.12 matrix)
- Pre-commit hooks (black, ruff, mypy)

### Fixed
- #3 — `dependencies()` now stops traversal at `--limit` (BFS breaks once the
  limit of dependency nodes is discovered) instead of walking the whole graph
  and truncating the result afterwards.
- #2 — Delta detects staged-but-uncommitted changes (`git diff HEAD` covers the
  index + working tree, so staged modifications/deletions/renames are caught).
- #6 — Incremental index update preserves test relationships on delta (test
  rows rebuilt from the canonical generation, not a second rule).
- #7 — Runtime trace parser builds correct edges from source order.
- #9 — `build` and `build → delta` produce logically equivalent indexes
  (canonical snapshot/diff; full call-site collection on every delta).
- #10 — Delta now prunes deleted nodes from Graph_1 (graph1.json) so the index,
  graph0, and graph1 stay in lock-step after a file deletion; adds an end-to-end
  developer-workflow regression test.

## [0.1.0] — 2025-01-01

### Added
- Initial release with core graph extraction pipeline.
- Click-based CLI entry point.
- JSON file storage backend.
- MIT license.

[1.0.0]: https://github.com/codegraph/codegraph/compare/v0.1.0...v1.0.0
[0.1.0]: https://github.com/codegraph/codegraph/releases/tag/v0.1.0
