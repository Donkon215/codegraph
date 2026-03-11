"""Tests for the JavaScript/TypeScript/React language extractor."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from codegraph.extractors.javascript import (
    JavaScriptExtractor,
    _extract_js_file,
    _line_of,
    _resolve_js_import,
)
from codegraph.models.graph0 import Graph0Node


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    """Create a minimal React project layout under *tmp_path*."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "components").mkdir()
    (src / "hooks").mkdir()

    (src / "App.tsx").write_text(textwrap.dedent("""\
        import React from 'react';
        import { Button } from './components/Button';
        import { useAuth } from './hooks/useAuth';

        export default function App() {
            const { user } = useAuth();
            return <div><Button label="hi" /></div>;
        }
    """), encoding="utf-8")

    (src / "components" / "Button.tsx").write_text(textwrap.dedent("""\
        import React from 'react';

        interface ButtonProps {
            label: string;
            onClick?: () => void;
        }

        export const Button = ({ label, onClick }: ButtonProps) => {
            return <button onClick={onClick}>{label}</button>;
        };
    """), encoding="utf-8")

    (src / "hooks" / "useAuth.ts").write_text(textwrap.dedent("""\
        import { useState } from 'react';

        export function useAuth() {
            const [user, setUser] = useState(null);
            return { user };
        }
    """), encoding="utf-8")

    (src / "api.ts").write_text(textwrap.dedent("""\
        import axios from 'axios';
        const API = '/api';
        export const login = async (u: string, p: string) => {
            return axios.post(`${API}/login`, { u, p });
        };
    """), encoding="utf-8")

    return tmp_path


class TestJavaScriptExtractor:
    """Test JavaScriptExtractor public API."""

    def test_supported_extensions(self, tmp_path: Path) -> None:
        ext = JavaScriptExtractor(tmp_path)
        exts = ext.supported_extensions()
        assert ".tsx" in exts
        assert ".js" in exts
        assert ".ts" in exts

    def test_extract_nodes_react_component(self, project: Path) -> None:
        ext = JavaScriptExtractor(project)
        nodes = ext.extract_nodes(project / "src" / "App.tsx")

        ids = {n.id for n in nodes}
        assert "src/App.tsx" in ids  # module node
        assert "src/App.tsx::App" in ids  # function component

    def test_extract_nodes_arrow_function(self, project: Path) -> None:
        ext = JavaScriptExtractor(project)
        nodes = ext.extract_nodes(project / "src" / "components" / "Button.tsx")

        ids = {n.id for n in nodes}
        assert "src/components/Button.tsx::Button" in ids
        assert "src/components/Button.tsx::ButtonProps" in ids

    def test_extract_nodes_hook(self, project: Path) -> None:
        ext = JavaScriptExtractor(project)
        nodes = ext.extract_nodes(project / "src" / "hooks" / "useAuth.ts")

        ids = {n.id for n in nodes}
        assert "src/hooks/useAuth.ts::useAuth" in ids

    def test_extract_edges_imports(self, project: Path) -> None:
        ext = JavaScriptExtractor(project)
        app = project / "src" / "App.tsx"
        nodes = ext.extract_nodes(app)
        edges = ext.extract_edges(app, nodes)

        targets = {e.target for e in edges}
        assert "react" in targets
        assert "src/components/Button.tsx" in targets
        assert "src/hooks/useAuth.ts" in targets

    def test_extract_all_returns_result(self, project: Path) -> None:
        ext = JavaScriptExtractor(project)
        result = ext.extract_all(project / "src" / "api.ts")

        assert len(result.nodes) >= 2  # module + login
        assert any(imp.module == "axios" for imp in result.imports)

    def test_body_hash_is_populated(self, project: Path) -> None:
        ext = JavaScriptExtractor(project)
        nodes = ext.extract_nodes(project / "src" / "App.tsx")
        for n in nodes:
            assert n.body_hash, f"body_hash empty for {n.id}"
            assert len(n.body_hash) == 5

    def test_node_types(self, project: Path) -> None:
        ext = JavaScriptExtractor(project)
        nodes = ext.extract_nodes(project / "src" / "components" / "Button.tsx")
        type_map = {n.id: n.type for n in nodes}
        assert type_map["src/components/Button.tsx"] == "module"
        assert type_map["src/components/Button.tsx::Button"] == "function"
        assert type_map["src/components/Button.tsx::ButtonProps"] == "class"

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        ext = JavaScriptExtractor(tmp_path)
        nodes = ext.extract_nodes(tmp_path / "nonexistent.tsx")
        assert nodes == []

    def test_class_declaration(self, tmp_path: Path) -> None:
        (tmp_path / "Widget.tsx").write_text(
            "export class Widget extends React.Component {\n"
            "  render() { return <div/>; }\n"
            "}\n",
            encoding="utf-8",
        )
        ext = JavaScriptExtractor(tmp_path)
        nodes = ext.extract_nodes(tmp_path / "Widget.tsx")
        ids = {n.id for n in nodes}
        assert "Widget.tsx::Widget" in ids
        assert any(n.type == "class" for n in nodes if n.id == "Widget.tsx::Widget")


class TestResolveJsImport:
    """Test relative import resolution."""

    def test_resolves_relative_tsx(self, project: Path) -> None:
        result = _resolve_js_import(
            "./components/Button",
            project / "src" / "App.tsx",
            project,
        )
        assert result == "src/components/Button.tsx"

    def test_resolves_relative_ts(self, project: Path) -> None:
        result = _resolve_js_import(
            "./hooks/useAuth",
            project / "src" / "App.tsx",
            project,
        )
        assert result == "src/hooks/useAuth.ts"

    def test_keeps_npm_packages(self, project: Path) -> None:
        result = _resolve_js_import(
            "react",
            project / "src" / "App.tsx",
            project,
        )
        assert result == "react"

    def test_keeps_scoped_packages(self, project: Path) -> None:
        result = _resolve_js_import(
            "@tanstack/react-query",
            project / "src" / "App.tsx",
            project,
        )
        assert result == "@tanstack/react-query"


class TestLineOf:
    """Test _line_of helper."""

    def test_first_line(self) -> None:
        assert _line_of("hello\nworld", 0) == 1

    def test_second_line(self) -> None:
        assert _line_of("hello\nworld", 6) == 2

    def test_third_line(self) -> None:
        assert _line_of("a\nb\nc", 4) == 3
