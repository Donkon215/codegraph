# Contributing to codegraph

Thank you for your interest in contributing to codegraph! This document explains
how to set up a development environment, run tests, and submit changes.

## Development Setup

```bash
# Clone the repository
git clone https://github.com/codegraph/codegraph.git
cd codegraph

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
.venv\Scripts\activate      # Windows

# Install in editable mode with dev dependencies
pip install -e ".[dev]"

# Install pre-commit hooks
pre-commit install
```

## Running Tests

```bash
# Run the full test suite
pytest

# Run with coverage
pytest --cov=codegraph --cov-report=term-missing

# Run a specific test file
pytest tests/test_models.py

# Run a specific test
pytest tests/test_models.py::TestGraph0Node::test_required_fields
```

## Code Quality

The project uses several tools to maintain code quality:

- **ruff** — linting and import sorting
- **black** — code formatting (line length 100)
- **mypy** — static type checking

Pre-commit hooks run these automatically. To run manually:

```bash
ruff check codegraph/ tests/
black --check codegraph/ tests/
mypy codegraph/ --ignore-missing-imports
```

## Project Structure

```
codegraph/
├── __init__.py          # Package metadata and version
├── cli.py               # Click CLI commands
├── config.py            # Project configuration loading
├── exceptions.py        # Custom exception hierarchy
├── extractor.py         # AST extraction → Graph_0
├── formatters.py        # Output formatting (text/json/table/csv)
├── logging_config.py    # Structured logging
├── models/              # Data models (graph0, graph1, workflow, etc.)
├── utils/               # Utility modules (hashing, IDs, formatting)
├── index.py             # SQLite graph index
├── query.py             # Query language parser and executor
├── suggest.py           # Suggested workflow policy engine
├── analyzer.py          # Convergence analysis
├── tasks.py             # Task generation
├── apply.py             # Repair actions
└── delta.py             # Incremental change detection
```

## Submitting Changes

1. Fork the repository and create a feature branch from `main`.
2. Write clear, focused commits with descriptive messages.
3. Ensure all tests pass and linting is clean.
4. Open a pull request against `main`.

### Commit Messages

Use conventional commit format:

```
feat: add support for decorated functions in extractor
fix: handle empty graph in delta engine
docs: update CLI reference with new commands
test: add property-based tests for workflow edges
```

### Pull Request Guidelines

- Keep PRs focused on a single change.
- Include tests for new functionality.
- Update documentation if the change affects user-facing behavior.
- Ensure CI passes before requesting review.

## Architecture Decisions

Significant design choices are documented as Architecture Decision Records (ADRs)
in `docs/adr/`. When proposing a change that alters the system's architecture,
add a new ADR following the existing format.

## Reporting Issues

Open an issue on GitHub with:
- A clear description of the problem or feature request.
- Steps to reproduce (for bugs).
- Expected vs actual behavior.
- codegraph version (`codegraph version`).

## License

By contributing, you agree that your contributions will be licensed under the
MIT License.
