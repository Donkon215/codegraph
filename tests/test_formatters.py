"""Unit tests for the output formatting system.

Task N-020: Output formatter.
"""

from __future__ import annotations

import json

import pytest

from codegraph.formatters import OutputFormatter


class TestOutputFormatter:
    """Test OutputFormatter with different formats."""

    def test_text_format_value(self) -> None:
        f = OutputFormatter(fmt="text")
        assert f.format_value(42) == "42"

    def test_json_format_value(self) -> None:
        f = OutputFormatter(fmt="json")
        result = f.format_value({"key": "val"})
        data = json.loads(result)
        assert data["key"] == "val"

    def test_count_format_list(self) -> None:
        f = OutputFormatter(fmt="count")
        result = f.format_value([1, 2, 3])
        assert result == "3"

    def test_format_list_text(self) -> None:
        f = OutputFormatter(fmt="text")
        items = [{"name": "a"}, {"name": "b"}]
        result = f.format_list(items, columns=["name"])
        assert "a" in result
        assert "b" in result

    def test_format_list_json(self) -> None:
        f = OutputFormatter(fmt="json")
        items = [{"name": "a"}, {"name": "b"}]
        result = f.format_list(items)
        data = json.loads(result)
        assert len(data) == 2

    def test_format_list_csv(self) -> None:
        f = OutputFormatter(fmt="csv")
        items = [{"name": "a", "value": "1"}, {"name": "b", "value": "2"}]
        result = f.format_list(items, columns=["name", "value"])
        assert "name" in result
        assert "a" in result

    def test_format_list_table(self) -> None:
        f = OutputFormatter(fmt="table")
        items = [{"name": "alpha", "value": "100"}]
        result = f.format_list(items, columns=["name", "value"])
        assert "name" in result
        assert "alpha" in result
        assert "---" in result or "--" in result  # separator line

    def test_format_list_count(self) -> None:
        f = OutputFormatter(fmt="count")
        items = [{"a": 1}, {"a": 2}, {"a": 3}]
        result = f.format_list(items)
        assert result == "3"

    def test_format_dict(self) -> None:
        f = OutputFormatter(fmt="text")
        result = f.format_dict({"key1": "val1", "key2": "val2"})
        assert "key1: val1" in result

    def test_format_dict_json(self) -> None:
        f = OutputFormatter(fmt="json")
        result = f.format_dict({"key": "val"})
        data = json.loads(result)
        assert data["key"] == "val"

    def test_empty_list(self) -> None:
        f = OutputFormatter(fmt="text")
        result = f.format_list([])
        assert result == "(empty)"

    def test_empty_list_quiet(self) -> None:
        f = OutputFormatter(fmt="text", quiet=True)
        result = f.format_list([])
        assert result == ""

    def test_header_suppressed_in_json(self) -> None:
        f = OutputFormatter(fmt="json")
        assert f.header("Title") == ""

    def test_header_suppressed_in_quiet(self) -> None:
        f = OutputFormatter(fmt="text", quiet=True)
        assert f.header("Title") == ""

    def test_invalid_format_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown format"):
            OutputFormatter(fmt="xml")

    def test_key_fn(self) -> None:
        f = OutputFormatter(fmt="json")

        class Obj:
            def __init__(self, n: str) -> None:
                self.name = n

        items = [Obj("x"), Obj("y")]
        result = f.format_list(items, key_fn=lambda o: {"name": o.name})
        data = json.loads(result)
        assert data[0]["name"] == "x"
