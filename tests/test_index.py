"""Unit tests for graph index operations.

Task O-016: Index build, query, consistency.
"""

from __future__ import annotations

import pytest


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
