---
name: codegraph-query-language
description: "Reference skill for the codegraph query expression language. Use when constructing codegraph query commands to explore the graph, trace dependencies, find violations, or understand architecture structure."
origin: codegraph
---

# Codegraph Query Language Skill

Reference for writing `codegraph query "<expression>"` commands.

## When to Use

- Exploring dependencies of a specific node
- Finding all callers/callees of a function
- Locating policy violations programmatically
- Identifying cross-layer edges
- Building custom architecture reports

## Core Query Patterns

### Dependency Traversal

```bash
# All direct callees of a node
codegraph query "callees(services/user_service.py::UserService::create_user)"

# All direct callers of a node
codegraph query "callers(codegraph/index.py::build_index)"

# Transitive callees (full downstream dependency tree)
codegraph query "transitive_callees(codegraph/cli.py::main)"

# Path between two nodes
codegraph path codegraph/extractor.py codegraph/graph_build.py
```

### Subsystem Queries

```bash
# All nodes in a subsystem
codegraph query "SELECT nodes IN subsystem(payment)"

# Subsystem root node
codegraph query "SELECT subsystem WHERE root=services/payment_service.py"

# Cross-subsystem edges
codegraph query "SELECT edges WHERE crosses_subsystem=true"
```

### Violation Queries

```bash
# All nodes with policy violations
codegraph query "SELECT nodes WHERE has_violation=true"

# Frontend calls to backend
codegraph query "SELECT edges WHERE edge_type='frontend_to_backend'"

# Unmatched frontend API calls
codegraph query "SELECT frontend_calls WHERE unmatched=true"
```

### Node Filtering

```bash
# Nodes by arch layer
codegraph query "SELECT nodes WHERE arch_layer='Service'"

# God modules (high fan-out)
codegraph query "SELECT nodes WHERE fan_out > 12"

# Orphan nodes
codegraph query "SELECT nodes WHERE callers=0 AND callees=0"

# Nodes with missing intents
codegraph query "SELECT nodes WHERE intent=null"
```

### Cycle Detection

```bash
codegraph policy --cycles
codegraph query "SELECT cycles WHERE length > 1"
```

## Node ID Format

```
relative/path/to/file.py::ClassName::method_name
relative/path/to/file.py::ClassName          (class-level)
relative/path/to/file.py                     (module-level)
```

Examples:
```
codegraph/index.py::build_index
codegraph/extractor.py::Extractor::extract
sample_project/services/user_service.py::UserService::create_user
```

## Workflow Graph Queries

```bash
# Full call workflow from entry point
codegraph workflow --trace --level function

# Architecture-level workflow
codegraph workflow --archi

# Include import edges
codegraph workflow --include-imports
```

## Semantic Graph Queries (Graph2)

```bash
# Semantic neighbors of a node
codegraph semantic show codegraph/extractor.py::Extractor --json

# Semantic summary of the system
codegraph semantic summary --json

# Check semantic health
codegraph semantic check --json
```

## Explain a Node

```bash
# Human-readable explanation
codegraph explain codegraph/analyzer.py::Analyzer

# JSON explanation (for agent consumption)
codegraph explain codegraph/analyzer.py::Analyzer --json
```

## Useful Composition Patterns

### Find all nodes touched by a change

```bash
# What does this module affect?
codegraph path <changed_module> <target_module>
codegraph query "transitive_callees(<changed_module>)"
```

### Check before deleting a function

```bash
codegraph query "callers(<node_id>)"
# If 0 callers → safe to remove
# If >0 callers → update references first
```

### Trace a failing API route

```bash
# Find who calls the route handler
codegraph query "callers(backend/api.py::get_orders)"
# Find what the handler calls
codegraph query "callees(backend/api.py::get_orders)"
```
