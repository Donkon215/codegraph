"""Smoke test for Group C — AST extraction engine."""

import ast
from pathlib import Path

from codegraph.extractor import (
    parse_file,
    extract_file,
    extract_imports,
    extract_globals,
    extract_call_sites,
    compare_graphs,
    ScopeTree,
    resolve_call_target,
    CallSite,
    ImportInfo,
    _body_hash_node,
    _body_hash_source,
)
from codegraph.models.graph0 import Graph0, Graph0Node

root = Path(r"D:\codegraph")

# === C-001: parse_file ===
tree = parse_file(root / "codegraph" / "config.py")
assert tree is not None, "parse_file failed"
print("C-001 parse_file: OK")

# === C-008: extract_file ===
result = extract_file(root / "codegraph" / "config.py", root)
types_found = set(n.type for n in result.nodes)
assert "module" in types_found, "no module node"
assert "function" in types_found or "class" in types_found, "no func/class nodes"
print(f"C-008 extract_file: {len(result.nodes)} nodes, types={types_found}")

for n in result.nodes[:5]:
    print(f"  {n.type:10s} {n.id} (line {n.line})")

# === C-002/C-004: methods extracted from classes ===
result2 = extract_file(root / "codegraph" / "models" / "graph0.py", root)
method_nodes = [n for n in result2.nodes if n.type == "method"]
class_nodes = [n for n in result2.nodes if n.type == "class"]
assert len(class_nodes) > 0, "no class nodes in graph0.py"
assert len(method_nodes) > 0, "no method nodes in graph0.py"
print(f"C-002/C-004 methods: {len(method_nodes)} methods, {len(class_nodes)} classes")

# === C-005: nested functions ===
nested_src = '''
def outer():
    def inner():
        return 1
    return inner()
'''
nested_path = root / "_test_nested.py"
nested_path.write_text(nested_src, encoding="utf-8")
try:
    res_nested = extract_file(nested_path, root)
    nested_ids = [n.id for n in res_nested.nodes if n.type == "function"]
    assert any("outer::inner" in nid for nid in nested_ids), f"nested not found: {nested_ids}"
    print(f"C-005 nested functions: OK ({nested_ids})")
finally:
    nested_path.unlink(missing_ok=True)

# === C-007/C-027: module nodes + __init__.py ===
init_result = extract_file(root / "codegraph" / "__init__.py", root)
module_nodes = [n for n in init_result.nodes if n.type == "module"]
assert len(module_nodes) >= 1, "no module node for __init__.py"
assert module_nodes[0].id == "codegraph", f"__init__.py module id wrong: {module_nodes[0].id}"
print(f"C-007/C-027 __init__.py module ID: '{module_nodes[0].id}' OK")

# === C-013: decorators ===
deco_src = '''
import functools

@functools.lru_cache(maxsize=128)
def cached_fn(x):
    return x * 2

class MyClass:
    @staticmethod
    def static_method():
        pass

    @property
    def prop(self):
        return 42
'''
deco_path = root / "_test_deco.py"
deco_path.write_text(deco_src, encoding="utf-8")
try:
    res_deco = extract_file(deco_path, root)
    for n in res_deco.nodes:
        meta = getattr(n, "_metadata", None)
        if meta and meta.get("decorators"):
            print(f"C-013 decorators: {n.id} → {meta['decorators']}")
finally:
    deco_path.unlink(missing_ok=True)

# === C-014/C-015: params & return type ===
typed_src = '''
def greet(name: str, count: int = 1, *args, key: str = "hi", **kwargs) -> str:
    return name * count
'''
typed_path = root / "_test_typed.py"
typed_path.write_text(typed_src, encoding="utf-8")
try:
    res_typed = extract_file(typed_path, root)
    for n in res_typed.nodes:
        meta = getattr(n, "_metadata", None)
        if meta and meta.get("params"):
            print(f"C-014 params: {[p['name'] for p in meta['params']]}")
            print(f"C-015 return_type: {meta.get('return_type')}")
finally:
    typed_path.unlink(missing_ok=True)

# === C-016: imports ===
assert len(result.imports) > 0, "no imports found"
print(f"C-016 imports: {len(result.imports)} imports from config.py")

# === C-024: globals ===
print(f"C-024 globals: {len(result.globals)} globals from config.py")

