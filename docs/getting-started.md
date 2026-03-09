# Getting Started

This guide walks you through installing codegraph, initializing a project,
and running your first analysis.

## Installation

```bash
pip install codegraph
```

Or install from source:

```bash
git clone https://github.com/codegraph/codegraph.git
cd codegraph
pip install -e ".[dev]"
```

## Quick Start

### 1. Initialize a project

Navigate to your Python project root and run:

```bash
codegraph init
```

This creates a `.codegraph/` directory with default configuration.

### 2. Build the graph

```bash
codegraph build
```

This extracts the AST from all Python files and produces:
- `.codegraph/graph_0.json` — raw structural graph (functions, classes, calls)
- `.codegraph/graph_1.json` — intent annotations
- `.codegraph/workflow.json` — call edges with confidence levels

### 3. Check status

```bash
codegraph status
```

Shows node counts, edge counts, and graph health.

### 4. Query the graph

```bash
# Find all callers of a function
codegraph query "callers-of auth.py::validate_token"

# Find all functions in a file
codegraph query "type:function file:auth.py"

# Find layer violations
codegraph archi-test
```

### 5. Generate tasks

```bash
codegraph tasks
```

Produces `.codegraph/tasks.json` with prioritized fix suggestions.

## Project Structure

After initialization, your project will contain:

```
your-project/
├── .codegraph/
│   ├── config.yaml          # Configuration
│   ├── graph_0.json         # Structural graph
│   ├── graph_1.json         # Intent annotations
│   ├── workflow.json        # Call edges
│   ├── suggested_workflow/  # Policy rules
│   ├── tasks.json           # Generated tasks
│   ├── delta.json           # Change tracking
│   ├── codegraph.db         # SQLite index
│   └── .gitignore           # Ignores DB and temp files
└── ... your source code ...
```

## Next Steps

- [Concepts](concepts.md) — understand the graph model
- [CLI Reference](cli-reference.md) — full command documentation
- [Configuration](configuration.md) — customize analysis behavior
- [Agent Integration](agent-integration.md) — use with AI agents
