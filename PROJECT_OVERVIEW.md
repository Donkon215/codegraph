# Codegraph: Complete Project Overview

> **Codegraph** is a self-evolving AI architecture analysis engine for Python codebases. It's a CLI-driven graph system that extracts, annotates, and analyzes codebase structure — designed specifically for AI agents operating over large and complex codebases.

---

## Table of Contents

1. [Project Vision](#project-vision)
2. [What is Codegraph?](#what-is-codegraph)
3. [Core Concepts](#core-concepts)
4. [The 7-Layer Architecture Pipeline](#the-7-layer-architecture-pipeline)
5. [Graph System](#graph-system)
6. [Key Components](#key-components)
7. [CLI Commands](#cli-commands)
8. [Installation & Quick Start](#installation--quick-start)
9. [Development Setup](#development-setup)
10. [Project Structure](#project-structure)
11. [Key Features](#key-features)
12. [Agent Integration](#agent-integration)
13. [Contributing](#contributing)
14. [License](#license)

---

## Project Vision

Codegraph transforms **unstructured Python codebases into structured knowledge graphs** that AI agents can query, reason over, and act upon. It closes the gap between static code analysis and dynamic architectural evolution by providing:

- **Extraction**: Convert Python AST into a queryable graph structure
- **Annotation**: Layer intent metadata on top of structural elements
- **Analysis**: Detect architecture violations, smells, and drift
- **Planning**: Transform detected issues into agent work queues
- **Execution**: Validate and apply code changes proposed by agents
- **Evolution**: Track architecture changes and predict future health

**Core Philosophy**: Codegraph is an **analysis and mapping engine**, not an auto-repair tool. The agent reads the maps, reasons about architecture, and decides what to change. Codegraph validates those changes and tracks what shifted.

---

## What is Codegraph?

Codegraph answers six critical questions that an agent needs to understand and improve any Python project:

| Question | Answered By | Example |
|---|---|---|
| **What exists in the code?** | Graph_0 (Structure) | Functions, classes, modules, dependency edges |
| **What does each component do?** | Graph_1 (Intent Metadata) | "fetch market data from REST API" |
| **How does it currently behave?** | Workflow Graph | Static call chains, runtime patterns |
| **How *should* it behave?** | Suggested Workflow | Layer policies, call constraints |
| **What is broken or misaligned?** | Tasks & Violations | Missing imports, cycle detection, design violations |
| **What changed since last cycle?** | Delta (Change Log) | Which nodes changed, impact radius, test scope |

### Autonomous Loop

```
Code Changes
    ↓
Extract (Graph_0) → Annotate (Graph_1) → Analyze (Violations)
    ↓
Plan (Tasks) → Execute (Apply) → Validate (Delta)
    ↓
Evolve (Architecture Intelligence) → Repeat
```

---

## Core Concepts

### Graph_0: Structure
The **foundational graph**. Extracted directly from Python AST via `extractor.py`.

- **Nodes**: Functions, classes, methods, modules, variables
- **Edges**: Import relationships, call graphs, inheritance
- **Metadata**: Source line, hash signature, file path, symbol type
- **Immutable**: Generated, not edited by users

Example node:
```json
{
  "id": "src/api.py::fetch_user",
  "type": "function",
  "file": "src/api.py",
  "line": 12,
  "body_hash": "c72b4a8f"
}
```

### Graph_1: Intent Annotation Layer
**User-facing intent overlay** on top of Graph_0. Agents and humans annotate what each component is *intended* to do.

- **Intent**: Human-readable purpose ("fetch OHLCV data from REST API")
- **Layer**: Architectural tier (3=service, 2=domain, 1=infrastructure)
- **Metadata**: Owner, maintenance status, API contract
- **Mutable**: Edited by agents and humans via CLI

Example annotation:
```json
{
  "id": "src/api.py::fetch_user",
  "intent": "retrieve user profile from REST API",
  "layer": 3,
  "owner": "backend-team",
  "api_contract": "GET /api/users/{id}"
}
```

### Workflow Graph
The **behavior graph**. Represents how code actually flows.

- **Static Edges**: Direct Python call relationships (`node A calls node B`)
- **Runtime Edges**: Inferred behavior patterns (callbacks, async patterns)
- **AI-Inferred Edges**: Agent-suggested relationships with confidence scores
- **Constraints**: Policy rules (must-call, must-not-call, layer-lock)

### Tasks
The **agent work queue**. Generated from violations and drift.

- Priority-ordered list of changes for the agent to execute
- Task types: refactor, fix-violation, update-intent, add-test, document
- Each task includes context (impact analysis, affected nodes, suggested remediation)

### Delta
The **change log engine**. Incremental updates between graph states.

- Tracks what nodes/edges changed and why
- Computes impact radius (which tests must re-run)
- Enables convergence analysis (is architecture improving?)

### Architecture Lock
Boundaries that must not be crossed. Example: "Service layer functions must not import from infrastructure layer."

---

## The 7-Layer Architecture Pipeline

Codegraph operates through 7 coordinated layers:

### Layer 1: Intent
**Capture semantic purpose**
- Users/agents annotate what functions *intend* to do
- Builds semantic understanding beyond syntax
- Modules: `architecture_intent.py`, `semantics.py`, `intent_validator.py`

### Layer 2: Architecture
**Define system structure**
- Subsystems, service boundaries, layer definitions
- Modules: `subsystem.py`, `system_architecture_layer.py`, `target_architecture.py`
- Format: `system.json` (subsystem definitions, edges, constraints)

### Layer 3: Analysis
**Detect violations & smells**
- Layer violations (crossing boundaries)
- Circular dependencies
- God modules (too many dependencies)
- Dead code, unused imports
- Modules: `analyzer.py`, `architecture_advisor.py`, `architecture_smells.py`

### Layer 4: Planning
**Convert violations to tasks**
- Prioritize issues by impact
- Generate remediation suggestions
- Modules: `code_planner.py`, `tasks.py`, `architecture_compiler.py`

### Layer 5: Execution
**Apply repairs**
- Execute agent-proposed code changes
- Validate syntax and imports
- Modules: `apply.py`, `branch_executor.py`, `apply_handlers.py`

### Layer 6: Validation
**Measure convergence**
- Verify score improvements
- Check hash convergence (CAS)
- Detect regressions
- Modules: `cas.py`, `delta.py`, `architecture_score.py`

### Layer 7: Evolution
**Improve over time**
- Learn from past decisions
- Predict future vulnerabilities
- Suggest subsystem evolution
- Modules: `arch_memory.py`, `architecture_simulator.py`, `subsystem_lifecycle.py`

---

## Graph System

### How Extraction Works

```
Python Codebase
    ↓
AST Walking (extractor.py)
    ↓
Symbol Resolution (extractor_import_resolver.py)
    ↓
Call Graph Building (extractor_call_graph_extractor.py)
    ↓
Graph_0 (raw structure)
    ↓
Intent Annotation (Graph_1)
    ↓
Index Building (SQLite backend)
    ↓
Query-Ready Graph
```

### Storage Backend

**SQLite with WAL mode** (`index.py`)
- Efficient queries over large graphs (10k+ nodes)
- ACID transactions for consistency
- Index performance benchmarked in `benchmarks/`
- Supports graph introspection and delta computation

### Query Language

Simple expression-based query DSL (`query.py`):

```bash
codegraph query "callees(src/api.py::fetch_user)"
codegraph query "callers(src/service.py::validate)"
codegraph query "depends_on(src/module.py)"
codegraph query "SELECT nodes WHERE layer=3 AND crosses_subsystem=true"
```

---

## Key Components

### Core Modules

| Module | Purpose |
|--------|---------|
| **extractor.py** | AST extraction → Graph_0 |
| **graph_build.py** | Graph construction and indexing |
| **index.py** | SQLite graph index with query support |
| **query.py** | Query language parser and executor |
| **analyzer.py** | Convergence analysis and violation detection |
| **tasks.py** | Task generation from violations |
| **apply.py** | Execute code repairs |
| **delta.py** | Incremental change detection |
| **suggest.py** | Suggested workflow policy engine |

### Architecture Intelligence

| Module | Purpose |
|--------|---------|
| **architecture_advisor.py** | High-level architecture recommendations |
| **architecture_simulator.py** | Simulate proposed changes before execution |
| **architecture_proof.py** | Formal verification of safety |
| **arch_memory.py** | Learn from past decisions |
| **architecture_drift.py** | Detect code vs. architecture drift |
| **drift_detector.py** | Real-time drift monitoring |

### Cross-Language Support

| Module | Purpose |
|--------|---------|
| **cross_language_linker.py** | Connect Python routes to TypeScript/React components |
| **context_flow_graph.py** | Track data flow across service boundaries |

### Subsystem Management

| Module | Purpose |
|--------|---------|
| **subsystem.py** | Subsystem definition and validation |
| **subsystem_discovery.py** | Auto-detect subsystem boundaries |
| **subsystem_lifecycle.py** | Track subsystem evolution |
| **subsystem_graph.py** | Build graphs scoped to subsystems |

### AI Agent Integration

| Module | Purpose |
|--------|---------|
| **copilot_context_builder.py** | Generate enriched context for Copilot |
| **copilot_intelligence.py** | Smart context filtering and ranking |
| **agent_memory.py** | Track agent reasoning and decisions |

---

## CLI Commands

### Core Pipeline Commands

```bash
# Extract and build all graphs
codegraph build

# Detect architecture violations
codegraph analyze

# Generate agent task queue
codegraph tasks

# Apply agent-proposed repairs
codegraph apply agent_response.json

# Compute incremental changes
codegraph delta

# Show project overview
codegraph status
```

### Query & Exploration

```bash
# Query graph relationships
codegraph query "callees(src/api.py::fetch_user)"
codegraph query "callers(src/service.py::validate)"

# Get comprehensive node information
codegraph explain src/api.py::fetch_user

# Show graph changes
codegraph diff

# Validate workflow integrity
codegraph validate
```

### Architecture Management

```bash
# Get architecture advisor report
codegraph architect

# Enrich workflow edges with intent
codegraph enrich

# Check boundary enforcement
codegraph lock

# Detect code vs architecture drift
codegraph drift

# Simulate architecture changes
codegraph arch-simulate

# Generate comprehensive Copilot context
codegraph copilot-context
```

### Governance & Policy

```bash
# List all policy rules
codegraph suggest list

# Add a new rule
codegraph suggest add

# Remove a rule
codegraph suggest remove
```

### Content Addressing & Semantics

```bash
# Compute content hashes
codegraph cas build

# Verify hash integrity
codegraph cas verify

# Extract semantic behaviors
codegraph semantic build

# Show behavior statistics
codegraph semantic summary

# Semantic policy checks
codegraph semantic check
```

---

## Installation & Quick Start

### Installation

```bash
# From PyPI
pip install codegraph

# From source (development)
git clone https://github.com/codegraph/codegraph.git
cd codegraph
pip install -e ".[dev]"
```

### Quick Start

```bash
# Navigate to your Python project
cd /path/to/your/project

# Build graphs
codegraph build

# Check project status
codegraph status

# Generate tasks
codegraph tasks

# Review tasks in .codegraph/tasks/tasks.json
cat .codegraph/tasks/tasks.json

# Agent processes tasks, creates .codegraph/responses/agent_response.json
# Apply changes
codegraph apply agent_response.json

# Measure delta
codegraph delta
```

### Output Structure

After `codegraph build`, your project contains:

```
.codegraph/
├── graphs/
│   ├── graph0.json          # Raw structure
│   ├── graph1.json          # Annotated structure
│   ├── graph0.db            # SQLite index
│   └── graph1.db            # Annotated index
├── architecture/
│   └── system.json          # Subsystem definitions
├── workflow/
│   └── workflow.json        # Behavior edges and constraints
├── analysis/
│   ├── violations.json      # Detected violations
│   └── smells.json          # Code quality issues
├── tasks/
│   └── tasks.json           # Agent work queue
├── responses/
│   └── agent_response.json  # Agent-proposed repairs
├── delta/
│   ├── delta.json           # Change log
│   └── impact.json          # Test impact analysis
└── decisions/
    └── DEC-*.json           # Architecture reasoning traces
```

---

## Development Setup

### Prerequisites

- Python 3.9+
- `pip` or `poetry`
- `git`

### Environment Setup

```bash
# Clone repository
git clone https://github.com/codegraph/codegraph.git
cd codegraph

# Create virtual environment
python -m venv .venv
source .venv/bin/activate        # Linux/macOS
.venv\Scripts\activate           # Windows

# Install in editable mode with dev dependencies
pip install -e ".[dev]"

# Install pre-commit hooks
pre-commit install
```

### Running Tests

```bash
# Run full test suite
pytest

# Run with coverage
pytest --cov=codegraph --cov-report=term-missing

# Run specific test file
pytest tests/test_models.py

# Run specific test
pytest tests/test_models.py::TestGraph0Node::test_required_fields

# Run with verbose output
pytest -v
```

### Code Quality Tools

The project uses automated code quality checks:

- **ruff**: Linting and import sorting
- **black**: Code formatting (line length 100)
- **mypy**: Static type checking
- **pytest**: Unit and integration tests

Run manually:

```bash
# Linting
ruff check codegraph/ tests/

# Formatting
black --check codegraph/ tests/

# Type checking
mypy codegraph/ --ignore-missing-imports

# All checks (via pre-commit)
pre-commit run --all-files
```

---

## Project Structure

### Directory Layout

```
codegraph/
├── __init__.py                 # Package metadata, version
├── __main__.py                 # Entry point
├── cli/                        # Click CLI commands
│   ├── __init__.py
│   └── (40+ command modules)
├── cli_groups/                 # Command groupings
├── models/                     # Data models (Graph0, Graph1, Workflow)
├── schemas/                    # JSON schemas for validation
├── utils/                      # Utility functions
├── extractors/                 # AST extraction strategies
├── templates/                  # Code generation templates
├── config.py                   # Configuration loading
├── extractor.py                # Main AST walker
├── graph_build.py              # Graph construction
├── index.py                    # SQLite indexing
├── query.py                    # Query language
├── analyzer.py                 # Analysis engine
├── tasks.py                    # Task generation
├── apply.py                    # Repair execution
├── delta.py                    # Change detection
├── suggest.py                  # Policy rules
├── architecture_*.py           # Architecture modules (30+)
├── subsystem_*.py              # Subsystem modules (10+)
├── copilot_*.py                # Agent integration modules
└── (50+ additional modules)
tests/
├── test_models.py              # Data model tests
├── test_extractor.py           # AST extraction tests
├── test_graph_build.py         # Graph construction tests
├── test_index.py               # Indexing tests
├── test_query.py               # Query language tests
├── test_analyzer.py            # Analysis tests
├── (13+ additional test files)
└── cross_language/             # Cross-language tests
benchmarks/
├── benchmark_build.py          # Graph build performance
├── benchmark_query.py          # Query performance
└── index_benchmark.py          # Index performance
docs/
examples/
sample_project/                 # Example project for testing
```

### Module Categories

**Core Graph System** (12 modules)
- Extraction, indexing, querying, and storage

**Architecture Analysis** (30+ modules)
- Violation detection, drift monitoring, evolution planning

**Subsystem Management** (10+ modules)
- Service boundary detection, lifecycle tracking

**AI Integration** (8 modules)
- Copilot context generation, agent memory, cross-language linking

**CLI & Output** (8 modules)
- Command structure, formatting, logging

**Utilities** (15+ modules)
- Hashing, ID generation, configuration, error handling

---

## Key Features

### ✅ Graph Extraction
- Full Python AST parsing (functions, classes, methods, imports)
- Call graph inference
- Recursive type resolution
- Package boundaries detection

### ✅ Intent Layer
- Semantic annotation overlay
- Layer-based architecture
- API contract specification
- Ownership tracking

### ✅ Analysis Engine
- Layer violation detection
- Circular dependency discovery
- God module identification
- Dead code detection
- Usage pattern analysis

### ✅ Task Generation
- Priority-based ordering
- Impact radius computation
- Test impact analysis
- Remediation suggestions

### ✅ Policy Enforcement
- Architecture locks (must/must-not-call rules)
- Layer constraints
- Subsystem boundary enforcement
- Custom policy rules

### ✅ Change Tracking
- Delta computation (what changed)
- Impact analysis (which tests to run)
- Convergence metrics (is code improving?)
- Score trending

### ✅ Agent Integration
- Copilot context generation
- Task queue production
- Response parsing and validation
- Repair execution

### ✅ Cross-Language Support
- Python↔TypeScript API linking
- Service boundary detection
- React component↔Python route mapping
- Shared data model integration

### ✅ Subsystem Evolution
- Auto-detect subsystem boundaries
- Track lifecycle (creation, growth, refactoring, deprecation)
- Predict splitting candidates
- Suggest reorganization

### ✅ Performance
- SQLite backend for large graphs (10k+ nodes)
- Incremental indexing
- Benchmarks for extraction and query

### ✅ Comprehensive Testing
- 18 test files
- Architecture tests (layer violations)
- Test impact analysis
- Cross-language tests
- CI/CD matrix (Python 3.9–3.12)

---

## Agent Integration

### How Agents Use Codegraph

```
Agent Loop:
1. Read .codegraph/feedback.md (architecture prompts)
2. Run `codegraph tasks` → get work queue
3. Process each task (refactor, fix, update)
4. Create agent_response.json with proposed changes
5. Run `codegraph apply agent_response.json` → apply changes
6. Run `codegraph delta` → measure impact
7. Repeat
```

### Agent Response Format

Agents create `.codegraph/responses/agent_response.json`:

```json
{
  "tasks_completed": [
    {
      "task_id": "TASK-001",
      "type": "refactor",
      "node": "src/api.py::fetch_user",
      "changes": [
        {
          "file": "src/api.py",
          "change_type": "modify",
          "before": "...",
          "after": "..."
        }
      ],
      "reasoning": "Move to service layer..."
    }
  ],
  "validation": {
    "syntax_check": "passed",
    "import_check": "passed",
    "test_commands": ["pytest tests/test_api.py"]
  }
}
```

### Reactive Server

For continuous feedback, run:

```bash
codegraph server
```

The server watches your codebase and pushes architecture prompts to `.codegraph/feedback.md` automatically.

---

## Contributing

### Contribution Process

1. **Fork** the repository
2. **Create a branch** for your feature (`git checkout -b feature/your-feature`)
3. **Install dev dependencies** (`pip install -e ".[dev]"`)
4. **Write tests** for new code
5. **Run tests** (`pytest`)
6. **Lint your code** (`ruff check .`, `black .`, `mypy .`)
7. **Commit** with descriptive messages
8. **Push** and **create a pull request**

### Development Workflow

```bash
# Setup
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install

# Make changes
# ... edit files ...

# Test
pytest -v

# Lint
pre-commit run --all-files

# Push
git add .
git commit -m "Your message"
git push origin feature/your-feature
```

### What to Contribute

- **Bug fixes**: Report and fix issues
- **Features**: New CLI commands, graph capabilities, analysis types
- **Tests**: Improve coverage
- **Documentation**: Enhance guides and examples
- **Performance**: Optimize extraction, indexing, queries

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed guidelines.

---

## License

Codegraph is licensed under the **MIT License**. See [LICENSE](LICENSE) file for details.

---

## Resources

- **GitHub**: https://github.com/codegraph/codegraph
- **Documentation**: See `docs/` directory
- **Examples**: See `examples/` directory
- **Test Suite**: See `tests/` directory
- **Security**: See [SECURITY.md](SECURITY.md)

---

## Summary

Codegraph is a **powerful, graph-based architecture analysis engine** that transforms Python codebases into structured knowledge that AI agents can reason over and act upon. It provides:

- **Extraction**: Convert code to queryable graphs
- **Analysis**: Detect violations and smells
- **Planning**: Generate agent work queues
- **Execution**: Validate and apply changes
- **Evolution**: Track and improve architecture over time

Whether you're building architecture analysis tools, AI-first development platforms, or automated refactoring systems, codegraph provides the foundational infrastructure to understand, analyze, and evolve complex Python codebases at scale.

---

**Version**: 0.1.0  
**Status**: Active Development  
**Python**: 3.9+  
**Last Updated**: April 2026
