"""Tests for codegraph.runtime_graph — Runtime behaviour extraction."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from codegraph.runtime_graph import (
    RuntimeEdge,
    RuntimeGraph,
    RuntimeEdgeVisitor,
    extract_runtime_edges,
    save_runtime_graph,
    load_runtime_graph,
)


# ── Data Classes ──────────────────────────────────────────────────────


class TestRuntimeEdge:
    def test_basic(self):
        e = RuntimeEdge(
            source_file="app.py",
            source_node="app.py::fetch",
            edge_type="http_call",
            target="https://api.example.com/users",
        )
        d = e.to_dict()
        assert d["edge_type"] == "http_call"
        assert d["target"] == "https://api.example.com/users"
        assert "details" not in d  # empty details omitted

    def test_with_details(self):
        e = RuntimeEdge(
            source_file="db.py",
            source_node="db.py::query",
            edge_type="db_query",
            target="users",
            details={"operation": "execute"},
        )
        d = e.to_dict()
        assert d["details"]["operation"] == "execute"


class TestRuntimeGraph:
    def test_empty(self):
        g = RuntimeGraph()
        d = g.to_dict()
        assert d["total_edges"] == 0
        assert d["files_scanned"] == 0

    def test_format(self):
        g = RuntimeGraph(
            files_scanned=10,
            edge_types={"http_call": 5, "db_query": 3},
        )
        text = g.format()
        assert "10 files" in text
        assert "http_call" in text


# ── AST Visitor ───────────────────────────────────────────────────────


class TestRuntimeEdgeVisitor:
    def _visit_source(self, source: str, filename: str = "test.py"):
        import ast
        tree = ast.parse(textwrap.dedent(source))
        visitor = RuntimeEdgeVisitor(filename)
        visitor.visit(tree)
        return visitor.edges

    def test_http_get(self):
        edges = self._visit_source("""
            import requests
            def fetch():
                requests.get("https://api.example.com/data")
        """)
        assert len(edges) == 1
        assert edges[0].edge_type == "http_call"
        assert edges[0].target == "https://api.example.com/data"
        assert edges[0].details["method"] == "GET"

    def test_http_post(self):
        edges = self._visit_source("""
            def send():
                client.post("https://api.example.com/submit")
        """)
        assert len(edges) == 1
        assert edges[0].details["method"] == "POST"

    def test_db_execute(self):
        edges = self._visit_source("""
            def query_users():
                cursor.execute("SELECT * FROM users WHERE id = ?")
        """)
        assert len(edges) == 1
        assert edges[0].edge_type == "db_query"
        assert edges[0].target == "users"

    def test_db_insert(self):
        edges = self._visit_source("""
            def insert():
                cursor.execute("INSERT INTO orders VALUES (?, ?)")
        """)
        assert len(edges) == 1
        assert edges[0].target == "orders"

    def test_mq_publish(self):
        edges = self._visit_source("""
            def notify():
                channel.publish(queue="notifications")
        """)
        assert len(edges) == 1
        assert edges[0].edge_type == "mq_publish"
        assert edges[0].target == "notifications"

    def test_env_var_getenv(self):
        edges = self._visit_source("""
            import os
            def config():
                os.getenv("DATABASE_URL")
        """)
        assert len(edges) == 1
        assert edges[0].edge_type == "env_var"
        assert edges[0].target == "DATABASE_URL"

    def test_env_var_environ_get(self):
        edges = self._visit_source("""
            import os
            def config():
                os.environ.get("SECRET_KEY")
        """)
        assert len(edges) == 1
        assert edges[0].edge_type == "env_var"
        assert edges[0].target == "SECRET_KEY"

    def test_dynamic_url(self):
        edges = self._visit_source("""
            def fetch(url):
                requests.get(url)
        """)
        assert len(edges) == 1
        assert edges[0].target == "<dynamic>"

    def test_class_method(self):
        edges = self._visit_source("""
            class Service:
                def call_api(self):
                    requests.get("https://api.test.com")
        """)
        assert len(edges) == 1
        assert "Service" in edges[0].source_node

    def test_no_runtime_edges(self):
        edges = self._visit_source("""
            def add(a, b):
                return a + b
        """)
        assert len(edges) == 0


# ── Extraction ────────────────────────────────────────────────────────


class TestExtractRuntimeEdges:
    def test_basic_extraction(self, tmp_path):
        (tmp_path / "app.py").write_text(textwrap.dedent("""
            import requests
            def fetch():
                requests.get("https://api.example.com/data")
        """))
        graph = extract_runtime_edges(tmp_path)
        assert graph.files_scanned == 1
        assert len(graph.edges) == 1

    def test_excludes_pycache(self, tmp_path):
        cache_dir = tmp_path / "__pycache__"
        cache_dir.mkdir()
        (cache_dir / "test.py").write_text("requests.get('x')")
        graph = extract_runtime_edges(tmp_path)
        assert graph.files_scanned == 0

    def test_edge_type_counts(self, tmp_path):
        (tmp_path / "app.py").write_text(textwrap.dedent("""
            def f():
                requests.get("http://a.com")
                requests.post("http://b.com")
                cursor.execute("SELECT * FROM t1")
        """))
        graph = extract_runtime_edges(tmp_path)
        assert graph.edge_types.get("http_call", 0) == 2
        assert graph.edge_types.get("db_query", 0) == 1


# ── Save / Load ───────────────────────────────────────────────────────


class TestSaveLoadRuntimeGraph:
    def test_roundtrip(self, tmp_path):
        graph = RuntimeGraph(files_scanned=5)
        graph.edges.append(RuntimeEdge(
            source_file="app.py",
            source_node="app.py::fetch",
            edge_type="http_call",
            target="https://api.test.com",
            details={"method": "GET"},
        ))
        graph.edge_types = {"http_call": 1}
        path = save_runtime_graph(tmp_path, graph)
        assert path.exists()

        loaded = load_runtime_graph(tmp_path)
        assert loaded is not None
        assert len(loaded.edges) == 1
        assert loaded.edges[0].target == "https://api.test.com"
        assert loaded.files_scanned == 5

    def test_load_missing(self, tmp_path):
        assert load_runtime_graph(tmp_path) is None
