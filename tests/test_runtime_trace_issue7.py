"""Regression tests for Issue #7: runtime trace parser created false edges.

Coverage.py proves which functions executed, not who called whom. These tests
assert that ``parse_trace_data`` no longer manufactures caller->callee edges
from source/declaration ordering, while the valid test->production coverage
relationships from ``build_test_edges`` are preserved.
"""

from __future__ import annotations

from codegraph.models.graph0 import Graph0, Graph0Node
from codegraph.models.workflow import WorkflowEdge
from codegraph.workflow import build_test_edges, parse_trace_data


def _node(nid: str, file: str, line: int) -> Graph0Node:
    return Graph0Node(id=nid, body_hash="h", file=file, type="function", line=line)


def _graph(nodes) -> Graph0:
    g = Graph0()
    for n in nodes:
        g.add_node(n)
    return g


def test_consecutive_source_order_functions_make_no_edges() -> None:
    # a, b, c declared in order and all executed.
    g = _graph([
        _node("src/m.py::a", "src/m.py", 1),
        _node("src/m.py::b", "src/m.py", 5),
        _node("src/m.py::c", "src/m.py", 10),
    ])
    cov = [{"file": "src/m.py", "executed_lines": [1, 5, 10]}]
    assert parse_trace_data(cov, g) == []


def test_a_calls_b_but_coverage_cannot_prove_it() -> None:
    # a calls b at runtime, both observed. Coverage still cannot prove the
    # caller->callee relationship, so no edge should be manufactured.
    g = _graph([
        _node("src/m.py::a", "src/m.py", 1),
        _node("src/m.py::b", "src/m.py", 5),
    ])
    cov = [{"file": "src/m.py", "executed_lines": [1, 5]}]
    assert parse_trace_data(cov, g) == []


def test_a_calls_b_then_c_does_not_create_b_to_c() -> None:
    # a() -> b(); a() -> c(). Coverage sees all three executed; the false
    # "b -> c" (and any) edge must not be produced.
    g = _graph([
        _node("src/m.py::a", "src/m.py", 1),
        _node("src/m.py::b", "src/m.py", 5),
        _node("src/m.py::c", "src/m.py", 10),
    ])
    cov = [{"file": "src/m.py", "executed_lines": [1, 5, 10]}]
    assert parse_trace_data(cov, g) == []


def test_independent_functions_make_no_edge() -> None:
    g = _graph([
        _node("src/x.py::a", "src/x.py", 1),
        _node("src/y.py::b", "src/y.py", 1),
    ])
    cov = [
        {"file": "src/x.py", "executed_lines": [1]},
        {"file": "src/y.py", "executed_lines": [1]},
    ]
    assert parse_trace_data(cov, g) == []


def test_declaration_order_not_call_order() -> None:
    # b is declared before a, but they never call each other.
    g = _graph([
        _node("src/m.py::b", "src/m.py", 1),
        _node("src/m.py::a", "src/m.py", 5),
    ])
    cov = [{"file": "src/m.py", "executed_lines": [1, 5]}]
    assert parse_trace_data(cov, g) == []


def test_empty_coverage_yields_no_edges() -> None:
    g = _graph([_node("src/m.py::a", "src/m.py", 1)])
    assert parse_trace_data([], g) == []


def test_valid_test_coverage_relationships_preserved() -> None:
    # build_test_edges (test -> production) is a legitimate coverage relationship
    # and must remain unchanged by the #7 fix.
    g = _graph([
        _node("tests/test_foo.py::test_foo", "tests/test_foo.py", 1),
        _node("src/foo.py::foo", "src/foo.py", 1),
    ])
    cov = [
        {"file": "tests/test_foo.py", "executed_lines": [1]},
        {"file": "src/foo.py", "executed_lines": [1]},
    ]
    edges = build_test_edges(cov, g)
    assert edges == [
        WorkflowEdge(
            source="tests/test_foo.py::test_foo",
            target="src/foo.py::foo",
            edge_type="test",
            confidence="test",
        )
    ]
