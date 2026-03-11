"""codegraph.extractors.javascript — JavaScript/TypeScript/React extractor.

Handles .js, .jsx, .ts, .tsx, .mjs, .cjs files using regex-based analysis.
No external AST parser is required — works with the standard library only.
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
# Internal helpers
# ---------------------------------------------------------------------------

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

    # ---- Imports ----
    import_seen: set = set()

    for m in _RE_IMPORT_FROM.finditer(source):
        module = m.group(1)
        if module in import_seen:
            continue
        import_seen.add(module)
        imports.append(ImportInfo(
            module=module,
            line=_line_of(source, m.start()),
            is_relative=module.startswith("."),
        ))

    for m in _RE_IMPORT_BARE.finditer(source):
        module = m.group(1)
        if module in import_seen:
            continue
        import_seen.add(module)
        imports.append(ImportInfo(
            module=module,
            line=_line_of(source, m.start()),
            is_relative=module.startswith("."),
        ))

    for m in _RE_REQUIRE.finditer(source):
        module = m.group(1)
        if module in import_seen:
            continue
        import_seen.add(module)
        imports.append(ImportInfo(
            module=module,
            line=_line_of(source, m.start()),
            is_relative=module.startswith("."),
        ))

    return FileExtractionResult(nodes=nodes, imports=imports)


def _extract_js_edges(
    file_path: Path,
    project_root: Path,
    nodes: List[Graph0Node],
) -> List[WorkflowEdge]:
    """Return import edges for *file_path* as :class:`WorkflowEdge` objects.

    Each ``import … from 'module'`` statement becomes an edge from the file's
    module node to the imported module path.  Call-graph edges within function
    bodies are not yet extracted (stub — same as :class:`PythonExtractor`).
    """
    rel_file = normalize_path(file_path, project_root)
    source_node = rel_file  # module node ID

    try:
        source = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    edges: List[WorkflowEdge] = []
    seen: set = set()

    for pattern in (_RE_IMPORT_FROM, _RE_IMPORT_BARE, _RE_REQUIRE):
        for m in pattern.finditer(source):
            module = m.group(1)
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

    return edges


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
        """Extract import edges from a JS/TS file.

        Returns one :class:`WorkflowEdge` per unique ``import``/``require``
        statement, with ``edge_type="import"``.  Intra-file call edges are
        not yet extracted (same stub behaviour as :class:`PythonExtractor`).
        """
        return _extract_js_edges(file_path, self._root, nodes)
