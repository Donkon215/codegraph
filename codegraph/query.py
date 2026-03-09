"""codegraph.query — Graph query parser and executor.

Group L: L-001 through L-022.
"""

from __future__ import annotations

import json
import re
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from codegraph.index import IndexStore
from codegraph.logging_config import get_logger

logger = get_logger("query")


# ═══════════════════════════════════════════════════════════════════════
# Data Structures
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class ParsedQuery:
    """Result of parsing a query string (L-001)."""

    function: str
    args: List[str] = field(default_factory=list)
    options: Dict[str, Any] = field(default_factory=dict)


@dataclass
class QueryResult:
    """Unified query result (L-011)."""

    nodes: List[str] = field(default_factory=list)
    paths: List[List[str]] = field(default_factory=list)  # for path queries
    total: int = 0
    truncated: bool = False
    query: str = ""
    function: str = ""
    elapsed_ms: float = 0.0
    message: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExplainResult:
    """Comprehensive node information (L-016)."""

    node_id: str = ""
    file: str = ""
    line: int = 0
    node_type: str = ""
    body_hash: str = ""
    intent: str = ""
    layer: int = -1
    arch_layer: str = ""
    tags: List[str] = field(default_factory=list)
    callers: List[str] = field(default_factory=list)
    callees: List[str] = field(default_factory=list)
    tests: List[str] = field(default_factory=list)
    dependency_hash: str = ""
    stale_intent: bool = False
    found: bool = False


@dataclass
class QueryOptions:
    """Common options for query execution (L-009, L-010)."""

    depth: Optional[int] = None
    limit: Optional[int] = None
    output_format: str = "text"  # text | json | tree | count
    verbose: bool = False


# ═══════════════════════════════════════════════════════════════════════
# L-001 — Query Parser
# L-012 — Node ID Quoting Rules
# ═══════════════════════════════════════════════════════════════════════

QUERY_FUNCTIONS = {
    "callers", "callees", "dependencies", "dependents",
    "path", "orphans", "layer", "tests", "explain",
    "imports", "effects", "actions", "guards",
    "domain", "pure", "unguarded", "risky",
}

# Pattern: function_name("arg1", "arg2", key=value, ...)
_QUERY_RE = re.compile(
    r'^(\w+)\s*\(\s*(.*?)\s*\)$', re.DOTALL,
)

_QUOTED_ARG_RE = re.compile(r'"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\'')
_OPTION_RE = re.compile(r'(\w+)\s*=\s*(\d+)')


def parse_query(query_string: str) -> ParsedQuery:
    """Parse a query string into structured form (L-001, L-012).

    Examples:
        callers("my/file.py::MyClass::method")
        callees("node_id", depth=2, limit=10)
        path("source", "target")
        orphans()
        layer(3)
    """
    query_string = query_string.strip()

    m = _QUERY_RE.match(query_string)
    if not m:
        # Try bare function name (no parens)
        bare = query_string.strip()
        if bare in QUERY_FUNCTIONS:
            return ParsedQuery(function=bare)
        raise ValueError(
            f"Invalid query syntax: {query_string!r}. "
            f"Expected: function(\"args\", options...)"
        )

    func_name = m.group(1)
    args_str = m.group(2)

    if func_name not in QUERY_FUNCTIONS:
        raise ValueError(
            f"Unknown query function: {func_name!r}. "
            f"Valid functions: {', '.join(sorted(QUERY_FUNCTIONS))}"
        )

    result = ParsedQuery(function=func_name)

    if not args_str.strip():
        return result

    # Extract quoted arguments
    for qm in _QUOTED_ARG_RE.finditer(args_str):
        arg = qm.group(1) if qm.group(1) is not None else qm.group(2)
        # Unescape
        arg = arg.replace('\\"', '"').replace("\\'", "'")
        result.args.append(arg)

    # Extract key=value options
    for om in _OPTION_RE.finditer(args_str):
        result.options[om.group(1)] = int(om.group(2))

    # If no quoted args, try bare numeric argument (e.g., layer(3))
    if not result.args:
        bare_num = args_str.strip()
        # Remove any options we already parsed
        for om in _OPTION_RE.finditer(args_str):
            bare_num = bare_num.replace(om.group(0), "").strip().strip(",").strip()
        if bare_num:
            # Try as bare unquoted node ID or number
            try:
                val = int(bare_num)
                result.args.append(str(val))
            except ValueError:
                # Treat as unquoted node ID — warn user
                result.args.append(bare_num)

    return result


