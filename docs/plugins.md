# Plugins

codegraph supports extension via plugins that can add custom extractors,
analyzers, and output formatters.

## Plugin Architecture

Plugins are Python packages that register entry points under the
`codegraph.plugins` group.

### Entry Point Registration

In your plugin's `pyproject.toml`:

```toml
[project.entry-points."codegraph.plugins"]
my_plugin = "my_plugin:register"
```

### Plugin Interface

A plugin must expose a `register` function that receives the codegraph
plugin registry:

```python
"""my_plugin — Example codegraph plugin."""


def register(registry):
    """Register custom hooks with codegraph."""
    registry.add_extractor("custom_lang", extract_custom)
    registry.add_analyzer("custom_check", analyze_custom)
    registry.add_formatter("custom_fmt", format_custom)


def extract_custom(file_path, config):
    """Extract nodes from a custom file format."""
    nodes = []
    # ... custom extraction logic ...
    return nodes


def analyze_custom(graph, config):
    """Run a custom analysis pass."""
    issues = []
    # ... custom analysis logic ...
    return issues


def format_custom(data, options):
    """Format output in a custom way."""
    # ... custom formatting logic ...
    return formatted_string
```

## Plugin Types

### Extractors

Custom extractors add support for non-Python file types or custom
AST processing:

```python
def extract_sql(file_path, config):
    """Extract nodes from SQL files."""
    nodes = []
    # Parse SQL and create Graph0Node instances
    return nodes
```

### Analyzers

Custom analyzers add project-specific checks:

```python
def analyze_naming(graph, config):
    """Check naming conventions."""
    issues = []
    for node in graph.nodes:
        if node.type == "function" and not node.id.endswith("_handler"):
            if "handler" in node.file:
                issues.append(f"{node.id}: handlers must end with _handler")
    return issues
```

### Formatters

Custom formatters add output formats beyond the built-in text/json/table/csv:

```python
def format_markdown(data, options):
    """Format output as Markdown."""
    lines = ["# Results", ""]
    for item in data:
        lines.append(f"- **{item['id']}**: {item.get('description', '')}")
    return "\n".join(lines)
```

## Example: Complexity Plugin

A complete example that adds cyclomatic complexity analysis:

```python
"""codegraph_complexity — Complexity analysis plugin."""

import ast
from pathlib import Path


def register(registry):
    registry.add_analyzer("complexity", analyze_complexity)


def analyze_complexity(graph, config):
    max_complexity = config.get("max_complexity", 10)
    issues = []

    for node in graph.nodes:
        if node.type not in ("function", "method"):
            continue
        try:
            source = Path(node.file).read_text()
            tree = ast.parse(source)
            complexity = _calculate_complexity(tree, node.line)
            if complexity > max_complexity:
                issues.append({
                    "node_id": node.id,
                    "complexity": complexity,
                    "max": max_complexity,
                    "message": f"Complexity {complexity} exceeds limit {max_complexity}",
                })
        except (OSError, SyntaxError):
            continue

    return issues


def _calculate_complexity(tree, target_line):
    """Calculate cyclomatic complexity for a function at a given line."""
    complexity = 1
    for node in ast.walk(tree):
        if isinstance(node, (ast.If, ast.While, ast.For, ast.ExceptHandler,
                             ast.With, ast.Assert, ast.BoolOp)):
            if hasattr(node, "lineno") and node.lineno >= target_line:
                complexity += 1
    return complexity
```

## Discovery

codegraph discovers plugins via Python entry points at startup. No
configuration is needed — installing the plugin package is sufficient.

List installed plugins:

```bash
codegraph status --verbose
```

The verbose output includes a "Plugins" section listing all discovered plugins.
