"""Smoke tests for Group C — AST extraction engine.

Each C-xxx item is one test function. Snippet sources are written into pytest's
tmp_path, so nothing is created inside the repository.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codegraph.extractor import (
    compare_graphs,
    extract_file,
    parse_file,
    ScopeTree,
    _body_hash_source,
)
from codegraph.models.graph0 import Graph0, Graph0Node

ROOT = Path(__file__).resolve().parents[1]  # the repo root, wherever it is checked out
CONFIG = ROOT / "codegraph" / "config.py"


@pytest.fixture(scope="module")
def config_result():
    return extract_file(CONFIG, ROOT)


def _extract_snippet(tmp_path: Path, name: str, src: str):
    path = tmp_path / name
    path.write_text(src, encoding="utf-8")
    return extract_file(path, tmp_path)


def test_c001_parse_file_returns_tree():
    assert parse_file(CONFIG) is not None


def test_c008_extract_file_finds_module_and_definitions(config_result):
    types_found = {n.type for n in config_result.nodes}
    assert "module" in types_found
    assert "function" in types_found or "class" in types_found


def test_c002_c004_methods_and_classes_extracted():
    result = extract_file(ROOT / "codegraph" / "models" / "graph0.py", ROOT)
    methods = [n for n in result.nodes if n.type == "method"]
    classes = [n for n in result.nodes if n.type == "class"]
    assert classes, "no class nodes in graph0.py"
    assert methods, "no method nodes in graph0.py"


def test_c005_nested_function_is_extracted(tmp_path):
    result = _extract_snippet(
        tmp_path,
        "nested.py",
        "def outer():\n    def inner():\n        return 1\n    return inner()\n",
    )
    function_ids = [n.id for n in result.nodes if n.type == "function"]
    assert any("outer::inner" in fid for fid in function_ids), function_ids


def test_c007_c027_init_module_id_is_package_name():
    result = extract_file(ROOT / "codegraph" / "__init__.py", ROOT)
    modules = [n for n in result.nodes if n.type == "module"]
    assert modules, "no module node for __init__.py"
    assert modules[0].id == "codegraph"


def test_c013_decorators_recorded_in_metadata(tmp_path):
    src = (
        "import functools\n\n"
        "@functools.lru_cache(maxsize=128)\n"
        "def cached_fn(x):\n"
        "    return x * 2\n\n"
        "class MyClass:\n"
        "    @staticmethod\n"
        "    def static_method():\n"
        "        pass\n\n"
        "    @property\n"
        "    def prop(self):\n"
        "        return 42\n"
    )
    result = _extract_snippet(tmp_path, "deco.py", src)
    with_decorators = [
        n for n in result.nodes if (getattr(n, "_metadata", None) or {}).get("decorators")
    ]
    assert with_decorators, "no node recorded any decorators"


def test_c014_c015_params_and_return_type_recorded(tmp_path):
    src = 'def greet(name: str, count: int = 1, *args, key: str = "hi", **kwargs) -> str:\n    return name * count\n'
    result = _extract_snippet(tmp_path, "typed.py", src)
    annotated = [n for n in result.nodes if (getattr(n, "_metadata", None) or {}).get("params")]
    assert annotated, "no node recorded params"
    meta = annotated[0]._metadata
    names = [p["name"] for p in meta["params"]]
    assert "name" in names and "count" in names
    assert meta.get("return_type") == "str"


def test_c016_imports_found_in_config(config_result):
    assert len(config_result.imports) > 0, "no imports found in config.py"


def test_c010_c011_body_hash_ignores_whitespace_and_comments():
    base = _body_hash_source("def foo():\n    return 1\n")
    assert base == _body_hash_source("def foo():\n    return    1\n")
    assert base == _body_hash_source("def foo():\n    # comment\n    return 1\n")


def test_c011_body_hash_ignores_docstring():
    without_doc = _body_hash_source("def foo():\n    return 1\n")
    with_doc = _body_hash_source('def foo():\n    """Does stuff."""\n    return 1\n')
    assert without_doc == with_doc


def test_c012_body_hash_detects_logic_change():
    base = _body_hash_source("def foo():\n    return 1\n")
    assert base != _body_hash_source("def foo():\n    return 2\n")
    assert base != _body_hash_source("def foo():\n    if True:\n        return 1\n")


def test_c031_compare_graphs_reports_removed_modified_added():
    old_graph = Graph0(nodes=[
        Graph0Node(id="a::f", body_hash="aaaaa", file="a.py", type="function", line=1),
        Graph0Node(id="a::g", body_hash="bbbbb", file="a.py", type="function", line=5),
    ])
    new_graph = Graph0(nodes=[
        Graph0Node(id="a::f", body_hash="ccccc", file="a.py", type="function", line=1),
    ])
    diff = compare_graphs(old_graph, new_graph)
    assert diff.nodes_removed == ["a::g"]
    assert diff.nodes_modified == ["a::f"]
    assert diff.nodes_added == []


def test_c026_scope_tree_resolves_bound_names():
    st = ScopeTree()
    st.push("module", "main")
    st.bind("helper", "utils.py::helper")
    assert st.resolve("helper") == "utils.py::helper"
    assert st.resolve("unknown") is None
    st.pop()


def test_c032_function_inside_main_guard_is_extracted(tmp_path):
    src = 'if __name__ == "__main__":\n    def main():\n        pass\n'
    result = _extract_snippet(tmp_path, "cond.py", src)
    function_ids = [n.id for n in result.nodes if n.type == "function"]
    assert any("main" in fid for fid in function_ids), function_ids


def test_c033_async_function_marked_async(tmp_path):
    src = (
        "async def fetch_data(url: str) -> str:\n"
        "    async with open_session() as session:\n"
        "        return await session.get(url)\n"
    )
    result = _extract_snippet(tmp_path, "async_fn.py", src)
    functions = [n for n in result.nodes if n.type == "function"]
    assert functions, "async function not extracted"
    assert (getattr(functions[0], "_metadata", None) or {}).get("is_async") is True


def test_c034_extraction_is_deterministic():
    first = [n.id for n in extract_file(CONFIG, ROOT).nodes]
    second = [n.id for n in extract_file(CONFIG, ROOT).nodes]
    assert first == second