# ═══════════════════════════════════════════════════════════════════════
# L-002 — callers() Query Function
# ═══════════════════════════════════════════════════════════════════════


def query_callers(
    node_id: str,
    index: IndexStore,
    *,
    depth: int = 1,
    limit: Optional[int] = None,
) -> QueryResult:
    """Return nodes that call the target (L-002)."""
    if depth < 1:
        raise ValueError("depth must be >= 1")

    result = QueryResult(function="callers", query=f'callers("{node_id}")')

    if depth == 1:
        result.nodes = sorted(index.get_callers(node_id))
    else:
        visited: Set[str] = set()
        queue: deque[Tuple[str, int]] = deque([(node_id, 0)])
        while queue:
            current, d = queue.popleft()
            if d > 0:
                visited.add(current)
            if d >= depth:
                continue
            for caller in index.get_callers(current):
                if caller not in visited and caller != node_id:
                    queue.append((caller, d + 1))
        result.nodes = sorted(visited)

    result.total = len(result.nodes)
    if limit and len(result.nodes) > limit:
        result.nodes = result.nodes[:limit]
        result.truncated = True
    return result


# ═══════════════════════════════════════════════════════════════════════
# L-003 — callees() Query Function
# ═══════════════════════════════════════════════════════════════════════


def query_callees(
    node_id: str,
    index: IndexStore,
    *,
    depth: int = 1,
    limit: Optional[int] = None,
) -> QueryResult:
    """Return nodes that the target calls (L-003)."""
    if depth < 1:
        raise ValueError("depth must be >= 1")

    result = QueryResult(function="callees", query=f'callees("{node_id}")')

    if depth == 1:
        result.nodes = sorted(index.get_callees(node_id))
    else:
        visited: Set[str] = set()
        queue: deque[Tuple[str, int]] = deque([(node_id, 0)])
        while queue:
            current, d = queue.popleft()
            if d > 0:
                visited.add(current)
            if d >= depth:
                continue
            for callee in index.get_callees(current):
                if callee not in visited and callee != node_id:
                    queue.append((callee, d + 1))
        result.nodes = sorted(visited)

    result.total = len(result.nodes)
    if limit and len(result.nodes) > limit:
        result.nodes = result.nodes[:limit]
        result.truncated = True
    return result


# ═══════════════════════════════════════════════════════════════════════
# L-004 — dependencies() Query Function
# ═══════════════════════════════════════════════════════════════════════


def query_dependencies(
    node_id: str,
    index: IndexStore,
    *,
    depth: Optional[int] = None,
    limit: Optional[int] = None,
) -> QueryResult:
    """Return all transitive dependencies (callees-of-callees) (L-004)."""
    result = QueryResult(function="dependencies", query=f'dependencies("{node_id}")')
    result.nodes = index.get_dependencies_recursive(node_id, max_depth=depth)
    result.total = len(result.nodes)
    if limit and len(result.nodes) > limit:
        result.nodes = result.nodes[:limit]
        result.truncated = True
    return result


# ═══════════════════════════════════════════════════════════════════════
# L-005 — dependents() Query Function
# ═══════════════════════════════════════════════════════════════════════


def query_dependents(
    node_id: str,
    index: IndexStore,
    *,
    depth: Optional[int] = None,
    limit: Optional[int] = None,
) -> QueryResult:
    """Return all transitive dependents (callers-of-callers) (L-005)."""
    result = QueryResult(function="dependents", query=f'dependents("{node_id}")')

    visited: Set[str] = set()
    queue: deque[Tuple[str, int]] = deque([(node_id, 0)])

    while queue:
        current, d = queue.popleft()
        if current in visited:
            continue
        if d > 0:
            visited.add(current)
        if depth is not None and d >= depth:
            continue
        for caller in index.get_callers(current):
            if caller not in visited:
                queue.append((caller, d + 1))

    result.nodes = sorted(visited)
    result.total = len(result.nodes)
    if limit and len(result.nodes) > limit:
        result.nodes = result.nodes[:limit]
        result.truncated = True
    return result


