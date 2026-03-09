"""Fuzz tests for parser inputs.

Task O-032: Fuzz test query parser and JSON loaders.
"""

from __future__ import annotations

import json
import random
import string

import pytest

from codegraph.query import parse_query


class TestQueryParserFuzz:
    """Fuzz the query parser with random/malformed input."""

    _RANDOM_STRINGS = [
        "",
        " ",
        "()",
        "(((",
        'callers("")',
        "callers(')",
        "x" * 1000,
        "callers(\x00)",
        'callers("a", "b", "c", "d")',
        "orphans",
        "orphans(",
        "orphans(abc",
        '{"json": true}',
        "SELECT * FROM nodes",
        "<script>alert(1)</script>",
        "callers(null)",
        "dependencies(depth=-1)",
        "layer(999)",
        'path("a")',
        "  callers  (  'x'  )  ",
    ]

    @pytest.mark.parametrize("input_str", _RANDOM_STRINGS)
    def test_no_crash(self, input_str: str) -> None:
        """Parser must not crash on any input."""
        try:
            parse_query(input_str)
        except (ValueError, TypeError):
            pass  # Expected for invalid input

    def test_random_strings_no_crash(self) -> None:
        """Try 100 random strings — none should crash the parser."""
        rng = random.Random(42)
        chars = string.printable
        for _ in range(100):
            length = rng.randint(0, 200)
            s = "".join(rng.choice(chars) for _ in range(length))
            try:
                parse_query(s)
            except (ValueError, TypeError):
                pass


class TestJsonLoaderFuzz:
    """Fuzz JSON loading with malformed data."""

    @pytest.mark.parametrize("bad_json", [
        "",
        "{",
        '{"nodes": null}',
        '{"nodes": "not_a_list"}',
        "[]",
        '{"format_version": "not_int"}',
        '{"nodes": [{"id": null}]}',
        '{"extra_field": true}',
    ])
    def test_graph0_no_crash(self, bad_json: str) -> None:
        from codegraph.models.graph0 import Graph0
        try:
            Graph0.from_json(bad_json)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            pass

    @pytest.mark.parametrize("bad_json", [
        "",
        "{}",
        '{"nodes": [{}]}',
        '{"format_version": null}',
    ])
    def test_graph1_no_crash(self, bad_json: str) -> None:
        from codegraph.models.graph1 import Graph1
        try:
            Graph1.from_json(bad_json)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            pass

    @pytest.mark.parametrize("bad_json", [
        "",
        "{}",
        '{"edges": null}',
        '{"edges": [{"source": "a"}]}',
    ])
    def test_workflow_no_crash(self, bad_json: str) -> None:
        from codegraph.models.workflow import Workflow
        try:
            Workflow.from_json(bad_json)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            pass


class TestNodeIdFuzz:
    """Fuzz node ID parser with special characters."""

    @pytest.mark.parametrize("input_str", [
        "",
        "::",
        "::::",
        "a::b::c::d::e",
        "unicode_ñ::函数",
        "path/with spaces.py::func",
        "no_separator",
        "a" * 500 + "::func",
    ])
    def test_generate_no_crash(self, input_str: str) -> None:
        from codegraph.utils.ids import generate_node_id
        try:
            generate_node_id(input_str)
        except (ValueError, TypeError):
            pass
