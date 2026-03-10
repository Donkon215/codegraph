"""Tests for codegraph.path_query — pattern-based path queries."""

import pytest

from codegraph.path_query import PathResult, find_pattern_paths, check_forbidden_path


class TestPathResult:
    def test_empty_result(self):
        r = PathResult(source_pattern="a/*", target_pattern="b/*")
        assert not r.has_paths
        assert r.to_dict()["total_paths"] == 0

    def test_result_with_paths(self):
        r = PathResult(
            source_pattern="a/*",
            target_pattern="b/*",
            paths_found=[["a/x", "mid", "b/y"]],
            source_matches=1,
            target_matches=1,
        )
        assert r.has_paths
        assert r.to_dict()["total_paths"] == 1

    def test_format_no_paths(self):
        r = PathResult(source_pattern="a/*", target_pattern="b/*")
        text = r.format()
        assert "No path found" in text

    def test_format_with_paths(self):
        r = PathResult(
            source_pattern="a/*",
            target_pattern="b/*",
            paths_found=[["a/x", "b/y"]],
        )
        text = r.format()
        assert "Found 1 path(s)" in text
        assert "a/x" in text


class TestFindPatternPaths:
    def test_no_index_returns_empty(self, tmp_path):
        """Test with a mock index that has no nodes."""
        from unittest.mock import MagicMock
        import sqlite3

        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE nodes (node_id TEXT, id TEXT, file TEXT, type TEXT, line INTEGER, body_hash TEXT, dep_hash TEXT)")
        mock_index = MagicMock()
        mock_index._conn = conn
        mock_index._get_conn.return_value = conn
        mock_index.get_callees.return_value = []

        result = find_pattern_paths("a/*", "b/*", mock_index)
        assert not result.has_paths
        assert result.source_matches == 0

    def test_direct_path(self, tmp_path):
        """Test path finding with a direct edge."""
        from unittest.mock import MagicMock
        import sqlite3

        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE nodes (node_id TEXT, id TEXT)")
        conn.execute("INSERT INTO nodes VALUES ('a/x::func1', 'a/x::func1')")
        conn.execute("INSERT INTO nodes VALUES ('b/y::func2', 'b/y::func2')")

        mock_index = MagicMock()
        mock_index._conn = conn
        mock_index._get_conn.return_value = conn
        mock_index.get_callees.side_effect = lambda nid: ["b/y::func2"] if nid == "a/x::func1" else []

        result = find_pattern_paths("a/*", "b/*", mock_index)
        assert result.has_paths
        assert result.source_matches == 1
        assert result.target_matches == 1


class TestCheckForbiddenPath:
    def test_forbidden_path_found(self):
        from unittest.mock import MagicMock
        import sqlite3

        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE nodes (node_id TEXT, id TEXT)")
        conn.execute("INSERT INTO nodes VALUES ('api/handler::process', 'api/handler::process')")
        conn.execute("INSERT INTO nodes VALUES ('db/engine::query', 'db/engine::query')")

        mock_index = MagicMock()
        mock_index._conn = conn
        mock_index._get_conn.return_value = conn
        mock_index.get_callees.side_effect = lambda nid: ["db/engine::query"] if nid == "api/handler::process" else []

        result = check_forbidden_path("api/*", "db/*", mock_index)
        assert result.violation

    def test_forbidden_path_not_found(self):
        from unittest.mock import MagicMock
        import sqlite3

        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE nodes (node_id TEXT, id TEXT)")
        conn.execute("INSERT INTO nodes VALUES ('api/handler::process', 'api/handler::process')")
        conn.execute("INSERT INTO nodes VALUES ('db/engine::query', 'db/engine::query')")

        mock_index = MagicMock()
        mock_index._conn = conn
        mock_index._get_conn.return_value = conn
        mock_index.get_callees.return_value = []

        result = check_forbidden_path("api/*", "db/*", mock_index)
        assert not result.violation
