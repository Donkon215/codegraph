"""Unit tests for the query system.

Task O-015: Query functions with known graph data.
"""

from __future__ import annotations

import pytest

from codegraph.query import parse_query, ParsedQuery


class TestQueryParser:
    """Test query string parsing."""

    def test_simple_function(self) -> None:
        q = parse_query('callers("mod.py::func")')
        assert q.function == "callers"
        assert "mod.py::func" in q.args

    def test_no_args(self) -> None:
        q = parse_query("orphans()")
        assert q.function == "orphans"
        assert len(q.args) == 0

    def test_layer_query(self) -> None:
        q = parse_query("layer(4)")
        assert q.function == "layer"
        assert "4" in q.args or 4 in q.args

    def test_path_query(self) -> None:
        q = parse_query('path("a", "b")')
        assert q.function == "path"
        assert len(q.args) == 2

    def test_with_options(self) -> None:
        q = parse_query('dependencies("a", depth=3)')
        assert q.function == "dependencies"
        assert "depth" in q.options

    def test_explain(self) -> None:
        q = parse_query('explain("mod.py::func")')
        assert q.function == "explain"

    def test_single_quoted(self) -> None:
        q = parse_query("callers('mod.py::func')")
        assert q.function == "callers"
        assert "mod.py::func" in q.args


class TestQueryImports:
    """Test that query module is importable."""

    def test_import_run_query(self) -> None:
        from codegraph.query import run_query
        assert callable(run_query)

    def test_import_execute_query(self) -> None:
        from codegraph.query import execute_query
        assert callable(execute_query)

    def test_import_format_query_result(self) -> None:
        from codegraph.query import format_query_result
        assert callable(format_query_result)
