"""codegraph.utils.hashing — File-content and AST body hashing.

(Tasks A-020, A-021)
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from typing import Optional

from codegraph.constants import BODY_HASH_LENGTH, FILE_HASH_LENGTH


# ── A-020  File-content hashing ────────────────────────────────────────


def hash_file(path: Path) -> str:
    """Return a truncated SHA-256 hex digest of *path*'s UTF-8 content.

    Line endings are normalized to ``\\n`` for cross-platform stability.
    """
    raw = path.read_text(encoding="utf-8")
    normalized = raw.replace("\r\n", "\n").replace("\r", "\n")
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return digest[:FILE_HASH_LENGTH]


# ── A-021  AST body-hash generator ────────────────────────────────────


class _DocstringStripper(ast.NodeTransformer):
    """Remove docstring nodes from an AST."""

    def _strip(self, node: ast.AST) -> ast.AST:
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module))
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
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


def compute_body_hash(source_code: str, node_name: Optional[str] = None) -> str:
    """Compute a deterministic hash of a function/class body, ignoring
    whitespace, comments, and docstrings.

    Parameters
    ----------
    source_code:
        The complete source of the function or class (or the whole module if
        *node_name* is ``None``).
    node_name:
        If provided, extract only the named function/class from the source
        before hashing.

    Returns
    -------
    str
        Hex digest truncated to :data:`BODY_HASH_LENGTH` characters.
    """
    try:
        tree = ast.parse(source_code)
    except SyntaxError:
        return hashlib.sha256(source_code.encode()).hexdigest()[:BODY_HASH_LENGTH]

    target: ast.AST = tree
    if node_name:
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name == node_name:
                    target = node
                    break

    stripped = _DocstringStripper().visit(target)
    canonical = ast.dump(stripped, annotate_fields=True, include_attributes=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:BODY_HASH_LENGTH]
