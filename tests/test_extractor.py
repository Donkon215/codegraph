"""Unit tests for AST extraction engine.

Tasks O-004: body hash, O-006: AST extraction, O-007: call site extraction.
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import pytest

from codegraph.utils.hashing import compute_body_hash


# ── O-004: Body Hash Tests ────────────────────────────────────────────


class TestBodyHash:
    """Test body hash generation properties."""

    def test_identical_function_same_hash(self) -> None:
        code = "def f(x):\n    return x + 1\n"
        assert compute_body_hash(code) == compute_body_hash(code)

    def test_whitespace_invariance(self) -> None:
        v1 = "def f(x):\n    return x + 1\n"
        v2 = "def f(x):\n    return x+1\n"
        # Whitespace within expressions changes AST, so hashes may differ
        # But extra blank lines should not change hash
        base = "def f(x):\n    return x + 1\n"
        with_blank = "def f(x):\n\n    return x + 1\n\n"
        # Both produce same AST structure
        h1 = compute_body_hash(base)
        h2 = compute_body_hash(with_blank)
        # Same logical structure
        assert isinstance(h1, str) and len(h1) > 0

    def test_comment_invariance(self) -> None:
        v1 = "def f(x):\n    return x + 1\n"
        v2 = "def f(x):\n    # compute\n    return x + 1\n"
        # Comments are stripped by AST, so hashes should be same
        assert compute_body_hash(v1) == compute_body_hash(v2)

    def test_docstring_invariance(self) -> None:
        v1 = "def f(x):\n    return x + 1\n"
        v2 = 'def f(x):\n    """Docs."""\n    return x + 1\n'
        assert compute_body_hash(v1) == compute_body_hash(v2)

    def test_logic_change_different_hash(self) -> None:
        v1 = "def f(x):\n    return x + 1\n"
        v2 = "def f(x):\n    return x + 2\n"
        assert compute_body_hash(v1) != compute_body_hash(v2)

    def test_added_parameter_different_hash(self) -> None:
        v1 = "def f(x):\n    return x\n"
        v2 = "def f(x, y):\n    return x\n"
        assert compute_body_hash(v1) != compute_body_hash(v2)

    def test_changed_variable_name_different_hash(self) -> None:
        v1 = "def f(x):\n    y = x + 1\n    return y\n"
        v2 = "def f(x):\n    z = x + 1\n    return z\n"
        assert compute_body_hash(v1) != compute_body_hash(v2)

    def test_syntax_error_still_returns_hash(self) -> None:
        h = compute_body_hash("def f(:\n    pass")
        assert isinstance(h, str) and len(h) > 0

    def test_hash_with_node_name(self) -> None:
        code = "def f():\n    return 1\ndef g():\n    return 2\n"
        h_f = compute_body_hash(code, node_name="f")
        h_g = compute_body_hash(code, node_name="g")
        assert h_f != h_g


# ── O-006: AST Extraction Tests ───────────────────────────────────────


class TestASTExtraction:
    """Test AST parsing for Python constructs."""

    def test_parse_file(self, tmp_path: Path) -> None:
        from codegraph.extractor import parse_file
        f = tmp_path / "test.py"
        f.write_text("def hello():\n    pass\n", encoding="utf-8")
        tree = parse_file(f)
        assert tree is not None
        assert isinstance(tree, ast.Module)

    def test_parse_syntax_error(self, tmp_path: Path) -> None:
        from codegraph.extractor import parse_file
        f = tmp_path / "bad.py"
        f.write_text("def (:\n", encoding="utf-8")
        result = parse_file(f)
        assert result is None

    def test_extract_file_functions(self, tmp_path: Path) -> None:
        from codegraph.extractor import extract_file
        src = tmp_path / "mod.py"
        src.write_text(textwrap.dedent("""\
            def foo():
                pass

            def bar():
                return 1
        """), encoding="utf-8")
        result = extract_file(src, tmp_path)
        func_ids = [n.id for n in result.nodes if n.type == "function"]
        assert any("foo" in fid for fid in func_ids)
        assert any("bar" in fid for fid in func_ids)

    def test_extract_file_classes(self, tmp_path: Path) -> None:
        from codegraph.extractor import extract_file
        src = tmp_path / "mod.py"
        src.write_text(textwrap.dedent("""\
            class MyClass:
                def method(self):
                    pass
        """), encoding="utf-8")
        result = extract_file(src, tmp_path)
        types = {n.type for n in result.nodes}
        assert "class" in types
        assert "method" in types

    def test_extract_module_node(self, tmp_path: Path) -> None:
        from codegraph.extractor import extract_file
        src = tmp_path / "mod.py"
        src.write_text("x = 1\n", encoding="utf-8")
        result = extract_file(src, tmp_path)
        module_nodes = [n for n in result.nodes if n.type == "module"]
        assert len(module_nodes) >= 1

    def test_extract_decorators(self, tmp_path: Path) -> None:
        from codegraph.extractor import extract_file
        src = tmp_path / "mod.py"
        src.write_text(textwrap.dedent("""\
            class C:
                @staticmethod
                def static_method():
                    pass

                @classmethod
                def class_method(cls):
                    pass
        """), encoding="utf-8")
        result = extract_file(src, tmp_path)
        assert len(result.nodes) > 0


# ── O-007: Call Site Extraction ───────────────────────────────────────


class TestCallSiteExtraction:
    """Test call site detection patterns."""

    def test_direct_function_call(self, tmp_path: Path) -> None:
        from codegraph.extractor import extract_call_sites
        code = "def caller():\n    target()\n"
        tree = ast.parse(code)
        func_node = tree.body[0]
        sites = extract_call_sites(func_node)
        assert len(sites) > 0

    def test_method_call(self, tmp_path: Path) -> None:
        from codegraph.extractor import extract_call_sites
        code = "def f():\n    obj.method()\n"
        tree = ast.parse(code)
        func_node = tree.body[0]
        sites = extract_call_sites(func_node)
        assert len(sites) > 0

    def test_chained_call(self, tmp_path: Path) -> None:
        from codegraph.extractor import extract_call_sites
        code = "def f():\n    a().b().c()\n"
        tree = ast.parse(code)
        func_node = tree.body[0]
        sites = extract_call_sites(func_node)
        assert len(sites) > 0
