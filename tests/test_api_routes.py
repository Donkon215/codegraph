"""Tests for codegraph.extractors.api_routes — cross-language API linker."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from codegraph.extractors.api_routes import (
    ApiCall,
    ApiEndpoint,
    ApiLinkReport,
    extract_js_api_calls,
    extract_python_endpoints,
    link_api_routes,
    _normalize_path,
    _normalize_api_path,
    _looks_like_api_path,
    _match_parameterized,
)


# ── normalize helpers ──────────────────────────────────────────────────


class TestNormalizePath:
    def test_trailing_slash(self):
        assert _normalize_path("/api/users/") == "/api/users"

    def test_lowercase(self):
        assert _normalize_path("/API/Users") == "/api/users"

    def test_leading_slash_added(self):
        assert _normalize_path("api/users") == "/api/users"

    def test_curly_brace_params(self):
        assert _normalize_path("/users/{id}") == "/users/:param"

    def test_colon_params(self):
        assert _normalize_path("/users/:userId") == "/users/:param"


class TestNormalizeApiPath:
    def test_template_literal(self):
        assert _normalize_api_path("/api/users/${userId}") == "/api/users/:param"


class TestLooksLikeApiPath:
    def test_slash_prefix(self):
        assert _looks_like_api_path("/api/data") is True

    def test_contains_api(self):
        assert _looks_like_api_path("http://server/api/data") is True

    def test_empty(self):
        assert _looks_like_api_path("") is False


# ── Python endpoint extraction ─────────────────────────────────────────


class TestExtractPythonEndpoints:
    def test_fastapi_get(self, tmp_path: Path):
        src = tmp_path / "app.py"
        src.write_text(textwrap.dedent("""\
            from fastapi import FastAPI
            app = FastAPI()

            @app.get("/users")
            async def list_users():
                return []
        """), encoding="utf-8")

        eps = extract_python_endpoints(src, tmp_path)
        assert len(eps) == 1
        assert eps[0].method == "GET"
        assert eps[0].path == "/users"
        assert eps[0].framework == "fastapi"
        assert "list_users" in eps[0].handler_node

    def test_fastapi_post(self, tmp_path: Path):
        src = tmp_path / "app.py"
        src.write_text(textwrap.dedent("""\
            from fastapi import FastAPI
            app = FastAPI()

            @app.post("/users")
            async def create_user(data: dict):
                pass
        """), encoding="utf-8")

        eps = extract_python_endpoints(src, tmp_path)
        assert len(eps) == 1
        assert eps[0].method == "POST"

    def test_flask_route(self, tmp_path: Path):
        src = tmp_path / "views.py"
        src.write_text(textwrap.dedent("""\
            from flask import Flask
            app = Flask(__name__)

            @app.route("/login", methods=["GET", "POST"])
            def login():
                pass
        """), encoding="utf-8")

        eps = extract_python_endpoints(src, tmp_path)
        assert len(eps) == 2
        methods = {e.method for e in eps}
        assert methods == {"GET", "POST"}
        assert all(e.framework == "flask" for e in eps)

    def test_flask_route_default_get(self, tmp_path: Path):
        src = tmp_path / "views.py"
        src.write_text(textwrap.dedent("""\
            from flask import Flask
            app = Flask(__name__)

            @app.route("/health")
            def health():
                return "ok"
        """), encoding="utf-8")

        eps = extract_python_endpoints(src, tmp_path)
        assert len(eps) == 1
        assert eps[0].method == "GET"

    def test_django_path(self, tmp_path: Path):
        src = tmp_path / "urls.py"
        src.write_text(textwrap.dedent("""\
            from django.urls import path
            from . import views

            urlpatterns = [
                path("api/login", views.login_view),
                path("api/users/<int:pk>", views.user_detail),
            ]
        """), encoding="utf-8")

        eps = extract_python_endpoints(src, tmp_path)
        assert len(eps) == 2
        assert all(e.framework == "django" for e in eps)
        assert all(e.method == "ANY" for e in eps)

    def test_fastapi_with_path_params(self, tmp_path: Path):
        src = tmp_path / "app.py"
        src.write_text(textwrap.dedent("""\
            from fastapi import FastAPI
            app = FastAPI()

            @app.get("/users/{user_id}/orders/{order_id}")
            async def get_order(user_id: int, order_id: int):
                pass
        """), encoding="utf-8")

        eps = extract_python_endpoints(src, tmp_path)
        assert len(eps) == 1
        assert eps[0].path == "/users/:param/orders/:param"

    def test_nonexistent_file(self, tmp_path: Path):
        eps = extract_python_endpoints(tmp_path / "missing.py", tmp_path)
        assert eps == []

    def test_non_python_file(self, tmp_path: Path):
        src = tmp_path / "readme.md"
        src.write_text("# Hello", encoding="utf-8")
        eps = extract_python_endpoints(src, tmp_path)
        assert eps == []


# ── JS/TS API call extraction ──────────────────────────────────────────


class TestExtractJsApiCalls:
    def test_fetch_get(self, tmp_path: Path):
        src = tmp_path / "api.js"
        src.write_text(textwrap.dedent("""\
            async function loadUsers() {
                const resp = await fetch("/api/users");
                return resp.json();
            }
        """), encoding="utf-8")

        calls = extract_js_api_calls(src, tmp_path)
        assert len(calls) == 1
        assert calls[0].method == "GET"
        assert calls[0].path == "/api/users"
        assert calls[0].library == "fetch"

    def test_fetch_with_method(self, tmp_path: Path):
        src = tmp_path / "api.ts"
        src.write_text(textwrap.dedent("""\
            async function createUser() {
                const resp = await fetch("/api/users", {
                    method: "POST",
                    body: JSON.stringify({name: "x"})
                });
            }
        """), encoding="utf-8")

        calls = extract_js_api_calls(src, tmp_path)
        assert len(calls) == 1
        assert calls[0].method == "POST"

    def test_axios_get(self, tmp_path: Path):
        src = tmp_path / "service.ts"
        src.write_text(textwrap.dedent("""\
            const fetchData = async () => {
                const { data } = await axios.get("/api/items");
                return data;
            };
        """), encoding="utf-8")

        calls = extract_js_api_calls(src, tmp_path)
        assert len(calls) == 1
        assert calls[0].method == "GET"
        assert calls[0].library == "axios"

    def test_axios_post(self, tmp_path: Path):
        src = tmp_path / "service.js"
        src.write_text(textwrap.dedent("""\
            async function submitForm(data) {
                await axios.post("/api/submit", data);
            }
        """), encoding="utf-8")

        calls = extract_js_api_calls(src, tmp_path)
        assert len(calls) == 1
        assert calls[0].method == "POST"

    def test_template_literal_path(self, tmp_path: Path):
        src = tmp_path / "api.tsx"
        src.write_text(textwrap.dedent("""\
            async function getUser(id) {
                const resp = await fetch(`/api/users/${id}`);
                return resp.json();
            }
        """), encoding="utf-8")

        calls = extract_js_api_calls(src, tmp_path)
        assert len(calls) == 1
        assert calls[0].path == "/api/users/:param"

    def test_nonexistent_file(self, tmp_path: Path):
        calls = extract_js_api_calls(tmp_path / "missing.js", tmp_path)
        assert calls == []

    def test_non_js_file(self, tmp_path: Path):
        src = tmp_path / "readme.md"
        src.write_text("# Hello", encoding="utf-8")
        calls = extract_js_api_calls(src, tmp_path)
        assert calls == []

    def test_caller_node_from_function(self, tmp_path: Path):
        src = tmp_path / "client.js"
        src.write_text(textwrap.dedent("""\
            async function loadItems() {
                const resp = await fetch("/api/items");
                return resp.json();
            }
        """), encoding="utf-8")

        calls = extract_js_api_calls(src, tmp_path)
        assert len(calls) == 1
        assert "loadItems" in calls[0].caller_node


# ── Parameterized matching ─────────────────────────────────────────────


class TestMatchParameterized:
    def test_param_match(self):
        ep = ApiEndpoint(
            path="/users/:param", method="GET",
            handler_node="app.py::get_user", file="app.py", line=1,
        )
        endpoint_index = {"/users/:param": [ep]}
        result = _match_parameterized("/users/:param", endpoint_index)
        assert len(result) == 1

    def test_different_segment_count(self):
        ep = ApiEndpoint(
            path="/users/:param", method="GET",
            handler_node="app.py::get_user", file="app.py", line=1,
        )
        endpoint_index = {"/users/:param": [ep]}
        result = _match_parameterized("/users/:param/orders", endpoint_index)
        assert len(result) == 0


# ── Data classes ───────────────────────────────────────────────────────


class TestDataClasses:
    def test_api_endpoint_to_dict(self):
        ep = ApiEndpoint(
            path="/users", method="get", handler_node="app.py::f",
            file="app.py", line=5, framework="fastapi",
        )
        d = ep.to_dict()
        assert d["method"] == "GET"
        assert d["path"] == "/users"

    def test_api_endpoint_from_dict(self):
        d = {"path": "/x", "method": "POST", "handler_node": "a", "file": "a.py", "line": 1}
        ep = ApiEndpoint.from_dict(d)
        assert ep.method == "POST"

    def test_api_call_to_dict(self):
        c = ApiCall(
            path="/api/x", method="delete", caller_node="c.js::f",
            file="c.js", line=10, library="axios",
        )
        d = c.to_dict()
        assert d["method"] == "DELETE"

    def test_api_call_from_dict(self):
        d = {"path": "/x", "method": "GET", "caller_node": "a", "file": "a.js", "line": 1}
        c = ApiCall.from_dict(d)
        assert c.library == ""

    def test_report_format(self):
        r = ApiLinkReport()
        text = r.format()
        assert "0 links" in text

    def test_report_to_dict_summary(self):
        r = ApiLinkReport()
        d = r.to_dict()
        assert d["summary"]["total_endpoints"] == 0
        assert d["summary"]["linked"] == 0


# ── End-to-end linking ─────────────────────────────────────────────────


class TestLinkApiRoutes:
    def test_link_fastapi_to_fetch(self, tmp_path: Path):
        # Backend
        backend = tmp_path / "backend" / "app.py"
        backend.parent.mkdir()
        backend.write_text(textwrap.dedent("""\
            from fastapi import FastAPI
            app = FastAPI()

            @app.get("/api/users")
            async def list_users():
                return []

            @app.post("/api/users")
            async def create_user(data: dict):
                pass
        """), encoding="utf-8")

        # Frontend
        frontend = tmp_path / "frontend" / "api.js"
        frontend.parent.mkdir()
        frontend.write_text(textwrap.dedent("""\
            async function loadUsers() {
                const resp = await fetch("/api/users");
                return resp.json();
            }

            async function addUser(data) {
                await fetch("/api/users", { method: "POST", body: JSON.stringify(data) });
            }
        """), encoding="utf-8")

        report = link_api_routes(tmp_path)
        assert len(report.endpoints) == 2
        assert len(report.api_calls) == 2
        assert len(report.linked_edges) == 2
        assert len(report.unlinked_calls) == 0

    def test_unlinked_endpoints(self, tmp_path: Path):
        # Backend endpoint with no frontend caller
        backend = tmp_path / "app.py"
        backend.write_text(textwrap.dedent("""\
            from fastapi import FastAPI
            app = FastAPI()

            @app.get("/api/health")
            def health():
                return "ok"
        """), encoding="utf-8")

        report = link_api_routes(tmp_path)
        assert len(report.endpoints) == 1
        assert len(report.unlinked_endpoints) == 1
        assert len(report.linked_edges) == 0

    def test_unlinked_calls(self, tmp_path: Path):
        # Frontend call with no backend handler
        frontend = tmp_path / "client.js"
        frontend.write_text(textwrap.dedent("""\
            async function getData() {
                return fetch("/api/data");
            }
        """), encoding="utf-8")

        report = link_api_routes(tmp_path)
        assert len(report.api_calls) == 1
        assert len(report.unlinked_calls) == 1
        assert len(report.linked_edges) == 0

    def test_parameterized_matching(self, tmp_path: Path):
        backend = tmp_path / "app.py"
        backend.write_text(textwrap.dedent("""\
            from fastapi import FastAPI
            app = FastAPI()

            @app.get("/api/users/{user_id}")
            async def get_user(user_id: int):
                pass
        """), encoding="utf-8")

        frontend = tmp_path / "client.tsx"
        frontend.write_text(textwrap.dedent("""\
            async function fetchUser(id) {
                return fetch(`/api/users/${id}`);
            }
        """), encoding="utf-8")

        report = link_api_routes(tmp_path)
        assert len(report.linked_edges) == 1

    def test_method_mismatch_not_linked(self, tmp_path: Path):
        backend = tmp_path / "app.py"
        backend.write_text(textwrap.dedent("""\
            from fastapi import FastAPI
            app = FastAPI()

            @app.post("/api/items")
            async def create_item():
                pass
        """), encoding="utf-8")

        frontend = tmp_path / "client.js"
        frontend.write_text(textwrap.dedent("""\
            async function getItems() {
                return fetch("/api/items");
            }
        """), encoding="utf-8")

        report = link_api_routes(tmp_path)
        # GET call should not match POST endpoint
        assert len(report.linked_edges) == 0

    def test_django_any_matches_all(self, tmp_path: Path):
        backend = tmp_path / "urls.py"
        backend.write_text(textwrap.dedent("""\
            from django.urls import path
            from . import views
            urlpatterns = [
                path("api/items", views.items_view),
            ]
        """), encoding="utf-8")

        frontend = tmp_path / "client.js"
        frontend.write_text(textwrap.dedent("""\
            async function getItems() {
                return fetch("/api/items");
            }
        """), encoding="utf-8")

        report = link_api_routes(tmp_path)
        # Django ANY method should match any call
        assert len(report.linked_edges) == 1

    def test_explicit_source_files(self, tmp_path: Path):
        backend = tmp_path / "app.py"
        backend.write_text(textwrap.dedent("""\
            from fastapi import FastAPI
            app = FastAPI()

            @app.get("/api/test")
            def test_endpoint():
                pass
        """), encoding="utf-8")

        report = link_api_routes(tmp_path, source_files=[backend])
        assert len(report.endpoints) == 1
        assert len(report.api_calls) == 0