# ═══════════════════════════════════════════════════════════════════════
# L-006 — path() Query Function
# ═══════════════════════════════════════════════════════════════════════


def query_path(
    source: str,
    target: str,
    index: IndexStore,
    *,
    depth: Optional[int] = None,
) -> QueryResult:
    """Find the shortest path between two nodes (L-006)."""
    result = QueryResult(function="path", query=f'path("{source}", "{target}")')

    max_d = depth if depth else 50
    path = index.shortest_path(source, target, max_depth=max_d)

    if path:
        result.paths = [path]
        result.nodes = path
        result.total = len(path)
    else:
        result.message = f"No path found from {source} to {target}"

    return result


# ═══════════════════════════════════════════════════════════════════════
# L-007 — orphans() Query Function
# ═══════════════════════════════════════════════════════════════════════


def query_orphans(
    index: IndexStore,
    *,
    layer: Optional[int] = None,
    limit: Optional[int] = None,
) -> QueryResult:
    """Return orphan nodes (L-007)."""
    result = QueryResult(function="orphans", query="orphans()")

    orphans = index.get_orphans()

    if layer is not None:
        layer_nodes = set(index.get_nodes_at_layer(layer))
        orphans = [o for o in orphans if o in layer_nodes]

    result.nodes = orphans
    result.total = len(result.nodes)
    if limit and len(result.nodes) > limit:
        result.nodes = result.nodes[:limit]
        result.truncated = True
    return result


# ═══════════════════════════════════════════════════════════════════════
# L-008 — layer() Query Function
# ═══════════════════════════════════════════════════════════════════════


def query_layer(
    layer: int,
    index: IndexStore,
    *,
    limit: Optional[int] = None,
) -> QueryResult:
    """Return all nodes at a specific layer (L-008)."""
    result = QueryResult(function="layer", query=f"layer({layer})")
    result.nodes = sorted(index.get_nodes_at_layer(layer))
    result.total = len(result.nodes)
    if limit and len(result.nodes) > limit:
        result.nodes = result.nodes[:limit]
        result.truncated = True
    return result


# ═══════════════════════════════════════════════════════════════════════
# L-014 — Query Auto-Complete Suggestions
# ═══════════════════════════════════════════════════════════════════════


def _suggest_nodes(node_id: str, index: IndexStore, max_suggestions: int = 5) -> List[str]:
    """Find similar node IDs when exact match not found (L-014)."""
    # Try prefix match
    suggestions = index.search_nodes(f"{node_id}*", limit=max_suggestions)
    if suggestions:
        return suggestions

    # Try contains match
    suggestions = index.search_nodes(f"*{node_id}*", limit=max_suggestions)
    if suggestions:
        return suggestions

    # Try last segment (function name only)
    parts = node_id.split("::")
    if len(parts) > 1:
        func_name = parts[-1]
        suggestions = index.search_nodes(f"*{func_name}*", limit=max_suggestions)
        if suggestions:
            return suggestions

    return []


# ═══════════════════════════════════════════════════════════════════════
# L-016 — explain() Query Command
# ═══════════════════════════════════════════════════════════════════════


def explain_node(
    node_id: str,
    index: IndexStore,
    graph0: Any = None,
    graph1: Any = None,
) -> ExplainResult:
    """Show comprehensive information about a node (L-016)."""
    result = ExplainResult(node_id=node_id)

    # Index data
    node_data = index.get_node(node_id)
    if not node_data:
        return result

    result.found = True
    result.file = node_data.get("file", "")
    result.line = node_data.get("line", 0)
    result.node_type = node_data.get("type", "")
    result.body_hash = node_data.get("body_hash", "")
    result.layer = node_data.get("layer", -1)
    result.arch_layer = node_data.get("arch_layer", "")

    # Dependency hash
    dep_hash = index.get_dependency_hash(node_id)
    if dep_hash:
        result.dependency_hash = dep_hash

    # Callers and callees (first 10)
    result.callers = index.get_callers(node_id)[:10]
    result.callees = index.get_callees(node_id)[:10]

    # Tests
    result.tests = index.get_tests_for_node(node_id)

    # Graph_1 enrichment
    if graph1:
        g1_node = graph1.get_node(node_id)
        if g1_node:
            result.intent = g1_node.intent or ""
            result.tags = list(g1_node.tags) if g1_node.tags else []
            if g1_node.intent_body_hash and result.body_hash:
                result.stale_intent = g1_node.intent_body_hash != result.body_hash

    return result


