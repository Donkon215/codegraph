"""Issue #3 regression — dependencies() must STOP traversal at --limit.

Historical bug: dependencies() walked the whole reachable graph and only cut the
returned list afterwards. On large or cyclic graphs that wasted work and could
loop. The fix (IndexStore.get_dependencies_recursive) BREAKS the BFS as soon as
the configured number of dependency nodes is discovered.

This test proves the traversal itself stops: get_callees is never invoked for any
node beyond the limit. A mere post-hoc truncation would still fetch callees for
every reachable node before slicing the result.
"""
from __future__ import annotations

from codegraph.index import IndexStore


def _chain(n: int) -> dict:
    return {f"a{i}": [f"a{i + 1}"] for i in range(n - 1)}


def _fake_store(callees: dict):
    """Minimal stand-in supplying the only collaborator get_dependencies_recursive uses."""

    class _Fake:
        def get_callees(self, node_id: str):
            return callees.get(node_id, [])

    return _Fake()


def test_dependencies_traversal_stops_at_limit():
    callees = _chain(100)
    seen: list[str] = []

    class _Recording:
        def get_callees(self, node_id: str):
            seen.append(node_id)
            return callees.get(node_id, [])

    store = _Recording()
    nodes, _ = IndexStore.get_dependencies_recursive(store, "a0", limit=3)

    assert nodes == ["a1", "a2", "a3"], nodes
    # Proof of early stop: callees of nodes past the limit are never fetched.
    # If the old bug were present (walk everything, then truncate), get_callees
    # would have been called for a3, a4, ... a98 to fill the result list first.
    assert "a3" not in seen, f"traversal fetched callees past the limit: {seen}"
    assert "a99" not in seen


def test_dependencies_truncated_flag_set_when_more_pending():
    # a0 fans out to four leaves; with limit=2 the BFS stops after two deps and
    # the queue still holds the remaining undiscovered nodes -> truncated=True.
    callees = {"a0": ["a1", "a2", "a3", "a4"]}

    class _Recording:
        def get_callees(self, node_id: str):
            return callees.get(node_id, [])

    store = _Recording()
    nodes, truncated = IndexStore.get_dependencies_recursive(store, "a0", limit=2)
    assert nodes == ["a1", "a2"], nodes
    assert truncated is True


def test_dependencies_cycle_terminates():
    callees = _chain(3)  # a0 -> a1 -> a2
    callees["a1"] = ["a0"]  # close a cycle a1 -> a0

    store = _fake_store(callees)
    # Must terminate (no infinite loop) even with a limit smaller than the cycle.
    nodes, _ = IndexStore.get_dependencies_recursive(store, "a0", limit=2)
    assert "a0" not in nodes  # start node excluded from results
    assert "a1" in nodes
