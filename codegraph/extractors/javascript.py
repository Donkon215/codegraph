"""codegraph.extractors.javascript — JavaScript/TypeScript/React extractor.

Handles .js, .jsx, .ts, .tsx, .mjs, .cjs files using regex-based analysis.
No external AST parser is required — works with the standard library only.

Extracts:
  - Function declarations and arrow functions
  - Class declarations with methods
  - TypeScript interfaces
  - JSX component usage (component → component edges)
  - React hook calls (component → hook edges)
  - Dynamic imports (import())
  - Express.js backend endpoints
  - Intra-file call edges (function → function)
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import List, Optional, Tuple

from codegraph.constants import BODY_HASH_LENGTH
from codegraph.extractor import FileExtractionResult, ImportInfo
from codegraph.models.graph0 import Graph0Node, NodeType
from codegraph.types import WorkflowEdge
from codegraph.utils.ids import normalize_path

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Named function declarations (function keyword)
# Matches: [export] [default] [async] function Name(  or  function Name<T>(
_RE_FUNC_DECL = re.compile(
    r"^[ \t]*(?:export\s+(?:default\s+)?)?(?:async\s+)?function\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*[(<]",
    re.MULTILINE,
)

# Arrow functions / function expressions assigned to a variable
# Matches: [export] const|let|var Name [<T>] = [async] (...) =>
#      and: [export] const|let|var Name [<T>] = [async] function
_RE_ARROW_OR_EXPR = re.compile(
    r"^[ \t]*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)"
    r"(?:\s*:\s*[A-Za-z_$][A-Za-z0-9_$<>\[\] |,]*?)?"  # optional TS type annotation
    r"\s*=\s*(?:async\s+)?"
    r"(?:"
    r"\([^)]*\)\s*(?::\s*[A-Za-z_$<>\[\] |,]+)?\s*=>"  # (...): RetType =>
    r"|[A-Za-z_$][A-Za-z0-9_$]*\s*=>"                   # x =>
    r"|function\s*[(*]"                                   # function expression
    r")",
    re.MULTILINE,
)

# Class declarations (ES6 + TypeScript abstract classes)
_RE_CLASS = re.compile(
    r"^[ \t]*(?:export\s+(?:default\s+)?)?(?:abstract\s+)?class\s+([A-Za-z_$][A-Za-z0-9_$]*)",
    re.MULTILINE,
)

# TypeScript interface declarations (treated as class-like nodes)
_RE_INTERFACE = re.compile(
    r"^[ \t]*(?:export\s+)?interface\s+([A-Za-z_$][A-Za-z0-9_$]*)",
    re.MULTILINE,
)

# ES6 import … from 'module'  (includes: import type, default, named, namespace)
_RE_IMPORT_FROM = re.compile(
    r"""^[ \t]*import\s+(?:type\s+)?[^'"()\n]+?\bfrom\s+['"]([^'"]+)['"]""",
    re.MULTILINE,
)

# Side-effect imports: import 'module'
_RE_IMPORT_BARE = re.compile(
    r"""^[ \t]*import\s+['"]([^'"]+)['"]""",
    re.MULTILINE,
)

# CommonJS: require('module')
_RE_REQUIRE = re.compile(
    r"""require\s*\(\s*['"]([^'"]+)['"]\s*\)""",
    re.MULTILINE,
)

# ---------------------------------------------------------------------------
# React / JSX patterns
# ---------------------------------------------------------------------------

# JSX component usage: <ComponentName   (uppercase first letter = component)
_RE_JSX_COMPONENT = re.compile(
    r"<([A-Z][A-Za-z0-9_$]*)\b",
    re.MULTILINE,
)

# React hook calls: useXxx(  — both built-in and custom
_RE_HOOK_CALL = re.compile(
    r"\b(use[A-Z][A-Za-z0-9_$]*)\s*\(",
    re.MULTILINE,
)

# Class method definitions (inside class bodies)
# Matches: [async] methodName(   or   [static] [async] methodName(
# Also: get/set propertyName(
_RE_CLASS_METHOD = re.compile(
    r"^[ \t]+(?:static\s+)?(?:async\s+)?(?:get\s+|set\s+)?([A-Za-z_$][A-Za-z0-9_$]*)\s*\(",
    re.MULTILINE,
)

# Dynamic import: import('module')
_RE_DYNAMIC_IMPORT = re.compile(
    r"""import\s*\(\s*['"]([^'"]+)['"]\s*\)""",
    re.MULTILINE,
)