# === C-010/C-011: body hash invariance ===
src1 = "def foo():\n    return 1\n"
src2 = "def foo():\n    return    1\n"  # extra whitespace
src3 = "def foo():\n    # comment\n    return 1\n"
h1 = _body_hash_source(src1)
h2 = _body_hash_source(src2)
h3 = _body_hash_source(src3)
assert h1 == h2, f"whitespace invariance failed: {h1} != {h2}"
assert h1 == h3, f"comment invariance failed: {h1} != {h3}"
print("C-010/C-011 body hash invariance: OK")

# Docstring invariance
src_no_doc = "def foo():\n    return 1\n"
src_with_doc = 'def foo():\n    """Does stuff."""\n    return 1\n'
h_no = _body_hash_source(src_no_doc)
h_doc = _body_hash_source(src_with_doc)
assert h_no == h_doc, f"docstring invariance failed: {h_no} != {h_doc}"
print("C-011 docstring invariance: OK")

# === C-012: logic change detection ===
src_a = "def foo():\n    return 1\n"
src_b = "def foo():\n    return 2\n"
src_c = "def foo():\n    if True:\n        return 1\n"
ha = _body_hash_source(src_a)
hb = _body_hash_source(src_b)
hc = _body_hash_source(src_c)
assert ha != hb, "changed return value should produce different hash"
assert ha != hc, "added control flow should produce different hash"
print("C-012 logic change detection: OK")

# === C-031: compare_graphs ===
n1 = Graph0Node(id="a::f", body_hash="aaaaa", file="a.py", type="function", line=1)
n2 = Graph0Node(id="a::g", body_hash="bbbbb", file="a.py", type="function", line=5)
n3 = Graph0Node(id="a::f", body_hash="ccccc", file="a.py", type="function", line=1)
old_g = Graph0(nodes=[n1, n2])
new_g = Graph0(nodes=[n3])
diff = compare_graphs(old_g, new_g)
assert diff.nodes_removed == ["a::g"], f"removed: {diff.nodes_removed}"
assert diff.nodes_modified == ["a::f"], f"modified: {diff.nodes_modified}"
assert diff.nodes_added == [], f"added: {diff.nodes_added}"
print("C-031 compare_graphs: OK")

# === C-026: ScopeTree ===
st = ScopeTree()
st.push("module", "main")
st.bind("helper", "utils.py::helper")
assert st.resolve("helper") == "utils.py::helper"
assert st.resolve("unknown") is None
st.pop()
print("C-026 ScopeTree: OK")

# === C-032: conditional code extraction ===
cond_src = '''
if __name__ == "__main__":
    def main():
        pass
'''
cond_path = root / "_test_cond.py"
cond_path.write_text(cond_src, encoding="utf-8")
try:
    res_cond = extract_file(cond_path, root)
    func_ids = [n.id for n in res_cond.nodes if n.type == "function"]
    assert any("main" in fid for fid in func_ids), f"conditional func not found: {func_ids}"
    print(f"C-032 conditional extraction: OK ({func_ids})")
finally:
    cond_path.unlink(missing_ok=True)

# === C-033: async-specific ===
async_src = '''
async def fetch_data(url: str) -> str:
    async with open_session() as session:
        return await session.get(url)
'''
async_path = root / "_test_async.py"
async_path.write_text(async_src, encoding="utf-8")
try:
    res_async = extract_file(async_path, root)
    async_nodes = [n for n in res_async.nodes if n.type == "function"]
    assert len(async_nodes) >= 1, "async function not extracted"
    meta = getattr(async_nodes[0], "_metadata", {})
    assert meta.get("is_async") is True, "not marked as async"
    print(f"C-033 async extraction: OK (is_async={meta.get('is_async')})")
finally:
    async_path.unlink(missing_ok=True)

# === C-034: determinism ===
r1 = extract_file(root / "codegraph" / "config.py", root)
r2 = extract_file(root / "codegraph" / "config.py", root)
ids1 = [n.id for n in r1.nodes]
ids2 = [n.id for n in r2.nodes]
assert ids1 == ids2, "non-deterministic extraction"
print("C-034 determinism: OK")

print("\n=== ALL GROUP C SMOKE TESTS PASSED ===")
