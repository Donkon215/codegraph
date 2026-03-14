"""codegraph.extractor — AST extraction engine (Graph_0).

Covers tasks C-001 through C-035:
  C-001  Python AST parser entry point
  C-002  Function node extractor
  C-003  Class node extractor
  C-004  Method node extractor
  C-005  Nested function extraction
  C-006  Nested class extraction
  C-007  Module node extraction
  C-008  Full file extraction pipeline
  C-009  Full project extraction pipeline
  C-010  Body hash — whitespace invariance (via ast.dump)
  C-011  Body hash — comment invariance (Python AST strips comments)
  C-012  Body hash — logic change detection (validated by tests)
  C-013  Decorator extraction
  C-014  Parameter extraction
  C-015  Return type extraction
  C-016  Import statement extraction
  C-017  Call site extraction for static analysis
  C-018  Call target resolution
  C-019  Dynamic call detection
  C-020  Incremental file extraction for delta
  C-021  Extraction caching
  C-022  Error handling and recovery
  C-023  Class hierarchy extraction
  C-024  Global variable / constant extraction
  C-025  Extraction performance optimization (parallel)
  C-026  Scope-aware name resolution
  C-027  __init__.py handling
  C-028  Type stub (.pyi) handling
  C-029  Extraction report generator
  C-030  Graph_0 persistence (save/load)
  C-031  Graph_0 comparison for delta
  C-032  Conditional code extraction
  C-033  Async-specific extraction
  C-034  Extraction determinism guarantee
  C-035  Type annotation extraction for nodes
"""

from __future__ import annotations

import ast
import concurrent.futures
import copy
import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from codegraph.config import CodegraphConfig, load_config
from codegraph.constants import (
    BODY_HASH_LENGTH,
    CODEGRAPH_DIR,
    CURRENT_FORMAT_VERSION,
    GRAPHS_DIR,
)
from codegraph.extraction_types import FileExtractionResult, ImportInfo
from codegraph.logging_config import get_logger
from codegraph.models.graph0 import CollisionResolver, Graph0, Graph0Node
from codegraph.storage import (
    atomic_write,
    ensure_codegraph_dir,
    increment_graph_version,
    resolve_path,
)
from codegraph.utils.file_discovery import discover_source_files
from codegraph.utils.formatting import iso_now
from codegraph.utils.hashing import hash_file
from codegraph.utils.ids import normalize_path
from codegraph.utils.progress import ProgressReporter

logger = get_logger("extractor")


# ═══════════════════════════════════════════════════════════════════════
# Helper data structures
# ═══════════════════════════════════════════════════════════════════════

# ImportInfo and FileExtractionResult are defined in codegraph.extraction_types
# and re-exported here for backward compatibility.


@dataclass
class CallSite:
    """A function/method call detected in source.  (C-017)"""

    raw_name: str
    line: int
    is_method_call: bool = False
    object_name: Optional[str] = None
    is_dynamic: bool = False


@dataclass
class DynamicCall:
    """An unresolvable dynamic call.  (C-019)"""

    pattern: str
    line: int
    scope: str = ""


@dataclass
class GlobalDef:
    """A module-level variable/constant.  (C-024)"""

    name: str
    line: int
    type_annotation: Optional[str] = None
    is_constant: bool = False


@dataclass
class ClassInfo:
    """Class hierarchy metadata.  (C-023)"""

    name: str
    bases: List[str] = field(default_factory=list)
    file: str = ""


@dataclass
class ExtractionWarning:
    """A warning produced during extraction."""

    file: str
    line: Optional[int] = None
    message: str = ""


@dataclass
class ExtractionReport:
    """Summary report after extraction.  (C-029)"""

    files_processed: int = 0
    files_skipped: int = 0
    nodes_extracted: Dict[str, int] = field(default_factory=dict)
    collisions: List[str] = field(default_factory=list)
    warnings: List[ExtractionWarning] = field(default_factory=list)
    duration_seconds: float = 0.0
    language_counts: Dict[str, int] = field(default_factory=dict)  # e.g. {"Python": 120, "TypeScript": 45}

    @property
    def total_nodes(self) -> int:
        return sum(self.nodes_extracted.values())

    def summary(self) -> str:
        lines = [
            f"Files processed: {self.files_processed}",
            f"Files skipped:   {self.files_skipped}",
        ]
        
        # Language coverage
        if self.language_counts:
            lines.append("\nLanguages detected:")
            for lang, count in sorted(self.language_counts.items(), key=lambda x: -x[1]):
                lines.append(f"  {lang}: {count} files")
        
        lines.append("\nNodes extracted:")
        for ntype, count in sorted(self.nodes_extracted.items()):
            lines.append(f"  {ntype}: {count}")
        lines.append(f"\nTotal nodes:     {self.total_nodes}")
        if self.collisions:
            lines.append(f"Collisions:      {len(self.collisions)}")
        if self.warnings:
            lines.append(f"Warnings:        {len(self.warnings)}")
        lines.append(f"Duration:        {self.duration_seconds:.2f}s")
        return "\n".join(lines)


