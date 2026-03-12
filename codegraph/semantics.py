"""codegraph.semantics — Semantic behavior extraction engine.

Tasks R-008 through R-021.
Extracts semantic actions, guards, side effects, data flow, domain tags,
and library associations from Python AST nodes.
"""

from __future__ import annotations

import ast
import hashlib
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from codegraph.logging_config import get_logger
from codegraph.models.graph2 import (
    ActionType,
    DataFlowItem,
    DataFlowSummary,
    Graph2,
    Graph2Node,
    Guard,
    SemanticAction,
    SideEffect,
    SideEffectType,
)

logger = get_logger("semantics")


# ═══════════════════════════════════════════════════════════════════════
# R-008 — Verb-to-ActionType Mapping
# ═══════════════════════════════════════════════════════════════════════

_VERB_MAP: Dict[str, ActionType] = {
    "get": ActionType.READ,
    "fetch": ActionType.READ,
    "load": ActionType.READ,
    "read": ActionType.READ,
    "find": ActionType.READ,
    "lookup": ActionType.READ,
    "search": ActionType.READ,
    "query": ActionType.QUERY,
    "select": ActionType.QUERY,
    "set": ActionType.WRITE,
    "put": ActionType.WRITE,
    "save": ActionType.WRITE,
    "store": ActionType.WRITE,
    "write": ActionType.WRITE,
    "insert": ActionType.WRITE,
    "create": ActionType.CREATE,
    "add": ActionType.CREATE,
    "new": ActionType.CREATE,
    "build": ActionType.CREATE,
    "make": ActionType.CREATE,
    "init": ActionType.CREATE,
    "initialize": ActionType.CREATE,
    "delete": ActionType.DELETE,
    "remove": ActionType.DELETE,
    "drop": ActionType.DELETE,
    "destroy": ActionType.DELETE,
    "clear": ActionType.DELETE,
    "update": ActionType.UPDATE,
    "modify": ActionType.UPDATE,
    "patch": ActionType.UPDATE,
    "change": ActionType.UPDATE,
    "edit": ActionType.UPDATE,
    "validate": ActionType.VALIDATE,
    "check": ActionType.VALIDATE,
    "verify": ActionType.VALIDATE,
    "assert": ActionType.VALIDATE,
    "ensure": ActionType.VALIDATE,
    "is_valid": ActionType.VALIDATE,
    "transform": ActionType.TRANSFORM,
    "convert": ActionType.TRANSFORM,
    "map": ActionType.TRANSFORM,
    "parse": ActionType.PARSE,
    "decode": ActionType.PARSE,
    "deserialize": ActionType.PARSE,
    "format": ActionType.FORMAT,
    "encode": ActionType.FORMAT,
    "serialize": ActionType.FORMAT,
    "render": ActionType.FORMAT,
    "send": ActionType.SEND,
    "post": ActionType.SEND,
    "publish": ActionType.SEND,
    "emit": ActionType.SEND,
    "dispatch": ActionType.DISPATCH,
    "notify": ActionType.DISPATCH,
    "receive": ActionType.RECEIVE,
    "consume": ActionType.RECEIVE,
    "subscribe": ActionType.SUBSCRIBE,
    "listen": ActionType.SUBSCRIBE,
    "compute": ActionType.COMPUTE,
    "calculate": ActionType.COMPUTE,
    "process": ActionType.COMPUTE,
    "run": ActionType.COMPUTE,
    "execute": ActionType.COMPUTE,
    "authorize": ActionType.AUTHORIZE,
    "authenticate": ActionType.AUTHORIZE,
    "login": ActionType.AUTHORIZE,
    "permit": ActionType.AUTHORIZE,
    "log": ActionType.LOG,
    "configure": ActionType.CONFIGURE,
    "setup": ActionType.CONFIGURE,
    "cache": ActionType.CACHE,
    "memoize": ActionType.CACHE,
    "retry": ActionType.RETRY,
}


def _classify_verb(func_name: str) -> ActionType:
    """Classify a function name into an ActionType via prefix matching."""
    name = func_name.lower().lstrip("_")
    for prefix, action_type in _VERB_MAP.items():
        if name.startswith(prefix):
            return action_type
    return ActionType.UNKNOWN


# ═══════════════════════════════════════════════════════════════════════
# R-009 — Action Extraction
# ═══════════════════════════════════════════════════════════════════════