def format_explain(result: ExplainResult, as_json: bool = False) -> str:
    """Format explain result for display (L-016)."""
    if as_json:
        return json.dumps({
            "node_id": result.node_id,
            "found": result.found,
            "file": result.file,
            "line": result.line,
            "type": result.node_type,
            "body_hash": result.body_hash,
            "intent": result.intent,
            "layer": result.layer,
            "arch_layer": result.arch_layer,
            "tags": result.tags,
            "callers": result.callers,
            "callees": result.callees,
            "tests": result.tests,
            "dependency_hash": result.dependency_hash,
            "stale_intent": result.stale_intent,
        }, indent=2)

    if not result.found:
        return f"Node not found: {result.node_id}"

    lines = [
        f"Node:            {result.node_id}",
        f"  file:          {result.file}",
        f"  line:          {result.line}",
        f"  type:          {result.node_type}",
        f"  body_hash:     {result.body_hash}",
        f"  layer:         {result.layer}",
    ]
    if result.arch_layer:
        lines.append(f"  arch_layer:    {result.arch_layer}")
    if result.intent:
        lines.append(f"  intent:        {result.intent}")
        if result.stale_intent:
            lines.append("  intent_stale:  YES — body changed since intent was written")
    if result.tags:
        lines.append(f"  tags:          {', '.join(result.tags)}")
    if result.dependency_hash:
        lines.append(f"  dep_hash:      {result.dependency_hash}")
    if result.callers:
        lines.append(f"  callers ({len(result.callers)}):")
        for c in result.callers:
            lines.append(f"    ← {c}")
    if result.callees:
        lines.append(f"  callees ({len(result.callees)}):")
        for c in result.callees:
            lines.append(f"    → {c}")
    if result.tests:
        lines.append(f"  tests ({len(result.tests)}):")
        for t in result.tests:
            lines.append(f"    ✓ {t}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# L-017 — Query Caching
# ═══════════════════════════════════════════════════════════════════════


class QueryCache:
    """LRU cache for query results (L-017)."""

    def __init__(self, max_size: int = 256, graph_version: int = 0) -> None:
        self._cache: Dict[str, QueryResult] = {}
        self._order: List[str] = []
        self._max_size = max_size
        self._graph_version = graph_version

    def _key(self, func: str, args: Tuple, depth: Any, limit: Any) -> str:
        return f"{func}:{args}:{depth}:{limit}"

    def get(self, func: str, args: Tuple, depth: Any, limit: Any) -> Optional[QueryResult]:
        key = self._key(func, args, depth, limit)
        return self._cache.get(key)

    def put(self, func: str, args: Tuple, depth: Any, limit: Any, result: QueryResult) -> None:
        key = self._key(func, args, depth, limit)
        if key in self._cache:
            self._order.remove(key)
        elif len(self._cache) >= self._max_size:
            oldest = self._order.pop(0)
            del self._cache[oldest]
        self._cache[key] = result
        self._order.append(key)

    def invalidate(self, new_version: int) -> None:
        if new_version != self._graph_version:
            self._cache.clear()
            self._order.clear()
            self._graph_version = new_version


# ═══════════════════════════════════════════════════════════════════════
# L-018 — Import Dependency Query
# ═══════════════════════════════════════════════════════════════════════


def query_import_dependencies(
    module: str,
    project_root: Path,
    *,
    depth: Optional[int] = None,
    limit: Optional[int] = None,
) -> QueryResult:
    """Follow import edges for module-level dependencies (L-018)."""
    from codegraph.storage import resolve_path

    result = QueryResult(function="imports", query=f'imports("{module}")')

    imports_path = resolve_path(project_root, "workflow") / "imports.json"
    if not imports_path.exists():
        result.message = "No imports.json found — run 'codegraph workflow' first"
        return result

    try:
        imports_data = json.loads(imports_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        result.message = "Failed to read imports.json"
        return result

    # BFS through import graph
    visited: Set[str] = set()
    queue: deque[Tuple[str, int]] = deque([(module, 0)])

    while queue:
        current, d = queue.popleft()
        if current in visited:
            continue
        if d > 0:
            visited.add(current)
        if depth is not None and d >= depth:
            continue
        # imports_data: {file: [imported_names...]} or {file: {imports: [...]}}
        file_imports = imports_data.get(current, [])
        if isinstance(file_imports, dict):
            file_imports = file_imports.get("imports", [])
        if isinstance(file_imports, list):
            for imp in file_imports:
                if isinstance(imp, str) and imp not in visited:
                    queue.append((imp, d + 1))

    result.nodes = sorted(visited)
    result.total = len(result.nodes)
    if limit and len(result.nodes) > limit:
        result.nodes = result.nodes[:limit]
        result.truncated = True
    return result


# ═══════════════════════════════════════════════════════════════════════
# L-013 — Query Execution Engine
# L-015 — Boolean Query Composition
# L-019 — Query Performance Monitoring
# L-020 — Batch Query Support
# ═══════════════════════════════════════════════════════════════════════


def execute_query(
    query: ParsedQuery,
    index: IndexStore,
    options: QueryOptions,
    *,
    project_root: Optional[Path] = None,
    graph0: Any = None,
    graph1: Any = None,
    cache: Optional[QueryCache] = None,
) -> QueryResult:
    """Dispatch parsed query to the correct handler (L-013)."""
    depth = query.options.get("depth", options.depth)
    limit = query.options.get("limit", options.limit)
    args_tuple = tuple(query.args)

    # L-017 — Check cache
    if cache:
        cached = cache.get(query.function, args_tuple, depth, limit)
        if cached:
            cached.metadata["cached"] = True
            return cached

    # L-019 — Timing
    t0 = time.perf_counter()

    func = query.function
    result: QueryResult

    if func == "callers":
        if not query.args:
            raise ValueError("callers() requires a node ID argument")
        result = query_callers(query.args[0], index, depth=depth or 1, limit=limit)

    elif func == "callees":
        if not query.args:
            raise ValueError("callees() requires a node ID argument")
        result = query_callees(query.args[0], index, depth=depth or 1, limit=limit)

    elif func == "dependencies":
        if not query.args:
            raise ValueError("dependencies() requires a node ID argument")
        result = query_dependencies(query.args[0], index, depth=depth, limit=limit)

    elif func == "dependents":
        if not query.args:
            raise ValueError("dependents() requires a node ID argument")
        result = query_dependents(query.args[0], index, depth=depth, limit=limit)

    elif func == "path":
        if len(query.args) < 2:
            raise ValueError('path() requires two arguments: path("source", "target")')
        result = query_path(query.args[0], query.args[1], index, depth=depth)

    elif func == "orphans":
        layer_arg = int(query.args[0]) if query.args else None
        result = query_orphans(index, layer=layer_arg, limit=limit)

    elif func == "layer":
        if not query.args:
            raise ValueError("layer() requires a layer number")
        result = query_layer(int(query.args[0]), index, limit=limit)

    elif func == "tests":
        if not query.args:
            raise ValueError("tests() requires a node ID argument")
        node_id = query.args[0]
        tests = index.get_tests_for_node(node_id)
        result = QueryResult(function="tests", query=f'tests("{node_id}")')
        result.nodes = tests
        result.total = len(tests)
        if limit and len(result.nodes) > limit:
            result.nodes = result.nodes[:limit]
            result.truncated = True

    elif func == "explain":
        if not query.args:
            raise ValueError("explain() requires a node ID argument")
        # Returns explain result formatted as QueryResult
        er = explain_node(query.args[0], index, graph0=graph0, graph1=graph1)
        result = QueryResult(function="explain", query=f'explain("{query.args[0]}")')
        result.metadata["explain"] = er
        if er.found:
            result.nodes = [er.node_id]
            result.total = 1
        else:
            result.message = f"Node not found: {query.args[0]}"

    elif func == "imports":
        if not query.args:
            raise ValueError("imports() requires a module path argument")
        if project_root is None:
            raise ValueError("imports() requires project_root")
        result = query_import_dependencies(
            query.args[0], project_root, depth=depth, limit=limit,
        )

    elif func in ("effects", "actions", "guards", "domain", "pure", "unguarded", "risky"):
        # L-021 / L-022 — Semantic queries (stub for Group R)
        result = QueryResult(function=func, query=f'{func}({", ".join(query.args)})')
        result.message = (
            f"Semantic query '{func}' requires Graph_2 (Group R). "
            f"Run 'codegraph build --semantic' first."
        )

    else:
        raise ValueError(f"Unknown query function: {func}")

    elapsed = (time.perf_counter() - t0) * 1000
    result.elapsed_ms = elapsed

    # L-014 — Auto-suggest on empty results for node-specific queries
    if not result.nodes and not result.message and func in (
        "callers", "callees", "dependencies", "dependents", "tests",
    ):
        node_id = query.args[0] if query.args else ""
        node_data = index.get_node(node_id)
        if not node_data:
            suggestions = _suggest_nodes(node_id, index)
            if suggestions:
                result.message = (
                    f"Node not found: {node_id!r}. "
                    f"Did you mean: {', '.join(suggestions[:5])}"
                )
            else:
                result.message = f"Node not found: {node_id!r}"

    # L-019 — Log slow queries
    if elapsed > 100:
        logger.warning("Slow query (%.0fms): %s", elapsed, result.query)

    # L-017 — Store in cache
    if cache:
        cache.put(query.function, args_tuple, depth, limit, result)

    return result


# ═══════════════════════════════════════════════════════════════════════
# L-015 — Boolean Query Composition
# ═══════════════════════════════════════════════════════════════════════

_BOOL_SPLIT = re.compile(r'\s+(AND|OR|NOT)\s+', re.IGNORECASE)


def parse_boolean_query(query_string: str) -> List[Tuple[str, str]]:
    """Split a boolean query into parts (L-015).

    Returns list of (operator, query_string) tuples.
    First operator is always 'START'.
    """
    parts = _BOOL_SPLIT.split(query_string)
    if len(parts) == 1:
        return [("START", parts[0].strip())]

    result: List[Tuple[str, str]] = []
    i = 0
    while i < len(parts):
        if i == 0:
            result.append(("START", parts[0].strip()))
        else:
            op = parts[i].upper()
            if i + 1 < len(parts):
                result.append((op, parts[i + 1].strip()))
                i += 1
        i += 1
    return result


def execute_boolean_query(
    query_string: str,
    index: IndexStore,
    options: QueryOptions,
    **kwargs: Any,
) -> QueryResult:
    """Execute a boolean query composition (L-015)."""
    parts = parse_boolean_query(query_string)

    if len(parts) == 1:
        parsed = parse_query(parts[0][1])
        return execute_query(parsed, index, options, **kwargs)

    # Execute each sub-query
    combined_set: Optional[Set[str]] = None

    for op, sub_query_str in parts:
        parsed = parse_query(sub_query_str)
        sub_result = execute_query(parsed, index, options, **kwargs)
        sub_set = set(sub_result.nodes)

        if op == "START":
            combined_set = sub_set
        elif op == "AND":
            if combined_set is not None:
                combined_set &= sub_set
        elif op == "OR":
            if combined_set is not None:
                combined_set |= sub_set
        elif op == "NOT":
            if combined_set is not None:
                combined_set -= sub_set

    result = QueryResult(function="boolean", query=query_string)
    result.nodes = sorted(combined_set or set())
    result.total = len(result.nodes)

    if options.limit and len(result.nodes) > options.limit:
        result.nodes = result.nodes[:options.limit]
        result.truncated = True

    return result


# ═══════════════════════════════════════════════════════════════════════
# L-011 — Query Result Formatter
# ═══════════════════════════════════════════════════════════════════════


def format_query_result(
    result: QueryResult,
    index: IndexStore,
    *,
    output_format: str = "text",
    verbose: bool = False,
) -> str:
    """Format query results for CLI display (L-011)."""
    # Handle explain specially
    if result.function == "explain" and "explain" in result.metadata:
        return format_explain(result.metadata["explain"], as_json=(output_format == "json"))

    if output_format == "json":
        data: Dict[str, Any] = {
            "query": result.query,
            "function": result.function,
            "total": result.total,
            "truncated": result.truncated,
            "elapsed_ms": round(result.elapsed_ms, 2),
            "nodes": result.nodes,
        }
        if result.paths:
            data["paths"] = result.paths
        if result.message:
            data["message"] = result.message
        return json.dumps(data, indent=2)

    if output_format == "count":
        return str(result.total)

    if output_format == "tree" and result.paths:
        lines: List[str] = []
        for path in result.paths:
            for i, node in enumerate(path):
                prefix = "  " * i + ("└─ " if i > 0 else "")
                lines.append(f"{prefix}{node}")
        return "\n".join(lines)

    # Default: text
    lines = []

    if result.message:
        lines.append(result.message)

    if result.function == "path" and result.paths:
        lines.append(f"Path ({len(result.paths[0])} nodes):")
        for i, node in enumerate(result.paths[0]):
            arrow = "  → " if i > 0 else "    "
            lines.append(f"{arrow}{node}")
    else:
        for node_id in result.nodes:
            if verbose:
                node_data = index.get_node(node_id)
                if node_data:
                    lines.append(
                        f"{node_id}  ({node_data.get('file', '?')}:"
                        f"{node_data.get('line', '?')})"
                    )
                else:
                    lines.append(node_id)
            else:
                lines.append(node_id)

    if result.truncated:
        lines.append(f"… {result.total - len(result.nodes)} more results not shown")

    # Summary
    if verbose:
        lines.append(f"\n{result.total} results in {result.elapsed_ms:.1f}ms")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# L-020 — Batch Query Support
# ═══════════════════════════════════════════════════════════════════════


def execute_batch(
    queries: List[str],
    index: IndexStore,
    options: QueryOptions,
    **kwargs: Any,
) -> List[QueryResult]:
    """Execute multiple queries, sharing the index connection (L-020)."""
    cache = QueryCache()
    results: List[QueryResult] = []
    for q in queries:
        if " AND " in q.upper() or " OR " in q.upper() or " NOT " in q.upper():
            r = execute_boolean_query(q, index, options, cache=cache, **kwargs)
        else:
            parsed = parse_query(q)
            r = execute_query(parsed, index, options, cache=cache, **kwargs)
        results.append(r)
    return results


# ═══════════════════════════════════════════════════════════════════════
# CLI Entry Points
# ═══════════════════════════════════════════════════════════════════════


def run_query(
    expression: str,
    project_root: Path,
    *,
    depth: Optional[int] = None,
    limit: Optional[int] = None,
    output_format: str = "text",
    verbose: bool = False,
) -> str:
    """Execute a query and return formatted output (CLI entry point)."""
    from codegraph.extractor import load_graph0
    from codegraph.annotator import load_graph1

    options = QueryOptions(
        depth=depth,
        limit=limit,
        output_format=output_format,
        verbose=verbose,
    )

    graph0 = load_graph0(project_root)
    graph1 = load_graph1(project_root)

    with IndexStore(project_root) as index:
        if " AND " in expression.upper() or " OR " in expression.upper() or " NOT " in expression.upper():
            result = execute_boolean_query(
                expression, index, options,
                project_root=project_root, graph0=graph0, graph1=graph1,
            )
        else:
            parsed = parse_query(expression)
            result = execute_query(
                parsed, index, options,
                project_root=project_root, graph0=graph0, graph1=graph1,
            )

        return format_query_result(
            result, index, output_format=output_format, verbose=verbose,
        )