# ---------------------------------------------------------------------------
# Express.js endpoint patterns
# ---------------------------------------------------------------------------

# app.get("/path", handler) or router.post("/path", ...)
_RE_EXPRESS_ROUTE = re.compile(
    r"""\b\w+\.(get|post|put|delete|patch|options|head|all)\s*\(\s*['"`]([^'"`]+)['"`]""",
    re.MULTILINE | re.IGNORECASE,
)

# app.use("/path", router) — middleware mount
_RE_EXPRESS_USE = re.compile(
    r"""\b\w+\.use\s*\(\s*['"`]([^'"`]+)['"`]""",
    re.MULTILINE,
)

# ---------------------------------------------------------------------------
# Intra-file function call pattern
# ---------------------------------------------------------------------------

# Direct function call: funcName(   — must be a known defined function
_RE_FUNCTION_CALL = re.compile(
    r"\b([A-Za-z_$][A-Za-z0-9_$]*)\s*\(",
    re.MULTILINE,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# JS/TS file extensions used for resolving bare imports
_JS_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")


def _resolve_js_import(
    import_path: str,
    importing_file: Path,
    project_root: Path,
) -> str:
    """Resolve a JS/TS import specifier to a project-relative module path.

    Relative imports (e.g. ``./components/Login``) are resolved against the
    importing file's directory.  The function tries common extensions and
    ``/index`` patterns.  Non-relative imports (npm packages) are returned
    as-is.
    """
    if not import_path.startswith("."):
        return import_path  # npm / bare package — keep original

    base_dir = importing_file.parent
    resolved = (base_dir / import_path).resolve()

    # Try exact match, then with extensions, then /index variants
    for candidate in _import_candidates(resolved):
        if candidate.exists():
            return normalize_path(candidate, project_root)

    # Fallback: return the normalised relative path even if file doesn't exist
    try:
        rel = resolved.relative_to(project_root.resolve())
        return str(rel).replace("\\", "/")
    except ValueError:
        return import_path


def _import_candidates(base: Path) -> List[Path]:
    """Yield candidate file paths for a resolved import base path."""
    candidates: List[Path] = []
    # Direct match (already has extension)
    if base.suffix in _JS_EXTENSIONS:
        candidates.append(base)
        return candidates
    # Try extensions
    for ext in _JS_EXTENSIONS:
        candidates.append(base.with_suffix(ext))
    # Try /index variants
    for ext in _JS_EXTENSIONS:
        candidates.append(base / f"index{ext}")
    return candidates

def _line_of(text: str, match_start: int) -> int:
    """Return 1-based line number for the character at *match_start*."""
    return text.count("\n", 0, match_start) + 1


def _body_hash(text: str, match_start: int) -> str:
    """Compute a short hash over the text window starting at *match_start*.

    Uses up to 500 characters as the 'body' — enough to detect most changes
    without requiring a full AST-based body extraction.
    """
    snippet = text[match_start: match_start + 500]
    return hashlib.sha256(snippet.encode()).hexdigest()[:BODY_HASH_LENGTH]


def _extract_js_file(file_path: Path, project_root: Path) -> FileExtractionResult:
    """Parse *file_path* and return a :class:`FileExtractionResult`.

    Extracts:
    - One module node per file.
    - Named function declarations (``function Foo()``).
    - Arrow functions / function expressions assigned to variables
      (``const Foo = () =>``).
    - Class declarations and TypeScript interfaces.
    - ES6 import statements and CommonJS ``require()`` calls.
    """
    try:
        source = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return FileExtractionResult()

    rel_file = normalize_path(file_path, project_root)
    nodes: List[Graph0Node] = []
    imports: List[ImportInfo] = []

    # Module node — one per file, always present
    nodes.append(Graph0Node(
        id=rel_file,
        body_hash=hashlib.sha256(source.encode()).hexdigest()[:BODY_HASH_LENGTH],
        file=rel_file,
        type=NodeType.MODULE.value,
        line=1,
    ))

    seen_ids: set = set()
    seen_ids.add(rel_file)

    # ---- Function declarations ----
    for m in _RE_FUNC_DECL.finditer(source):
        name = m.group(1)
        node_id = f"{rel_file}::{name}"
        if node_id in seen_ids:
            continue
        seen_ids.add(node_id)
        nodes.append(Graph0Node(
            id=node_id,
            body_hash=_body_hash(source, m.start()),
            file=rel_file,
            type=NodeType.FUNCTION.value,
            line=_line_of(source, m.start()),
        ))

    # ---- Arrow functions / function expressions ----
    for m in _RE_ARROW_OR_EXPR.finditer(source):
        name = m.group(1)
        node_id = f"{rel_file}::{name}"
        if node_id in seen_ids:
            continue
        seen_ids.add(node_id)
        nodes.append(Graph0Node(
            id=node_id,
            body_hash=_body_hash(source, m.start()),
            file=rel_file,
            type=NodeType.FUNCTION.value,
            line=_line_of(source, m.start()),
        ))

    # ---- Class declarations ----
    for m in _RE_CLASS.finditer(source):
        name = m.group(1)
        node_id = f"{rel_file}::{name}"
        if node_id in seen_ids:
            continue
        seen_ids.add(node_id)
        nodes.append(Graph0Node(
            id=node_id,
            body_hash=_body_hash(source, m.start()),
            file=rel_file,
            type=NodeType.CLASS.value,
            line=_line_of(source, m.start()),
        ))

    # ---- TypeScript interfaces ----
    for m in _RE_INTERFACE.finditer(source):
        name = m.group(1)
        node_id = f"{rel_file}::{name}"
        if node_id in seen_ids:
            continue
        seen_ids.add(node_id)
        nodes.append(Graph0Node(
            id=node_id,
            body_hash=_body_hash(source, m.start()),
            file=rel_file,
            type=NodeType.CLASS.value,
            line=_line_of(source, m.start()),
        ))

    # ---- Class methods ----
    class_nodes = [n for n in nodes if n.type == NodeType.CLASS.value]
    for cls_node in class_nodes:
        cls_name = cls_node.id.split("::")[-1]
        # Find class body: locate the class declaration and scan for methods
        cls_pattern = re.compile(
            rf"(?:class\s+{re.escape(cls_name)}\b.*?\{{)",
            re.DOTALL,
        )
        cls_match = cls_pattern.search(source)
        if not cls_match:
            continue
        # Scan for methods after class opening brace
        brace_depth = 1
        search_start = cls_match.end()
        class_end = len(source)
        pos = search_start
        while pos < len(source) and brace_depth > 0:
            ch = source[pos]
            if ch == "{":
                brace_depth += 1
            elif ch == "}":
                brace_depth -= 1
            pos += 1
        class_end = pos
        class_body = source[search_start:class_end]
        for mm in _RE_CLASS_METHOD.finditer(class_body):
            method_name = mm.group(1)
            if method_name in ("constructor", "if", "for", "while",
                               "switch", "return", "catch", "super"):
                continue
            node_id = f"{rel_file}::{cls_name}::{method_name}"
            if node_id in seen_ids:
                continue
            seen_ids.add(node_id)
            abs_line = _line_of(source, search_start + mm.start())
            nodes.append(Graph0Node(
                id=node_id,
                body_hash=_body_hash(source, search_start + mm.start()),
                file=rel_file,
                type=NodeType.METHOD.value,
                line=abs_line,
            ))

    # ---- Imports ----
    import_seen: set = set()

    for m in _RE_IMPORT_FROM.finditer(source):
        module = _resolve_js_import(m.group(1), file_path, project_root)
        if module in import_seen:
            continue
        import_seen.add(module)
        imports.append(ImportInfo(
            module=module,
            line=_line_of(source, m.start()),
            is_relative=m.group(1).startswith("."),
        ))

    for m in _RE_IMPORT_BARE.finditer(source):
        module = _resolve_js_import(m.group(1), file_path, project_root)
        if module in import_seen:
            continue
        import_seen.add(module)
        imports.append(ImportInfo(
            module=module,
            line=_line_of(source, m.start()),
            is_relative=m.group(1).startswith("."),
        ))

    for m in _RE_REQUIRE.finditer(source):
        module = _resolve_js_import(m.group(1), file_path, project_root)
        if module in import_seen:
            continue
        import_seen.add(module)
        imports.append(ImportInfo(
            module=module,
            line=_line_of(source, m.start()),
            is_relative=m.group(1).startswith("."),
        ))

    return FileExtractionResult(nodes=nodes, imports=imports)


def _extract_js_edges(
    file_path: Path,
    project_root: Path,
    nodes: List[Graph0Node],
) -> List[WorkflowEdge]:
    """Return edges for *file_path* as :class:`WorkflowEdge` objects.

    Extracts:
    - Import edges (import/require)
    - Dynamic import edges (import())
    - Intra-file call edges (function → function)
    - JSX component usage edges (component → component)
    - React hook call edges (component → hook)
    """
    rel_file = normalize_path(file_path, project_root)
    source_node = rel_file  # module node ID

    try:
        source = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    edges: List[WorkflowEdge] = []
    seen: set = set()

    # ---- Import edges ----
    for pattern in (_RE_IMPORT_FROM, _RE_IMPORT_BARE, _RE_REQUIRE):
        for m in pattern.finditer(source):
            module = _resolve_js_import(m.group(1), file_path, project_root)
            key = (source_node, module)
            if key in seen:
                continue
            seen.add(key)
            edges.append(WorkflowEdge(
                source=source_node,
                target=module,
                edge_type="import",
                confidence="static",
            ))

    # ---- Dynamic import edges ----
    for m in _RE_DYNAMIC_IMPORT.finditer(source):
        module = _resolve_js_import(m.group(1), file_path, project_root)
        key = (source_node, module, "dynamic")
        if key in seen:
            continue
        seen.add(key)
        edges.append(WorkflowEdge(
            source=source_node,
            target=module,
            edge_type="import",
            confidence="dynamic",
        ))

    # Build a set of locally defined node names for intra-file resolution
    local_names: dict = {}  # name → node_id
    for n in nodes:
        if "::" in n.id:
            parts = n.id.split("::")
            short_name = parts[-1]
            local_names[short_name] = n.id

    # ---- JSX component usage edges ----
    # <ComponentName → edge from enclosing function to ComponentName
    func_ranges = _build_func_scope_ranges(source, rel_file, nodes)
    for m in _RE_JSX_COMPONENT.finditer(source):
        comp_name = m.group(1)
        # Skip HTML-like tags that start uppercase (rare) or DOM elements
        if comp_name in ("React", "Fragment", "Suspense", "StrictMode"):
            continue
        line_no = _line_of(source, m.start())
        caller = _find_enclosing_scope(func_ranges, line_no, source_node)
        target = local_names.get(comp_name, f"{rel_file}::{comp_name}")
        key = (caller, target, "jsx")
        if key in seen or caller == target:
            continue
        seen.add(key)
        edges.append(WorkflowEdge(
            source=caller,
            target=target,
            edge_type="call",
            confidence="static",
        ))

    # ---- React hook call edges ----
    for m in _RE_HOOK_CALL.finditer(source):
        hook_name = m.group(1)
        line_no = _line_of(source, m.start())
        caller = _find_enclosing_scope(func_ranges, line_no, source_node)
        # Custom hooks defined locally get linked; built-in hooks are labeled
        target = local_names.get(hook_name, f"{rel_file}::{hook_name}")
        key = (caller, target, "hook")
        if key in seen or caller == target:
            continue
        seen.add(key)
        edges.append(WorkflowEdge(
            source=caller,
            target=target,
            edge_type="call",
            confidence="static",
        ))

    # ---- Intra-file function call edges ----
    for m in _RE_FUNCTION_CALL.finditer(source):
        called_name = m.group(1)
        # Only link if the called name is a locally defined function
        if called_name not in local_names:
            continue
        # Skip keywords and built-ins
        if called_name in ("if", "for", "while", "switch", "return",
                           "catch", "require", "import", "super",
                           "typeof", "new", "throw", "delete", "void"):
            continue
        line_no = _line_of(source, m.start())
        caller = _find_enclosing_scope(func_ranges, line_no, source_node)
        target = local_names[called_name]
        key = (caller, target, "call")
        if key in seen or caller == target:
            continue
        seen.add(key)
        edges.append(WorkflowEdge(
            source=caller,
            target=target,
            edge_type="call",
            confidence="static",
        ))

    return edges


def _build_func_scope_ranges(
    source: str,
    rel_file: str,
    nodes: List[Graph0Node],
) -> List[Tuple[int, str]]:
    """Build (start_line, node_id) list from extracted nodes for scope lookup."""
    ranges: List[Tuple[int, str]] = []
    for n in nodes:
        if n.type in (NodeType.FUNCTION.value, NodeType.METHOD.value) and "::" in n.id:
            ranges.append((n.line, n.id))
    return sorted(ranges, key=lambda x: x[0])


def _find_enclosing_scope(
    func_ranges: List[Tuple[int, str]],
    line_no: int,
    fallback: str,
) -> str:
    """Find the function/method whose scope encloses *line_no*."""
    result = fallback
    for fl, node_id in func_ranges:
        if fl <= line_no:
            result = node_id
        else:
            break
    return result


# ---------------------------------------------------------------------------
# Public extractor class
# ---------------------------------------------------------------------------

class JavaScriptExtractor:
    """Extract Graph_0 nodes and Workflow edges from JavaScript/TypeScript files.

    Supports ``.js``, ``.jsx``, ``.ts``, ``.tsx``, ``.mjs``, ``.cjs``
    including React component files.

    Uses regex-based analysis — no external AST parser required.
    """

    def __init__(self, project_root: Path) -> None:
        self._root = project_root

    def supported_extensions(self) -> List[str]:
        return [".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"]

    def extract_nodes(self, file_path: Path) -> List[Graph0Node]:
        """Extract all function/class/module nodes from a JS/TS file."""
        return _extract_js_file(file_path, self._root).nodes

    def extract_all(self, file_path: Path) -> FileExtractionResult:
        """Extract nodes, imports, and other metadata from a JS/TS file."""
        return _extract_js_file(file_path, self._root)

    def extract_edges(self, file_path: Path, nodes: List[Graph0Node]) -> List[WorkflowEdge]:
        """Extract edges from a JS/TS file.

        Returns :class:`WorkflowEdge` objects for:
        - Import/require statements (``edge_type="import"``)
        - Dynamic imports (``confidence="dynamic"``)
        - JSX component usage (component → component)
        - React hook calls (component → hook)
        - Intra-file function calls (function → function)
        """
        return _extract_js_edges(file_path, self._root, nodes)

    def extract_express_endpoints(
        self, file_path: Path,
    ) -> List[dict]:
        """Extract Express.js route definitions from a file.

        Returns dicts with keys: path, method, handler_node, file, line,
        framework ("express").
        """
        return _extract_express_endpoints(file_path, self._root)


# ---------------------------------------------------------------------------
# Express.js endpoint extraction
# ---------------------------------------------------------------------------

def _extract_express_endpoints(
    file_path: Path,
    project_root: Path,
) -> List[dict]:
    """Extract Express.js route definitions from a JS/TS file.

    Detects ``app.get("/path", handler)`` / ``router.post("/path", ...)``.
    Returns a list of endpoint dicts compatible with :mod:`api_routes`.
    """
    if not file_path.exists() or file_path.suffix not in _JS_EXTENSIONS:
        return []

    try:
        source = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    rel_file = normalize_path(file_path, project_root)
    endpoints: list = []
    lines = source.split("\n")

    # Build function context for handler attribution
    func_ranges: List[Tuple[int, str]] = []
    for m in _RE_FUNC_DECL.finditer(source):
        func_ranges.append((_line_of(source, m.start()), f"{rel_file}::{m.group(1)}"))
    for m in _RE_ARROW_OR_EXPR.finditer(source):
        func_ranges.append((_line_of(source, m.start()), f"{rel_file}::{m.group(1)}"))
    func_ranges.sort(key=lambda x: x[0])

    for m in _RE_EXPRESS_ROUTE.finditer(source):
        method = m.group(1).upper()
        path = m.group(2)
        # Skip non-route HTTP method patterns (e.g. obj.get("key"))
        if not path.startswith("/"):
            continue
        line_no = _line_of(source, m.start())
        # Try to find handler function name after the path string
        handler = _find_express_handler(source, m.end())
        node_id = f"{rel_file}::{handler}" if handler else rel_file
        endpoints.append({
            "path": path,
            "method": method,
            "handler_node": node_id,
            "file": rel_file,
            "line": line_no,
            "framework": "express",
        })

    return endpoints


def _find_express_handler(source: str, after_pos: int) -> Optional[str]:
    """Find the handler function name in an Express route definition.

    Looks for patterns like:
      app.get("/path", handlerFunc)
      app.get("/path", (req, res) => {  — returns None (anonymous)
    """
    # Skip whitespace and comma after path string
    rest = source[after_pos:after_pos + 200]
    m = re.match(r"""['"`,\s]*([A-Za-z_$][A-Za-z0-9_$.]*)""", rest)
    if m:
        name = m.group(1)
        # Skip anonymous arrow/function syntax
        if name in ("function", "async", "req", "res", "next", "err"):
            return None
        # Take the last segment (e.g. "controller.handleLogin" → "handleLogin")
        return name.split(".")[-1]
    return None