def extract_actions(func_node: ast.AST, func_name: str) -> List[SemanticAction]:
    """Extract semantic actions from a function AST node."""
    actions: List[SemanticAction] = []

    # Primary action from function name
    parts = _split_name(func_name)
    if parts:
        verb = parts[0]
        obj = "_".join(parts[1:]) if len(parts) > 1 else ""
        action_type = _classify_verb(verb)
        actions.append(SemanticAction(
            verb=verb,
            object=obj,
            action_type=action_type,
            confidence=0.8 if action_type != ActionType.UNKNOWN else 0.3,
        ))

    # Secondary actions from calls within the body
    if isinstance(func_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        for node in ast.walk(func_node):
            if isinstance(node, ast.Call):
                call_name = _get_call_name(node)
                if call_name and call_name != func_name:
                    ct = _classify_verb(call_name)
                    if ct != ActionType.UNKNOWN:
                        call_parts = _split_name(call_name)
                        actions.append(SemanticAction(
                            verb=call_parts[0] if call_parts else call_name,
                            object="_".join(call_parts[1:]) if len(call_parts) > 1 else "",
                            action_type=ct,
                            confidence=0.5,
                        ))

    return actions


# ═══════════════════════════════════════════════════════════════════════
# R-010 — Guard Extraction
# ═══════════════════════════════════════════════════════════════════════


def extract_guards(func_node: ast.AST) -> List[Guard]:
    """Extract guard clauses (preconditions) from a function body."""
    guards: List[Guard] = []

    if not isinstance(func_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return guards

    for i, stmt in enumerate(func_node.body):
        # Pattern: if <cond>: raise ...
        if isinstance(stmt, ast.If):
            body = stmt.body
            if len(body) == 1 and isinstance(body[0], ast.Raise):
                cond = _unparse_safe(stmt.test)
                exc = _get_raise_type(body[0])
                guards.append(Guard(
                    condition=cond,
                    raises=exc,
                    description=f"Guard clause at line {getattr(stmt, 'lineno', '?')}",
                ))
            elif len(body) == 1 and isinstance(body[0], ast.Return):
                cond = _unparse_safe(stmt.test)
                guards.append(Guard(
                    condition=cond,
                    early_return=True,
                    description=f"Early return guard at line {getattr(stmt, 'lineno', '?')}",
                ))

        # Pattern: assert <expr>
        if isinstance(stmt, ast.Assert):
            cond = _unparse_safe(stmt.test)
            guards.append(Guard(
                condition=cond,
                raises="AssertionError",
                description=f"Assert guard at line {getattr(stmt, 'lineno', '?')}",
            ))

    return guards


# ═══════════════════════════════════════════════════════════════════════
# R-011 — Side Effect Extraction
# ═══════════════════════════════════════════════════════════════════════

_SIDE_EFFECT_PATTERNS: List[Tuple[str, SideEffectType, str]] = [
    # Database
    (r"\.execute\(", SideEffectType.DATABASE_WRITE, "SQL execute"),
    (r"\.executemany\(", SideEffectType.DATABASE_WRITE, "SQL executemany"),
    (r"\.commit\(", SideEffectType.DATABASE_WRITE, "DB commit"),
    (r"\.cursor\(", SideEffectType.DATABASE_READ, "DB cursor"),
    (r"session\.(add|delete|merge|flush)", SideEffectType.DATABASE_WRITE, "ORM write"),
    (r"session\.query", SideEffectType.DATABASE_READ, "ORM query"),
    # Network
    (r"requests\.(get|post|put|delete|patch|head)", SideEffectType.NETWORK_CALL, "HTTP request"),
    (r"httpx\.", SideEffectType.NETWORK_CALL, "HTTP request"),
    (r"urllib", SideEffectType.NETWORK_CALL, "URL request"),
    (r"aiohttp", SideEffectType.NETWORK_CALL, "Async HTTP"),
    (r"socket\.", SideEffectType.NETWORK_CALL, "Socket"),
    # File I/O
    (r"open\(", SideEffectType.FILE_WRITE, "File open"),
    (r"\.write\(", SideEffectType.FILE_WRITE, "File write"),
    (r"\.read\(", SideEffectType.FILE_READ, "File read"),
    (r"Path\(.*\)\.(write_text|write_bytes)", SideEffectType.FILE_WRITE, "Path write"),
    (r"Path\(.*\)\.(read_text|read_bytes)", SideEffectType.FILE_READ, "Path read"),
    (r"shutil\.", SideEffectType.FILE_WRITE, "File copy/move"),
    (r"os\.(remove|unlink|rmdir|makedirs|rename)", SideEffectType.FILE_WRITE, "OS file op"),
    # Process
    (r"subprocess\.", SideEffectType.PROCESS_SPAWN, "Subprocess"),
    (r"os\.system\(", SideEffectType.PROCESS_SPAWN, "OS system call"),
    (r"os\.exec", SideEffectType.PROCESS_SPAWN, "OS exec"),
    # Environment
    (r"os\.environ", SideEffectType.ENVIRONMENT_READ, "Env var access"),
    (r"os\.getenv", SideEffectType.ENVIRONMENT_READ, "Env var read"),
    # Logging
    (r"logger\.", SideEffectType.LOGGING, "Logging"),
    (r"logging\.", SideEffectType.LOGGING, "Logging"),
    (r"print\(", SideEffectType.LOGGING, "Print output"),
    # Cache
    (r"cache\.(get|set|delete|clear)", SideEffectType.CACHE_WRITE, "Cache op"),
    (r"@(lru_cache|cache|cached)", SideEffectType.CACHE_READ, "Cache decorator"),
    # Messaging
    (r"\.(publish|send_message|enqueue)", SideEffectType.MESSAGE_PUBLISH, "Message publish"),
    (r"\.(subscribe|consume|dequeue)", SideEffectType.MESSAGE_CONSUME, "Message consume"),
]


def extract_side_effects(func_node: ast.AST) -> List[SideEffect]:
    """Extract side effects by pattern-matching the unparsed AST source."""
    effects: List[SideEffect] = []
    seen: Set[str] = set()

    if not isinstance(func_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return effects

    source = _unparse_safe(func_node)
    if not source:
        return effects

    for pattern, effect_type, description in _SIDE_EFFECT_PATTERNS:
        match = re.search(pattern, source)
        if match:
            key = f"{effect_type.value}:{description}"
            if key not in seen:
                seen.add(key)
                effects.append(SideEffect(
                    type=effect_type.value,
                    target=match.group(0)[:50],
                    description=description,
                    effect_type=effect_type,
                ))

    return effects


# ═══════════════════════════════════════════════════════════════════════
# R-012 — Data Flow Extraction
# ═══════════════════════════════════════════════════════════════════════


def extract_data_flow(func_node: ast.AST) -> Optional[DataFlowSummary]:
    """Extract data-flow summary: parameters (inputs), return values (outputs)."""
    if not isinstance(func_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return None

    inputs: List[str] = []
    input_items: List[DataFlowItem] = []
    outputs: List[str] = []
    output_items: List[DataFlowItem] = []
    transforms: List[str] = []

    # Inputs from parameters
    for arg in func_node.args.args:
        name = arg.arg
        if name == "self" or name == "cls":
            continue
        ann = _unparse_safe(arg.annotation) if arg.annotation else ""
        inputs.append(name)
        input_items.append(DataFlowItem(name=name, type_annotation=ann))

    # Outputs from return statements
    for node in ast.walk(func_node):
        if isinstance(node, ast.Return) and node.value is not None:
            ret_text = _unparse_safe(node.value)
            if ret_text and ret_text not in outputs:
                outputs.append(ret_text[:80])

    # Return type annotation
    if func_node.returns:
        ret_type = _unparse_safe(func_node.returns)
        if ret_type:
            output_items.append(DataFlowItem(name="return", type_annotation=ret_type))

    # Transforms — assignments with both reads and writes
    for node in ast.walk(func_node):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = _unparse_safe(node.targets[0])
            value = _unparse_safe(node.value)
            if target and value and len(target) < 40 and len(value) < 40:
                transforms.append(f"{target} = {value}")

    # Limit transforms to most interesting
    transforms = transforms[:10]

    if not inputs and not outputs:
        return None

    return DataFlowSummary(
        inputs=inputs,
        outputs=outputs,
        transforms=transforms,
        input_items=input_items,
        output_items=output_items,
    )


# ═══════════════════════════════════════════════════════════════════════
# R-013 — Domain Tag Inference
# ═══════════════════════════════════════════════════════════════════════

_DOMAIN_PATTERNS: Dict[str, List[str]] = {
    "auth": ["auth", "login", "logout", "permission", "role", "token", "jwt", "oauth", "session"],
    "database": ["db", "database", "sql", "query", "migration", "orm", "model", "repository"],
    "api": ["api", "endpoint", "route", "handler", "controller", "rest", "graphql"],
    "ui": ["ui", "view", "template", "render", "component", "widget", "form", "page"],
    "config": ["config", "setting", "environment", "option", "preference"],
    "logging": ["log", "logger", "audit", "trace", "monitor", "metric"],
    "testing": ["test", "fixture", "mock", "stub", "assert", "expect"],
    "io": ["file", "path", "stream", "read", "write", "download", "upload"],
    "network": ["http", "request", "response", "socket", "url", "client"],
    "serialization": ["json", "xml", "yaml", "csv", "serialize", "deserialize", "parse", "encode"],
    "security": ["encrypt", "decrypt", "hash", "sign", "verify", "sanitize", "escape"],
    "cache": ["cache", "memoize", "ttl", "invalidate"],
    "messaging": ["queue", "message", "event", "publish", "subscribe", "notification"],
    "scheduling": ["schedule", "cron", "task", "job", "worker", "celery"],
    "validation": ["validate", "schema", "constraint", "rule", "check"],
}


def infer_domain_tags(
    func_name: str,
    file_path: str,
    source_hint: str = "",
) -> List[str]:
    """Infer domain tags from function name and file path."""
    tags: List[str] = []
    text = f"{func_name} {file_path} {source_hint}".lower()

    for domain, keywords in _DOMAIN_PATTERNS.items():
        for kw in keywords:
            if kw in text:
                if domain not in tags:
                    tags.append(domain)
                break

    return tags


# ═══════════════════════════════════════════════════════════════════════
# R-014 — SQL Operation Classification
# ═══════════════════════════════════════════════════════════════════════

_SQL_PATTERNS: List[Tuple[str, str]] = [
    (r"SELECT\s+", "SELECT"),
    (r"INSERT\s+INTO", "INSERT"),
    (r"UPDATE\s+\w+\s+SET", "UPDATE"),
    (r"DELETE\s+FROM", "DELETE"),
    (r"CREATE\s+TABLE", "CREATE_TABLE"),
    (r"DROP\s+TABLE", "DROP_TABLE"),
    (r"ALTER\s+TABLE", "ALTER_TABLE"),
    (r"CREATE\s+INDEX", "CREATE_INDEX"),
]


def classify_sql_operations(func_node: ast.AST) -> List[str]:
    """Extract SQL operation types from string literals in function body."""
    ops: List[str] = []
    seen: Set[str] = set()

    if not isinstance(func_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return ops

    for node in ast.walk(func_node):
        # Check string constants for SQL keywords
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value.strip()
            if len(text) < 5:
                continue
            for pattern, op_name in _SQL_PATTERNS:
                if re.search(pattern, text, re.IGNORECASE) and op_name not in seen:
                    seen.add(op_name)
                    ops.append(op_name)

    return ops


# ═══════════════════════════════════════════════════════════════════════
# R-015 — Library Call Detection
# ═══════════════════════════════════════════════════════════════════════


def detect_library_calls(
    func_node: ast.AST,
    known_libraries: Optional[Set[str]] = None,
) -> List[str]:
    """Detect calls to known external libraries in the function body."""
    libs: List[str] = []
    seen: Set[str] = set()

    if not isinstance(func_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return libs

    # Default known libraries if none provided
    known = known_libraries or _DEFAULT_KNOWN_LIBRARIES

    for node in ast.walk(func_node):
        if isinstance(node, ast.Attribute):
            # obj.method() where obj is a known library
            root = _get_attribute_root(node)
            if root in known and root not in seen:
                seen.add(root)
                libs.append(root)
        elif isinstance(node, ast.Name):
            if node.id in known and node.id not in seen:
                seen.add(node.id)
                libs.append(node.id)

    return libs


_DEFAULT_KNOWN_LIBRARIES: Set[str] = {
    # Standard library
    "os", "sys", "json", "re", "pathlib", "subprocess", "logging",
    "typing", "collections", "functools", "itertools", "dataclasses",
    "hashlib", "hmac", "secrets", "sqlite3", "unittest", "pytest",
    "datetime", "time", "math", "io", "shutil", "tempfile",
    "threading", "multiprocessing", "asyncio", "socket",
    # Third-party
    "requests", "httpx", "aiohttp", "flask", "django", "fastapi",
    "sqlalchemy", "psycopg2", "pymongo", "redis", "celery",
    "numpy", "pandas", "scipy", "sklearn",
    "boto3", "botocore", "azure", "google",
    "pydantic", "marshmallow", "attrs",
    "click", "typer", "argparse",
    "yaml", "toml", "configparser",
    "pytest", "mock", "hypothesis",
    "jinja2", "mako",
    "cryptography", "jwt",
}


# ═══════════════════════════════════════════════════════════════════════
# R-016 — Full Node Semantic Extraction
# ═══════════════════════════════════════════════════════════════════════


def _extract_external_semantics(func_node, known_libraries):
    """Extract SQL operations and library calls."""
    sql_ops = classify_sql_operations(func_node)
    lib_calls = detect_library_calls(func_node, known_libraries)
    return sql_ops, lib_calls


def extract_semantics_for_node(
    func_node: ast.AST,
    node_id: str,
    func_name: str,
    file_path: str,
    known_libraries: Optional[Set[str]] = None,
) -> Graph2Node:
    """Extract all semantic information for a single function node."""
    actions = extract_actions(func_node, func_name)
    guards = extract_guards(func_node)
    side_effects = extract_side_effects(func_node)
    data_flow = extract_data_flow(func_node)
    domain_tags = infer_domain_tags(func_name, file_path)
    sql_ops, lib_calls = _extract_external_semantics(func_node, known_libraries)

    g2node = Graph2Node(
        id=node_id,
        actions=actions,
        guards=guards,
        side_effects=side_effects,
        data_flow=data_flow,
        domain_tags=domain_tags,
        sql_operations=sql_ops,
        library_calls=lib_calls,
        confidence=_compute_confidence(actions, guards, side_effects, data_flow),
    )
    g2node.behavior_hash = g2node.compute_behavior_hash()
    return g2node


def _compute_confidence(
    actions: List[SemanticAction],
    guards: List[Guard],
    side_effects: List[SideEffect],
    data_flow: Optional[DataFlowSummary],
) -> float:
    """Compute extraction confidence based on how much was found."""
    score = 0.0
    if actions:
        non_unknown = [a for a in actions if a.action_type != ActionType.UNKNOWN]
        score += 0.3 if non_unknown else 0.1
    if guards:
        score += 0.2
    if side_effects:
        score += 0.2
    if data_flow and (data_flow.inputs or data_flow.outputs):
        score += 0.3
    return min(score, 1.0)


# ═══════════════════════════════════════════════════════════════════════
# R-017 — Full File Semantic Extraction
# ═══════════════════════════════════════════════════════════════════════


def extract_semantics_for_file(
    source: str,
    file_path: str,
    node_prefix: str = "",
    known_libraries: Optional[Set[str]] = None,
) -> List[Graph2Node]:
    """Extract Graph2 nodes for all functions/methods in a source file."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        logger.warning("Syntax error in %s — skipping semantic extraction", file_path)
        return []

    nodes: List[Graph2Node] = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Build node ID matching Graph0 convention
            func_name = node.name
            node_id = f"{file_path}::{func_name}" if not node_prefix else f"{node_prefix}::{func_name}"

            g2node = extract_semantics_for_node(
                node, node_id, func_name, file_path, known_libraries,
            )
            nodes.append(g2node)

        elif isinstance(node, ast.ClassDef):
            class_name = node.name
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    method_name = item.name
                    node_id = f"{file_path}::{class_name}::{method_name}"
                    g2node = extract_semantics_for_node(
                        item, node_id, method_name, file_path, known_libraries,
                    )
                    nodes.append(g2node)

    return nodes


# ═══════════════════════════════════════════════════════════════════════
# R-018 — Incremental Semantic Extraction
# ═══════════════════════════════════════════════════════════════════════


def update_graph2_incremental(
    graph2: Graph2,
    changed_node_ids: Set[str],
    source_map: Dict[str, str],
    file_node_map: Dict[str, List[str]],
    known_libraries: Optional[Set[str]] = None,
) -> Graph2:
    """Incrementally update Graph2 for changed nodes only.

    Args:
        graph2: Existing Graph2 to update.
        changed_node_ids: Set of Graph0 node IDs that changed.
        source_map: Mapping {file_path: source_code} for files with changes.
        file_node_map: Mapping {file_path: [node_ids_in_file]}.
        known_libraries: Optional override for library detection.

    Returns:
        Updated Graph2.
    """
    t0 = time.perf_counter()
    updated = 0

    # Remove old entries for changed nodes
    for nid in changed_node_ids:
        graph2.remove_node(nid)

    # Re-extract from source for files containing changed nodes
    processed_files: Set[str] = set()
    for file_path, source in source_map.items():
        if file_path in processed_files:
            continue
        # Check if any changed node is in this file
        file_nodes = set(file_node_map.get(file_path, []))
        if not file_nodes & changed_node_ids:
            continue

        processed_files.add(file_path)
        new_nodes = extract_semantics_for_file(source, file_path, known_libraries=known_libraries)

        for g2node in new_nodes:
            if g2node.id in changed_node_ids:
                graph2.upsert_node(g2node)
                updated += 1

    elapsed = time.perf_counter() - t0
    logger.info(
        "Incremental semantic extraction: %d nodes updated in %.2fs",
        updated, elapsed,
    )
    return graph2


# ═══════════════════════════════════════════════════════════════════════
# R-019 — Build Integration
# ═══════════════════════════════════════════════════════════════════════


def build_graph2(
    graph0: Any,
    project_root: Path,
    known_libraries: Optional[Set[str]] = None,
) -> Graph2:
    """Full Graph_2 build from Graph_0 nodes and source files.

    Reads source files referenced by Graph_0 nodes and extracts
    semantic information for each function/method.
    """
    t0 = time.perf_counter()
    graph2 = Graph2()

    # Group nodes by file
    file_nodes: Dict[str, List[Any]] = {}
    for node in graph0.nodes:
        file_nodes.setdefault(node.file, []).append(node)

    for file_path, nodes in file_nodes.items():
        abs_path = project_root / file_path
        if not abs_path.exists() or not abs_path.suffix == ".py":
            continue

        try:
            source = abs_path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (OSError, SyntaxError):
            continue

        # Build map of line→AST node for matching
        func_map: Dict[int, ast.AST] = {}
        for ast_node in ast.walk(tree):
            if isinstance(ast_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_map[getattr(ast_node, "lineno", -1)] = ast_node

        for g0node in nodes:
            if g0node.type not in ("function", "method"):
                continue

            # Find matching AST node by line number
            ast_node = func_map.get(g0node.line)
            if ast_node is None:
                continue

            func_name = ast_node.name if hasattr(ast_node, "name") else g0node.id.split("::")[-1]
            g2node = extract_semantics_for_node(
                ast_node, g0node.id, func_name, file_path, known_libraries,
            )
            graph2.upsert_node(g2node)

    elapsed = time.perf_counter() - t0
    logger.info(
        "Built Graph_2: %d semantic nodes in %.2fs",
        len(graph2.nodes), elapsed,
    )
    return graph2


# ═══════════════════════════════════════════════════════════════════════
# R-020 — Behavior Hash
# ═══════════════════════════════════════════════════════════════════════


def detect_behavior_changes(
    old_graph2: Graph2, new_graph2: Graph2,
) -> Dict[str, Tuple[Optional[str], Optional[str]]]:
    """Compare behavior hashes between old and new Graph_2.

    Returns {node_id: (old_hash, new_hash)} for changed nodes.
    """
    changes: Dict[str, Tuple[Optional[str], Optional[str]]] = {}

    old_ids = {n.id for n in old_graph2.nodes}
    new_ids = {n.id for n in new_graph2.nodes}

    # Added nodes
    for nid in new_ids - old_ids:
        new_node = new_graph2.get_node(nid)
        changes[nid] = (None, new_node.behavior_hash if new_node else None)

    # Removed nodes
    for nid in old_ids - new_ids:
        old_node = old_graph2.get_node(nid)
        changes[nid] = (old_node.behavior_hash if old_node else None, None)

    # Changed behavior
    for nid in old_ids & new_ids:
        old_node = old_graph2.get_node(nid)
        new_node = new_graph2.get_node(nid)
        if old_node and new_node and old_node.behavior_hash != new_node.behavior_hash:
            changes[nid] = (old_node.behavior_hash, new_node.behavior_hash)

    return changes


# ═══════════════════════════════════════════════════════════════════════
# R-021 — Graph2 Storage
# ═══════════════════════════════════════════════════════════════════════


def save_graph2(graph2: Graph2, project_root: Path) -> None:
    """Save Graph_2 to .codegraph/graphs/graph2.json."""
    from codegraph.storage import ensure_codegraph_dir
    ensure_codegraph_dir(project_root)

    graphs_dir = project_root / ".codegraph" / "graphs"
    graphs_dir.mkdir(parents=True, exist_ok=True)
    out_path = graphs_dir / "graph2.json"
    out_path.write_text(graph2.to_json(compact=True), encoding="utf-8")
    logger.info("Saved Graph_2 with %d nodes", len(graph2.nodes))


def load_graph2(project_root: Path) -> Graph2:
    """Load Graph_2 from .codegraph/graphs/graph2.json."""
    g2_path = project_root / ".codegraph" / "graphs" / "graph2.json"
    if not g2_path.exists():
        return Graph2()
    try:
        text = g2_path.read_text(encoding="utf-8")
        return Graph2.from_json(text)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load Graph_2: %s — starting fresh", exc)
        return Graph2()


# ═══════════════════════════════════════════════════════════════════════
# Utility Helpers
# ═══════════════════════════════════════════════════════════════════════


def _split_name(name: str) -> List[str]:
    """Split function name into verb + object parts."""
    # Strip leading underscores
    clean = name.lstrip("_")
    if not clean:
        return [name]

    # Split camelCase
    if any(c.isupper() for c in clean[1:]):
        parts = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\d|\b)", clean)
        return [p.lower() for p in parts] if parts else [clean.lower()]

    # Split snake_case
    return clean.split("_")


def _get_call_name(node: ast.Call) -> str:
    """Extract the function name from a Call node."""
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def _get_attribute_root(node: ast.Attribute) -> str:
    """Get the root name of an attribute chain (a.b.c → a)."""
    current: ast.expr = node
    while isinstance(current, ast.Attribute):
        current = current.value
    if isinstance(current, ast.Name):
        return current.id
    return ""


def _unparse_safe(node: Optional[ast.AST]) -> str:
    """Safely unparse an AST node."""
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:
        return ""


def _get_raise_type(raise_node: ast.Raise) -> str:
    """Extract the exception type name from a Raise node."""
    if raise_node.exc is None:
        return "Exception"
    if isinstance(raise_node.exc, ast.Call):
        return _unparse_safe(raise_node.exc.func)
    return _unparse_safe(raise_node.exc)


# ═══════════════════════════════════════════════════════════════════════
# R-016 supplement — Semantic Rule Evaluation integration
# ═══════════════════════════════════════════════════════════════════════


def evaluate_semantic_rules_impl(
    graph2: Graph2,
    graph0: Any,
    workflow: Any,
) -> List[Dict[str, Any]]:
    """Evaluate semantic-aware rules for policy violations.

    Returns list of violation dicts with details.
    """
    violations: List[Dict[str, Any]] = []

    for node in graph2.nodes:
        # Rule: DB-write functions without guards
        has_db_write = any(
            se.effect_type == SideEffectType.DATABASE_WRITE
            for se in node.side_effects
        )
        if has_db_write and not node.guards:
            violations.append({
                "rule": "db-write-no-guard",
                "node_id": node.id,
                "severity": "warning",
                "message": f"Node {node.id} performs database writes without guard clauses",
            })

        # Rule: Network calls without error handling
        has_network = any(
            se.effect_type == SideEffectType.NETWORK_CALL
            for se in node.side_effects
        )
        if has_network:
            # Check if there's any try/except in the function (heuristic: guards with 'raises')
            has_error_handling = any(g.raises for g in node.guards)
            if not has_error_handling:
                violations.append({
                    "rule": "network-no-error-handling",
                    "node_id": node.id,
                    "severity": "info",
                    "message": f"Node {node.id} makes network calls — consider adding error handling",
                })

        # Rule: File write + no logging
        has_file_write = any(
            se.effect_type == SideEffectType.FILE_WRITE
            for se in node.side_effects
        )
        has_logging = any(
            se.effect_type == SideEffectType.LOGGING
            for se in node.side_effects
        )
        if has_file_write and not has_logging:
            violations.append({
                "rule": "file-write-no-logging",
                "node_id": node.id,
                "severity": "info",
                "message": f"Node {node.id} writes files without logging",
            })

    return violations