@dataclass
class GraphDiff:
    """Result of comparing two Graph_0 instances.  (C-031)"""

    nodes_added: List[str] = field(default_factory=list)
    nodes_removed: List[str] = field(default_factory=list)
    nodes_modified: List[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.nodes_added and not self.nodes_removed and not self.nodes_modified


# ═══════════════════════════════════════════════════════════════════════
# C-010 / C-011 / C-012 — Body hash computation (AST-based)
# ═══════════════════════════════════════════════════════════════════════


class _DocstringStripper(ast.NodeTransformer):
    """Remove docstring nodes from an AST for hashing.

    Comments are already stripped by ``ast.parse()``.
    Using ``ast.dump(include_attributes=False)`` ignores line numbers / whitespace.
    Together these give whitespace-invariant, comment-invariant, docstring-invariant
    body hashes that still detect any logic change (C-010, C-011, C-012).
    """

    def _strip(self, node: ast.AST) -> ast.AST:
        if (
            isinstance(
                node,
                (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module),
            )
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            node.body = node.body[1:] or [ast.Pass()]
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        self._strip(node)
        self.generic_visit(node)
        return node

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
        self._strip(node)
        self.generic_visit(node)
        return node

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST:
        self._strip(node)
        self.generic_visit(node)
        return node

    def visit_Module(self, node: ast.Module) -> ast.AST:
        self._strip(node)
        self.generic_visit(node)
        return node


def _body_hash_node(node: ast.AST) -> str:
    """Compute a deterministic hash for an AST node, ignoring whitespace/comments/docstrings."""
    stripped = _DocstringStripper().visit(copy.deepcopy(node))
    canonical = ast.dump(stripped, annotate_fields=True, include_attributes=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:BODY_HASH_LENGTH]


def _body_hash_source(source: str) -> str:
    """Compute body hash from raw source (for module-level hashing)."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return hashlib.sha256(source.encode("utf-8")).hexdigest()[:BODY_HASH_LENGTH]
    return _body_hash_node(tree)


# ═══════════════════════════════════════════════════════════════════════
# C-035 — Type annotation extraction helpers
# ═══════════════════════════════════════════════════════════════════════


def _annotation_to_str(node: Optional[ast.AST]) -> Optional[str]:
    """Convert an annotation AST node to a human-readable string."""
    if node is None:
        return None
    return ast.unparse(node)


# ═══════════════════════════════════════════════════════════════════════
# C-013 — Decorator extraction
# ═══════════════════════════════════════════════════════════════════════


def _extract_decorators(
    node: Union[ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef],
) -> List[str]:
    """Return a list of decorator name strings for a function/class AST node."""
    return [ast.unparse(dec) for dec in node.decorator_list]


# ═══════════════════════════════════════════════════════════════════════
# C-014 — Parameter extraction
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class ParamInfo:
    """Extracted parameter metadata."""

    name: str
    annotation: Optional[str] = None
    has_default: bool = False
    kind: str = "positional"  # positional | keyword | var_positional | var_keyword


def _extract_params(
    node: Union[ast.FunctionDef, ast.AsyncFunctionDef],
) -> List[ParamInfo]:
    """Extract parameter info from a function/async-function AST node."""
    params: List[ParamInfo] = []
    args = node.args

    num_defaults = len(args.defaults)
    num_pos = len(args.posonlyargs) + len(args.args)

    for i, arg in enumerate(args.posonlyargs + args.args):
        has_default = i >= (num_pos - num_defaults)
        params.append(
            ParamInfo(
                name=arg.arg,
                annotation=_annotation_to_str(arg.annotation),
                has_default=has_default,
                kind="positional",
            )
        )

    if args.vararg:
        params.append(
            ParamInfo(
                name=f"*{args.vararg.arg}",
                annotation=_annotation_to_str(args.vararg.annotation),
                kind="var_positional",
            )
        )

    for i, arg in enumerate(args.kwonlyargs):
        has_default = args.kw_defaults[i] is not None
        params.append(
            ParamInfo(
                name=arg.arg,
                annotation=_annotation_to_str(arg.annotation),
                has_default=has_default,
                kind="keyword",
            )
        )

    if args.kwarg:
        params.append(
            ParamInfo(
                name=f"**{args.kwarg.arg}",
                annotation=_annotation_to_str(args.kwarg.annotation),
                kind="var_keyword",
            )
        )

    return params


# ═══════════════════════════════════════════════════════════════════════
# C-015 — Return type extraction
# ═══════════════════════════════════════════════════════════════════════


def _extract_return_type(
    node: Union[ast.FunctionDef, ast.AsyncFunctionDef],
) -> Optional[str]:
    """Return the return-type annotation as a string, or None."""
    return _annotation_to_str(node.returns)


# ═══════════════════════════════════════════════════════════════════════
# C-001 — Parse file into AST
# ═══════════════════════════════════════════════════════════════════════


def parse_file(file_path: Path) -> Optional[ast.Module]:
    """Read a Python source file and return its AST, or *None* on error."""
    try:
        source = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        logger.warning("Skipping %s: encoding error — %s", file_path, exc)
        return None
    except OSError as exc:
        logger.warning("Skipping %s: read error — %s", file_path, exc)
        return None

    try:
        return ast.parse(source, filename=str(file_path))
    except SyntaxError as exc:
        logger.warning(
            "Skipping %s: syntax error at line %s — %s",
            file_path,
            exc.lineno,
            exc.msg,
        )
        return None


# ═══════════════════════════════════════════════════════════════════════
# C-016 — Import statement extraction
# ═══════════════════════════════════════════════════════════════════════


def extract_imports(tree: ast.Module, file_path: str = "") -> List[ImportInfo]:
    """Extract all import statements from a module AST."""
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


# ═══════════════════════════════════════════════════════════════════════
# C-024 — Global variable / constant extraction
# ═══════════════════════════════════════════════════════════════════════


def extract_globals(tree: ast.Module) -> List[GlobalDef]:
    """Extract module-level variable assignments."""
    result: List[GlobalDef] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    result.append(
                        GlobalDef(
                            name=target.id,
                            line=node.lineno,
                            is_constant=target.id.isupper(),
                        )
                    )
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            result.append(
                GlobalDef(
                    name=node.target.id,
                    line=node.lineno,
                    type_annotation=_annotation_to_str(node.annotation),
                    is_constant=node.target.id.isupper(),
                )
            )
    return result


# ═══════════════════════════════════════════════════════════════════════
# C-023 — Class hierarchy extraction
# ═══════════════════════════════════════════════════════════════════════


def _extract_bases(class_node: ast.ClassDef) -> List[str]:
    """Return base class names as strings."""
    return [ast.unparse(b) for b in class_node.bases]


# ═══════════════════════════════════════════════════════════════════════
# C-017 / C-019 — Call site and dynamic call extraction
# ═══════════════════════════════════════════════════════════════════════


def extract_call_sites(
    func_node: Union[ast.FunctionDef, ast.AsyncFunctionDef],
) -> List[CallSite]:
    """Extract all function/method call sites from a function body.

    Also detects ``await`` expressions as call sites (C-033).
    """
    calls: List[CallSite] = []

    for node in ast.walk(func_node):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                calls.append(CallSite(raw_name=func.id, line=node.lineno))
            elif isinstance(func, ast.Attribute):
                obj = _unparse_safe(func.value)
                calls.append(
                    CallSite(
                        raw_name=f"{obj}.{func.attr}" if obj else func.attr,
                        line=node.lineno,
                        is_method_call=True,
                        object_name=obj,
                    )
                )
            else:
                calls.append(
                    CallSite(
                        raw_name=_unparse_safe(func) or "<dynamic>",
                        line=node.lineno,
                        is_dynamic=True,
                    )
                )

    return calls


def detect_dynamic_calls(
    func_node: Union[ast.FunctionDef, ast.AsyncFunctionDef],
    scope: str = "",
) -> List[DynamicCall]:
    """Detect dynamic dispatch patterns that cannot be resolved statically.  (C-019)"""
    dynamics: List[DynamicCall] = []

    for node in ast.walk(func_node):
        if not isinstance(node, ast.Call):
            continue

        func = node.func

        # Pattern: getattr(obj, name)()
        if (
            isinstance(func, ast.Call)
            and isinstance(func.func, ast.Name)
            and func.func.id == "getattr"
        ):
            dynamics.append(DynamicCall(pattern="getattr", line=node.lineno, scope=scope))
            continue

        # Pattern: dict_lookup[key]()  — Subscript call
        if isinstance(func, ast.Subscript):
            dynamics.append(DynamicCall(pattern="dict_dispatch", line=node.lineno, scope=scope))
            continue

        # Pattern: any non-Name/non-Attribute call
        if not isinstance(func, (ast.Name, ast.Attribute)):
            dynamics.append(DynamicCall(pattern="indirect_call", line=node.lineno, scope=scope))

    return dynamics


def _unparse_safe(node: ast.AST) -> Optional[str]:
    """Return ``ast.unparse(node)`` or *None* on failure."""
    try:
        return ast.unparse(node)
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════
# C-026 — Scope-aware name resolution
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class _Scope:
    """A single scope level in the scope tree."""

    kind: str  # "module", "class", "function"
    name: str
    bindings: Dict[str, str] = field(default_factory=dict)  # local_name → node_id


class ScopeTree:
    """Tracks variable bindings across nested scopes (LEGB).  (C-026)"""

    def __init__(self) -> None:
        self._stack: List[_Scope] = []

    def push(self, kind: str, name: str) -> None:
        self._stack.append(_Scope(kind=kind, name=name))

    def pop(self) -> None:
        if self._stack:
            self._stack.pop()

    def bind(self, local_name: str, node_id: str) -> None:
        """Bind *local_name* to *node_id* in the current scope."""
        if self._stack:
            self._stack[-1].bindings[local_name] = node_id

    def resolve(self, name: str) -> Optional[str]:
        """Resolve *name* using LEGB lookup, returning a node ID or None."""
        for scope in reversed(self._stack):
            if name in scope.bindings:
                return scope.bindings[name]
        return None


# ═══════════════════════════════════════════════════════════════════════
# C-018 — Call target resolution
# ═══════════════════════════════════════════════════════════════════════


def resolve_call_target(
    call: CallSite,
    imports: List[ImportInfo],
    current_file: str,
    all_node_ids: Set[str],
    scope: Optional[ScopeTree] = None,
    current_class: Optional[str] = None,
) -> Optional[str]:
    """Attempt to resolve a call site to a Graph_0 node ID.

    Returns *None* if the target cannot be resolved statically.
    """
    name = call.raw_name

    # self.method() → resolve to current_class::method
    if call.is_method_call and call.object_name == "self" and current_class:
        candidate = f"{current_file}::{current_class}::{name.split('.')[-1]}"
        if candidate in all_node_ids:
            return candidate

    # super().method() — needs class hierarchy, bail
    if call.is_method_call and call.object_name and call.object_name.startswith("super("):
        return None

    # Scope tree lookup
    if scope is not None:
        resolved = scope.resolve(name)
        if resolved and resolved in all_node_ids:
            return resolved

    # Simple name → same-file function
    if not call.is_method_call:
        candidate = f"{current_file}::{name}"
        if candidate in all_node_ids:
            return candidate

    # Import-based resolution
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

    # Method call: obj.method() — fuzzy match
    # Skip common builtin method names that produce false positive resolutions
    if call.is_method_call and "." in name:
        method_name = name.split(".")[-1]
        if method_name not in _AMBIGUOUS_METHOD_NAMES:
            for nid in sorted(all_node_ids):
                if nid.endswith(f"::{method_name}"):
                    return nid

    return None


# Names that are common on builtins/stdlib types.  Fuzzy-matching these
# to the first class that defines them creates massive false-positive
# fan-in (e.g. every ``list.append()`` resolves to TaskHistory::append).
_AMBIGUOUS_METHOD_NAMES: frozenset[str] = frozenset({
    # list / set / dict builtins
    "append", "extend", "insert", "remove", "pop", "clear",
    "get", "keys", "values", "items", "update", "setdefault",
    "add", "discard", "put",
    # str builtins
    "format", "join", "split", "strip", "replace", "startswith", "endswith",
    "lower", "upper", "encode", "decode",
    # common dunder-like / generic names
    "to_dict", "from_dict", "to_json", "from_json",
    "copy", "sort", "reverse", "count", "index",
    # logging / formatting
    "info", "debug", "warning", "error", "critical",
    "write", "read", "close", "flush", "seek",
    # pathlib / common object methods
    "resolve", "exists", "save", "load", "apply",
    "validate", "run", "execute", "start", "stop",
})


# ═══════════════════════════════════════════════════════════════════════
# C-002 through C-007, C-032, C-033 — Node extractors
# ═══════════════════════════════════════════════════════════════════════


def _is_method_context(parent_chain: List[str], body: List[ast.stmt]) -> bool:
    """Return True if the body belongs to a class (making functions methods)."""
    if not parent_chain:
        return False
    for stmt in body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if stmt.args.args and stmt.args.args[0].arg in ("self", "cls"):
                return True
    return False


def _extract_nodes_recursive(
    body: List[ast.stmt],
    file_rel: str,
    parent_chain: List[str],
    nodes: List[Graph0Node],
    class_infos: List[ClassInfo],
    is_class_body: bool = False,
) -> None:
    """Recursively extract nodes from a list of AST statements.

    Handles functions, classes, nested functions, nested classes, methods,
    conditional blocks, and try/except blocks (C-002–C-006, C-032, C-033).
    """
    for stmt in body:
        # ── Functions (C-002) and async functions (C-033) ──────────
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            chain = parent_chain + [stmt.name]
            node_id = f"{file_rel}::{'::'.join(chain)}"
            node_type = "method" if is_class_body else "function"
            body_hash = _body_hash_node(stmt)

            decorators = _extract_decorators(stmt)
            params = _extract_params(stmt)
            return_type = _extract_return_type(stmt)
            is_async = isinstance(stmt, ast.AsyncFunctionDef)

            node = Graph0Node(
                id=node_id,
                body_hash=body_hash,
                file=file_rel,
                type=node_type,
                line=stmt.lineno,
            )
            node._metadata = {  # type: ignore[attr-defined]
                "decorators": decorators,
                "params": [
                    {"name": p.name, "annotation": p.annotation, "has_default": p.has_default, "kind": p.kind}
                    for p in params
                ],
                "return_type": return_type,
                "is_async": is_async,
            }
            nodes.append(node)

            # Recurse into nested functions/classes (C-005)
            _extract_nodes_recursive(
                stmt.body, file_rel, chain, nodes, class_infos, is_class_body=False
            )

        # ── Classes (C-003, C-006) ────────────────────────────────
        elif isinstance(stmt, ast.ClassDef):
            chain = parent_chain + [stmt.name]
            node_id = f"{file_rel}::{'::'.join(chain)}"
            body_hash = _body_hash_node(stmt)

            bases = _extract_bases(stmt)
            decorators = _extract_decorators(stmt)

            class_infos.append(ClassInfo(name=stmt.name, bases=bases, file=file_rel))

            node = Graph0Node(
                id=node_id,
                body_hash=body_hash,
                file=file_rel,
                type="class",
                line=stmt.lineno,
            )
            node._metadata = {  # type: ignore[attr-defined]
                "decorators": decorators,
                "bases": bases,
            }
            nodes.append(node)

            # Extract methods and nested classes (C-004, C-006)
            _extract_nodes_recursive(
                stmt.body, file_rel, chain, nodes, class_infos, is_class_body=True
            )

        # ── Conditional blocks (C-032) ────────────────────────────
        elif isinstance(stmt, ast.If):
            _extract_nodes_recursive(
                stmt.body, file_rel, parent_chain, nodes, class_infos, is_class_body
            )
            _extract_nodes_recursive(
                stmt.orelse, file_rel, parent_chain, nodes, class_infos, is_class_body
            )
        elif isinstance(stmt, ast.Try):
            _extract_nodes_recursive(
                stmt.body, file_rel, parent_chain, nodes, class_infos, is_class_body
            )
            for handler in stmt.handlers:
                _extract_nodes_recursive(
                    handler.body, file_rel, parent_chain, nodes, class_infos, is_class_body
                )
            _extract_nodes_recursive(
                stmt.orelse, file_rel, parent_chain, nodes, class_infos, is_class_body
            )
            _extract_nodes_recursive(
                stmt.finalbody, file_rel, parent_chain, nodes, class_infos, is_class_body
            )
        elif isinstance(stmt, ast.With):
            _extract_nodes_recursive(
                stmt.body, file_rel, parent_chain, nodes, class_infos, is_class_body
            )


# ═══════════════════════════════════════════════════════════════════════
# C-007 — Module node extraction  (C-027 — __init__.py handling)
# ═══════════════════════════════════════════════════════════════════════


def _extract_module_node(
    file_path: Path,
    project_root: Path,
    source: str,
) -> Graph0Node:
    """Extract a module-level Graph0Node."""
    rel = normalize_path(file_path, project_root)

    # __init__.py → package ID (C-027)
    if file_path.name == "__init__.py":
        module_id = rel.rsplit("/", 1)[0] if "/" in rel else ""
    else:
        module_id = rel.rsplit(".", 1)[0] if "." in rel else rel

    body_hash = _body_hash_source(source)

    return Graph0Node(
        id=module_id,
        body_hash=body_hash,
        file=rel,
        type="module",
        line=1,
    )


# ═══════════════════════════════════════════════════════════════════════
# C-008 — Full file extraction pipeline
# ═══════════════════════════════════════════════════════════════════════


def extract_file(
    file_path: Path,
    project_root: Path,
    *,
    include_stubs: bool = False,
) -> FileExtractionResult:
    """Extract all Graph_0 nodes and metadata from a single file.  (C-008)"""
    result = FileExtractionResult()
    rel = normalize_path(file_path, project_root)

    # C-028 — skip .pyi by default
    if file_path.suffix == ".pyi" and not include_stubs:
        return result

    # C-001 — parse
    tree = parse_file(file_path)
    if tree is None:
        result.warnings.append(
            ExtractionWarning(file=rel, message="Could not parse file")
        )
        return result

    source = file_path.read_text(encoding="utf-8")

    # C-007 / C-027 — module node
    module_node = _extract_module_node(file_path, project_root, source)
    result.nodes.append(module_node)

    # C-016 — imports
    result.imports = extract_imports(tree, rel)

    # C-024 — globals
    result.globals = extract_globals(tree)

    # C-002 through C-006, C-032, C-033 — recursive node extraction
    _extract_nodes_recursive(
        tree.body,
        rel,
        [],
        result.nodes,
        result.class_infos,
    )

    # C-017, C-019 — call sites for functions/methods
    _extract_call_data(tree, rel, result)

    return result


def _extract_call_data(tree, rel, result):
    """Extract call sites and dynamic calls from AST."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            calls = extract_call_sites(node)
            dynamics = detect_dynamic_calls(node, scope=rel)
            result.call_sites[node.name] = calls
            result.dynamic_calls.extend(dynamics)


# ═══════════════════════════════════════════════════════════════════════
# C-021 — Extraction caching
# ═══════════════════════════════════════════════════════════════════════


class ExtractionCache:
    """Per-file extraction cache keyed by content hash.  (C-021)"""

    def __init__(self, project_root: Path) -> None:
        self._root = project_root
        self._cache_path = (
            project_root / CODEGRAPH_DIR / "cache" / "extraction_cache.json"
        )
        self._data: Dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if self._cache_path.exists():
            try:
                self._data = json.loads(
                    self._cache_path.read_text(encoding="utf-8")
                )
            except (json.JSONDecodeError, OSError):
                logger.warning("Extraction cache corrupted, ignoring")
                self._data = {}

    def save(self) -> None:
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(self._cache_path, self._data)

    def get(self, file_path: Path) -> Optional[List[Dict[str, Any]]]:
        """Return cached node dicts if the content hash matches."""
        key = normalize_path(file_path, self._root)
        entry = self._data.get(key)
        if entry is None:
            return None
        current_hash = hash_file(file_path)
        if entry.get("content_hash") != current_hash:
            return None
        return entry.get("nodes")

    def put(self, file_path: Path, content_hash: str, nodes: List[Graph0Node]) -> None:
        key = normalize_path(file_path, self._root)
        self._data[key] = {
            "content_hash": content_hash,
            "nodes": [n.to_dict() for n in nodes],
        }

    def invalidate(self, file_path: Path) -> None:
        key = normalize_path(file_path, self._root)
        self._data.pop(key, None)

    def clear(self) -> None:
        self._data.clear()


# ═══════════════════════════════════════════════════════════════════════
# C-022 — Error handling wrapper
# ═══════════════════════════════════════════════════════════════════════


def _safe_extract_file(
    file_path: Path,
    project_root: Path,
    include_stubs: bool = False,
) -> Tuple[FileExtractionResult, Optional[ExtractionWarning]]:
    """Extract a file, catching all exceptions.  (C-022)"""
    try:
        return extract_file(file_path, project_root, include_stubs=include_stubs), None
    except SyntaxError as exc:
        w = ExtractionWarning(
            file=str(file_path),
            line=getattr(exc, "lineno", None),
            message=f"SyntaxError: {exc.msg}" if hasattr(exc, "msg") else str(exc),
        )
        logger.warning("Skipping %s: %s", file_path, w.message)
        return FileExtractionResult(), w
    except UnicodeDecodeError as exc:
        w = ExtractionWarning(file=str(file_path), message=f"UnicodeDecodeError: {exc}")
        logger.warning("Skipping %s: encoding error", file_path)
        return FileExtractionResult(), w
    except Exception as exc:
        w = ExtractionWarning(file=str(file_path), message=f"Unexpected: {exc}")
        logger.warning("Skipping %s: %s", file_path, exc, exc_info=True)
        return FileExtractionResult(), w


# ═══════════════════════════════════════════════════════════════════════
# C-020 — Incremental file extraction for delta
# ═══════════════════════════════════════════════════════════════════════


def extract_files(
    file_paths: List[Path],
    project_root: Path,
) -> List[Graph0Node]:
    """Re-extract only the specified files, returning their nodes.  (C-020)"""
    all_nodes: List[Graph0Node] = []
    for fp in file_paths:
        result, _ = _safe_extract_file(fp, project_root)
        all_nodes.extend(result.nodes)
    return all_nodes


# ═══════════════════════════════════════════════════════════════════════
# C-025 — Parallel extraction helper
# ═══════════════════════════════════════════════════════════════════════


def _extract_file_worker(
    args: Tuple[Path, Path, bool],
) -> Tuple[FileExtractionResult, Optional[ExtractionWarning]]:
    """Worker function for parallel extraction.  Unpacks args tuple."""
    return _safe_extract_file(args[0], args[1], args[2])


# ═══════════════════════════════════════════════════════════════════════
# C-009 — Full project extraction pipeline
# ═══════════════════════════════════════════════════════════════════════

# ───────────────────────────────────────────────────────────────────────
# Extraction Helpers (reduce fan-out)
# ───────────────────────────────────────────────────────────────────────


def _initialize_extraction(
    project_root: Path,
    use_cache: bool,
    progress: bool,
    num_files: int,
) -> Tuple[Optional[ExtractionCache], Optional[ProgressReporter], CollisionResolver, ExtractionReport]:
    """Initialize extraction infrastructure: cache, progress, collision resolver, report.

    Returns
    -------
    (cache, prog, resolver, report)
    """
    report = ExtractionReport()

    # Cache setup (C-021)
    cache: Optional[ExtractionCache] = None
    if use_cache:
        try:
            cache = ExtractionCache(project_root)
        except Exception:
            logger.warning("Could not initialize extraction cache")

    # Progress (A-030)
    prog: Optional[ProgressReporter] = None
    if progress and num_files > 5:
        prog = ProgressReporter(total=num_files, label="Extracting")

    resolver = CollisionResolver()

    return cache, prog, resolver, report


def _run_file_extraction(
    source_files: List[Path],
    project_root: Path,
    include_stubs: bool,
    use_cache: bool,
    cache: Optional[ExtractionCache],
    prog: Optional[ProgressReporter],
    resolver: CollisionResolver,
    report: ExtractionReport,
    all_nodes: List[Graph0Node],
    node_counts: Dict[str, int],
) -> None:
    """Run file extraction in parallel or serial mode.

    Mutates: all_nodes, node_counts, report
    """
    from codegraph.extractors import get_extractor

    def _process_result(
        result: FileExtractionResult,
        warning: Optional[ExtractionWarning],
    ) -> None:
        if warning:
            report.warnings.append(warning)
            report.files_skipped += 1
        elif not result.nodes:
            report.files_skipped += 1
        else:
            report.files_processed += 1
            for n in result.nodes:
                ntype = n.type
                node_counts[ntype] = node_counts.get(ntype, 0) + 1
                resolved_id = resolver.resolve(n.id)
                if resolved_id != n.id:
                    n = Graph0Node(
                        id=resolved_id,
                        body_hash=n.body_hash,
                        file=n.file,
                        type=n.type,
                        line=n.line,
                        dependency_hash=n.dependency_hash,
                    )
                all_nodes.append(n)

    # C-025 â parallel extraction for large projects
    if len(source_files) > 50:
        workers = os.cpu_count() or 4
        tasks = [(fp, project_root, include_stubs) for fp in source_files]
        with concurrent.futures.ProcessPoolExecutor(max_workers=min(8, workers)) as pool:
            for fp, (result, warning) in zip(
                source_files, pool.map(_extract_file_worker, tasks)
            ):
                _process_result(result, warning)
                if prog:
                    prog.update()
    else:
        for fp in source_files:
            # Cache check (C-021)
            if cache is not None:
                cached = cache.get(fp)
                if cached is not None:
                    result = FileExtractionResult(
                        nodes=[Graph0Node.from_dict(d) for d in cached]
                    )
                    _process_result(result, None)
                    if prog:
                        prog.update()
                    continue

            # Multi-language: delegate to extractor registry for non-Python files
            _ext = get_extractor(fp)
            if _ext is not None and fp.suffix != ".py":
                try:
                    result = _ext.extract_all(fp)
                    warning = None
                except Exception as exc:
                    logger.warning("Skipping %s: %s", fp, exc)
                    result = FileExtractionResult()
                    warning = ExtractionWarning(
                        file=str(fp), message=str(exc)
                    )
            else:
                result, warning = _safe_extract_file(fp, project_root, include_stubs)
            _process_result(result, warning)

            # Populate cache
            if cache is not None and result.nodes:
                try:
                    content_hash = hash_file(fp)
                    cache.put(fp, content_hash, result.nodes)
                except Exception:
                    pass

            if prog:
                prog.update()


def _finalize_graph0(
    project_root: Path,
    report: ExtractionReport,
    source_files: List[Path],
    all_nodes: List[Graph0Node],
    node_counts: Dict[str, int],
    resolver: CollisionResolver,
    t0: float,
) -> Tuple[Graph0, float]:
    """Finalize and assemble Graph_0.

    Returns
    -------
    (graph0, duration_seconds)
    """
    # Collision report
    report.collisions = [f"{orig} â {res}" for orig, res in resolver.collisions]
    report.nodes_extracted = node_counts

    # C-034 â determinism: sort nodes by ID
    all_nodes.sort(key=lambda n: n.id)

    # Assemble Graph_0
    rel_files = sorted(normalize_path(f, project_root) for f in source_files)
    graph_version = increment_graph_version(project_root)

    graph0 = Graph0(
        graph_version=graph_version,
        format_version=CURRENT_FORMAT_VERSION,
        extracted_at=iso_now(),
        source_files=rel_files,
        nodes=all_nodes,
    )

    duration = round(time.monotonic() - t0, 3)
    report.duration_seconds = duration

    return graph0, duration


def extract_project(
    project_root: Path,
    config: Optional[CodegraphConfig] = None,
    *,
    use_cache: bool = True,
    parallel: bool = False,
    max_workers: Optional[int] = None,
    include_stubs: bool = False,
    progress: bool = True,
) -> Tuple[Graph0, ExtractionReport]:
    """Extract the complete Graph_0 for a project.  (C-009, C-025, C-029, C-034)

    Returns
    -------
    (Graph0, ExtractionReport)
        The assembled graph and a summary report.
    """
    t0 = time.monotonic()
    if config is None:
        config = load_config(project_root)

    # Discover source files (multi-language: use extractor registry)
    from codegraph.extractors import setup as _setup_extractors
    _setup_extractors(project_root)
    source_files = discover_source_files(project_root)
    if not source_files:
        logger.info("No source files found in %s", project_root)
        report = ExtractionReport()
        return Graph0(source_files=[]), report

    # Initialize extraction infrastructure
    cache, prog, resolver, report = _initialize_extraction(
        project_root, use_cache, progress, len(source_files)
    )
    all_nodes, node_counts = [], {}

    # Run extraction (serial or parallel)
    _run_file_extraction(
        source_files, project_root, include_stubs, use_cache,
        cache, prog, resolver, report, all_nodes, node_counts,
    )

    if prog:
        prog.finish()

    # Save cache
    if cache is not None:
        try:
            cache.save()
        except Exception:
            logger.warning("Could not save extraction cache")

    # Phase 2 — Extract API routes (polyglot support)
    # API extraction links frontend components to backend services via HTTP endpoints
    try:
        from codegraph.extractors.api_routes import APIRouteExtractor
        api_extractor = APIRouteExtractor(project_root)
        api_result = api_extractor.extract_all()
        if api_result.nodes:
            all_nodes.extend(api_result.nodes)
            node_counts["api_endpoint"] = len([n for n in api_result.nodes if n.type == "api_endpoint"])
            logger.info("Extracted %d API endpoints", len(api_result.nodes))
    except Exception as exc:
        logger.warning("API route extraction failed: %s", exc)

    # Finalize and assemble Graph_0
    graph0, duration = _finalize_graph0(
        project_root, report, source_files, all_nodes, node_counts, resolver, t0
    )


# ═══════════════════════════════════════════════════════════════════════
# C-030 — Graph_0 persistence (save / load)
# ═══════════════════════════════════════════════════════════════════════


def save_graph0(graph0: Graph0, project_root: Path) -> Path:
    """Persist *graph0* to ``.codegraph/graphs/graph0.json``."""
    ensure_codegraph_dir(project_root)
    dest = resolve_path(project_root, GRAPHS_DIR, "graph0.json")
    data = json.loads(graph0.to_json())
    atomic_write(dest, data)
    logger.info("Saved Graph_0 (%d nodes) → %s", len(graph0.nodes), dest)
    return dest


def load_graph0(project_root: Path) -> Graph0:
    """Load Graph_0 from ``.codegraph/graphs/graph0.json``.

    Returns an empty Graph0 if the file does not exist.
    """
    path = resolve_path(project_root, GRAPHS_DIR, "graph0.json")
    if not path.exists():
        logger.debug("No graph0.json found — returning empty Graph_0")
        return Graph0()

    try:
        text = path.read_text(encoding="utf-8")
        return Graph0.from_json(text)
    except (json.JSONDecodeError, KeyError) as exc:
        logger.error("Corrupted graph0.json: %s", exc)
        raise ValueError(f"Corrupted graph0.json: {exc}") from exc


# ═══════════════════════════════════════════════════════════════════════
# C-031 — Graph_0 comparison for delta
# ═══════════════════════════════════════════════════════════════════════


def compare_graphs(old: Graph0, new: Graph0) -> GraphDiff:
    """Compare two Graph_0 instances, returning a diff."""
    old_ids = {n.id: n for n in old.nodes}
    new_ids = {n.id: n for n in new.nodes}

    diff = GraphDiff()
    diff.nodes_added = sorted(nid for nid in new_ids if nid not in old_ids)
    diff.nodes_removed = sorted(nid for nid in old_ids if nid not in new_ids)
    diff.nodes_modified = sorted(
        nid
        for nid in new_ids
        if nid in old_ids and new_ids[nid].body_hash != old_ids[nid].body_hash
    )

    return diff
