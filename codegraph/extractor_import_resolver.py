from __future__ import annotations

import ast
from typing import Any, List, Optional, Set

from codegraph.extraction_types import ImportInfo


def extract_imports(tree: ast.Module, file_path: str = "") -> List[ImportInfo]:
    imports: List[ImportInfo] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(
                    ImportInfo(
                        module=alias.name,
                        names=[alias.name.split(".")[-1]],
                        alias=alias.asname,
                        is_relative=False,
                        level=0,
                        line=node.lineno,
                    )
                )
        elif isinstance(node, ast.ImportFrom):
            module_name = node.module or ""
            names = [a.name for a in node.names] if node.names else []
            imports.append(
                ImportInfo(
                    module=module_name,
                    names=names,
                    alias=node.names[0].asname if node.names and len(node.names) == 1 else None,
                    is_relative=node.level > 0,
                    level=node.level or 0,
                    line=node.lineno,
                )
            )

    return imports


_AMBIGUOUS_METHOD_NAMES: frozenset[str] = frozenset({
    "append", "extend", "insert", "remove", "pop", "clear",
    "get", "keys", "values", "items", "update", "setdefault",
    "add", "discard", "put",
    "format", "join", "split", "strip", "replace", "startswith", "endswith",
    "lower", "upper", "encode", "decode",
    "to_dict", "from_dict", "to_json", "from_json",
    "copy", "sort", "reverse", "count", "index",
    "info", "debug", "warning", "error", "critical",
    "write", "read", "close", "flush", "seek",
    "resolve", "exists", "save", "load", "apply",
    "validate", "run", "execute", "start", "stop",
})


def resolve_call_target(
    call: Any,
    imports: List[ImportInfo],
    current_file: str,
    all_node_ids: Set[str],
    scope: Optional[Any] = None,
    current_class: Optional[str] = None,
) -> Optional[str]:
    name = call.raw_name

    if call.is_method_call and call.object_name == "self" and current_class:
        candidate = f"{current_file}::{current_class}::{name.split('.')[-1]}"
        if candidate in all_node_ids:
            return candidate

    if call.is_method_call and call.object_name and call.object_name.startswith("super("):
        return None

    if scope is not None and hasattr(scope, "resolve"):
        resolved = scope.resolve(name)
        if resolved and resolved in all_node_ids:
            return resolved

    if not call.is_method_call:
        candidate = f"{current_file}::{name}"
        if candidate in all_node_ids:
            return candidate

    for imp in imports:
        if name in imp.names:
            module_path = imp.module.replace(".", "/")
            candidate = f"{module_path}.py::{name}"
            if candidate in all_node_ids:
                return candidate
            candidate = f"{module_path}::{name}"
            if candidate in all_node_ids:
                return candidate
        if imp.alias and imp.alias == name.split(".")[0]:
            if "." in name:
                func_part = name.split(".", 1)[1]
                module_path = imp.module.replace(".", "/")
                candidate = f"{module_path}.py::{func_part}"
                if candidate in all_node_ids:
                    return candidate

    if call.is_method_call and "." in name:
        method_name = name.split(".")[-1]
        if method_name not in _AMBIGUOUS_METHOD_NAMES:
            for nid in sorted(all_node_ids):
                if nid.endswith(f"::{method_name}"):
                    return nid

    return None
