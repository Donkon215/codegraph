# Changelog

All notable changes to codegraph will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

## [0.1.0] — 2025-01-01

### Added
- Initial release with core graph extraction pipeline.
- Click-based CLI entry point.
- JSON file storage backend.
- MIT license.

[Unreleased]: https://github.com/codegraph/codegraph/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/codegraph/codegraph/releases/tag/v0.1.0
