"""Regression tests for Issue #6: incremental index loses test relationships.

Builds a real index via the public path and verifies that ``codegraph delta``
preserves the same test relationships that a fresh full rebuild would produce.
"""

from __future__ import annotations

from codegraph.index import IndexStore, build_all_indexes
from codegraph.index_delta import update_index_delta
from codegraph.models.graph0 import Graph0, Graph0Node
from codegraph.models.graph1 import Graph1
from codegraph.models.workflow import Workflow, WorkflowEdge


def _node(nid: str, file: str) -> Graph0Node:
    return Graph0Node(id=nid, body_hash="h", file=file, type="function", line=1)


def _test_edge(test_id: str, prod_id: str) -> WorkflowEdge:
    return WorkflowEdge(source=test_id, target=prod_id, edge_type="test", confidence="static")


def _store(graph0: Graph0, workflow: Workflow, root) -> None:
    build_all_indexes(graph0, Graph1(), workflow, root)


def _tests_for(root, node_id: str):
    with IndexStore(root) as store:
        return sorted(store.get_tests_for_node(node_id))


def _all_tests(root) -> set:
    with IndexStore(root) as store:
        out = set()
        for nid in store.get_all_node_ids():
            for tid in store.get_tests_for_node(nid):
                out.add((tid, nid))
        return out


FOO = _node("src/foo.py::foo", "src/foo.py")
BAR = _node("src/bar.py::bar", "src/bar.py")
TEST_FOO = _node("tests/test_foo.py::test_foo", "tests/test_foo.py")
TEST_BAR = _node("tests/test_bar.py::test_bar", "tests/test_bar.py")


def _base_graph():
    g0 = Graph0()
    for n in (FOO, BAR, TEST_FOO, TEST_BAR):
        g0.add_node(n)
    wf = Workflow()
    wf.add_edge(_test_edge(TEST_FOO.id, FOO.id))
    wf.add_edge(_test_edge(TEST_BAR.id, BAR.id))
    return g0, wf


def test_production_modified_preserves_relationship(tmp_path) -> None:
    g0, wf = _base_graph()
    _store(g0, wf, tmp_path)

    # Modify the production node (body hash changes, id stays).
    changed = Graph0()
    f = _node(FOO.id, FOO.file)
    f.body_hash = "h2"
    for n in (f, BAR, TEST_FOO, TEST_BAR):
        changed.add_node(n)
    update_index_delta([FOO.id], changed, Graph1(), wf, tmp_path, build_all_indexes)

    assert _tests_for(tmp_path, FOO.id) == [TEST_FOO.id]


def test_test_node_modified_preserves_relationship(tmp_path) -> None:
    g0, wf = _base_graph()
    _store(g0, wf, tmp_path)

    changed = Graph0()
    t = _node(TEST_FOO.id, TEST_FOO.file)
    t.body_hash = "h2"
    for n in (FOO, BAR, t, TEST_BAR):
        changed.add_node(n)
    update_index_delta([TEST_FOO.id], changed, Graph1(), wf, tmp_path, build_all_indexes)

    assert _tests_for(tmp_path, FOO.id) == [TEST_FOO.id]


def test_production_deleted_removes_relationship(tmp_path) -> None:
    g0, wf = _base_graph()
    _store(g0, wf, tmp_path)

    # Remove foo from graph and workflow.
    updated = Graph0()
    for n in (BAR, TEST_FOO, TEST_BAR):
        updated.add_node(n)
    uwf = Workflow()
    uwf.add_edge(_test_edge(TEST_BAR.id, BAR.id))
    update_index_delta([FOO.id], updated, Graph1(), uwf, tmp_path, build_all_indexes)

    assert _tests_for(tmp_path, FOO.id) == []


def test_test_deleted_removes_relationship(tmp_path) -> None:
    g0, wf = _base_graph()
    _store(g0, wf, tmp_path)

    updated = Graph0()
    for n in (FOO, BAR, TEST_BAR):
        updated.add_node(n)
    uwf = Workflow()
    uwf.add_edge(_test_edge(TEST_BAR.id, BAR.id))
    update_index_delta([TEST_FOO.id], updated, Graph1(), uwf, tmp_path, build_all_indexes)

    assert TEST_FOO.id not in _tests_for(tmp_path, FOO.id)


def test_multiple_changed_nodes_correct(tmp_path) -> None:
    g0, wf = _base_graph()
    _store(g0, wf, tmp_path)

    changed = Graph0()
    f = _node(FOO.id, FOO.file); f.body_hash = "h2"
    b = _node(BAR.id, BAR.file); b.body_hash = "h2"
    for n in (f, b, TEST_FOO, TEST_BAR):
        changed.add_node(n)
    update_index_delta([FOO.id, BAR.id], changed, Graph1(), wf, tmp_path, build_all_indexes)

    assert _tests_for(tmp_path, FOO.id) == [TEST_FOO.id]
    assert _tests_for(tmp_path, BAR.id) == [TEST_BAR.id]


def test_unrelated_relationship_untouched(tmp_path) -> None:
    g0, wf = _base_graph()
    _store(g0, wf, tmp_path)

    changed = Graph0()
    f = _node(FOO.id, FOO.file); f.body_hash = "h2"
    for n in (f, BAR, TEST_FOO, TEST_BAR):
        changed.add_node(n)
    update_index_delta([FOO.id], changed, Graph1(), wf, tmp_path, build_all_indexes)

    # bar was not changed; its test relationship must remain.
    assert _tests_for(tmp_path, BAR.id) == [TEST_BAR.id]


def test_repeated_delta_no_duplicates(tmp_path) -> None:
    g0, wf = _base_graph()
    _store(g0, wf, tmp_path)

    changed = Graph0()
    f = _node(FOO.id, FOO.file); f.body_hash = "h2"
    for n in (f, BAR, TEST_FOO, TEST_BAR):
        changed.add_node(n)
    update_index_delta([FOO.id], changed, Graph1(), wf, tmp_path, build_all_indexes)
    update_index_delta([FOO.id], changed, Graph1(), wf, tmp_path, build_all_indexes)

    result = _tests_for(tmp_path, FOO.id)
    assert result == [TEST_FOO.id]
    assert len(result) == len(set(result))


def test_incremental_matches_full_rebuild(tmp_path) -> None:
    g0, wf = _base_graph()
    _store(g0, wf, tmp_path)

    # Simulate a delta: foo changed.
    updated = Graph0()
    f = _node(FOO.id, FOO.file); f.body_hash = "h2"
    for n in (f, BAR, TEST_FOO, TEST_BAR):
        updated.add_node(n)
    update_index_delta([FOO.id], updated, Graph1(), wf, tmp_path, build_all_indexes)
    delta_tests = _all_tests(tmp_path)

    # Fresh full rebuild from the same updated graph.
    _store(updated, wf, tmp_path)
    full_tests = _all_tests(tmp_path)

    assert delta_tests == full_tests
    assert (TEST_FOO.id, FOO.id) in delta_tests
