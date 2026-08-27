"""Unit tests for graph index operations.

Task O-016: Index build, query, consistency.
"""

from __future__ import annotations

import pytest
from typing import Dict, List

from codegraph.index import IndexStore


class _InstrumentedIndex(IndexStore):
    """IndexStore whose get_callees is backed by a dict and call-counted.

    Lets us observe how much of the graph the recursive traversal actually
    walks, without needing a live SQLite database.
    """

    def __init__(self, callees: Dict[str, List[str]]) -> None:
        self._callees = callees
        self.callee_calls = 0

    def get_callees(self, node_id: str) -> List[str]:
        self.callee_calls += 1
        return list(self._callees.get(node_id, []))


class TestIndexImports:
    """Test that index module is importable."""

    def test_import_index_store(self) -> None:
        from codegraph.index import IndexStore
        assert IndexStore is not None

    def test_import_build_all_indexes(self) -> None:
        from codegraph.index import build_all_indexes
        assert callable(build_all_indexes)

    def test_import_rebuild_index(self) -> None:
        from codegraph.index import rebuild_index
        assert callable(rebuild_index)

    def test_import_check_consistency(self) -> None:
        from codegraph.index import check_index_consistency
        assert callable(check_index_consistency)


class TestIndexConcepts:
    """Test index concepts without live database."""

    def test_index_store_context_manager(self) -> None:
        """IndexStore should support context manager protocol."""
        from codegraph.index import IndexStore
        assert hasattr(IndexStore, "__enter__")
        assert hasattr(IndexStore, "__exit__")

    def test_get_dependencies_recursive_respects_limit(self) -> None:
        """Traversal must stop at the limit, not walk the whole graph."""
        # A fans out to 5 callees, each of which fans out to 100 leaves.
        # Full traversal would touch ~505 nodes; a limit of 3 should only
        # walk the seed plus the first 3 discovered nodes.
        callees: Dict[str, List[str]] = {"A": [f"B{i}" for i in range(5)]}
        for i in range(5):
            callees[f"B{i}"] = [f"B{i}_leaf{j}" for j in range(100)]

        index = _InstrumentedIndex(callees)
        nodes, truncated = index.get_dependencies_recursive("A", limit=3)

        assert len(nodes) == 3
        assert truncated is True
        # Far fewer calls than the ~505 a full walk would require.
        assert index.callee_calls <= 5

    def test_get_dependencies_recursive_unlimited_returns_all(self) -> None:
        callees = {"A": ["B", "C"], "B": ["D"], "C": ["E"], "D": [], "E": []}
        index = _InstrumentedIndex(callees)
        nodes, truncated = index.get_dependencies_recursive("A")

        assert set(nodes) == {"B", "C", "D", "E"}
        assert truncated is False

    def test_get_dependencies_recursive_limit_equals_total(self) -> None:
        callees = {"A": ["B", "C"], "B": [], "C": []}
        index = _InstrumentedIndex(callees)
        nodes, truncated = index.get_dependencies_recursive("A", limit=2)

        assert set(nodes) == {"B", "C"}
        assert truncated is False
