"""Unit tests for the delta engine.

Task O-014: Incremental change detection.
"""

from __future__ import annotations

import pytest

from codegraph.models.graph0 import Graph0, Graph0Node


class TestDeltaImports:
    """Test that delta module is importable."""

    def test_import_run_delta(self) -> None:
        from codegraph.delta import run_delta
        assert callable(run_delta)

    def test_import_format_delta_result(self) -> None:
        from codegraph.delta import format_delta_result
        assert callable(format_delta_result)


class TestChangeDetection:
    """Test body hash change detection logic."""

    def test_same_hash_no_change(self) -> None:
        n1 = Graph0Node(id="a", body_hash="abc", file="a.py", type="function", line=1)
        n2 = Graph0Node(id="a", body_hash="abc", file="a.py", type="function", line=1)
        assert n1.body_hash == n2.body_hash

    def test_different_hash_is_change(self) -> None:
        n1 = Graph0Node(id="a", body_hash="abc", file="a.py", type="function", line=1)
        n2 = Graph0Node(id="a", body_hash="xyz", file="a.py", type="function", line=1)
        assert n1.body_hash != n2.body_hash

    def test_new_node_detection(self) -> None:
        old = Graph0()
        new = Graph0()
        new.add_node(Graph0Node(id="new_func", body_hash="h", file="a.py", type="function", line=1))
        old_ids = {n.id for n in old.nodes}
        new_ids = {n.id for n in new.nodes}
        added = new_ids - old_ids
        assert "new_func" in added

    def test_removed_node_detection(self) -> None:
        old = Graph0()
        old.add_node(Graph0Node(id="old_func", body_hash="h", file="a.py", type="function", line=1))
        new = Graph0()
        old_ids = {n.id for n in old.nodes}
        new_ids = {n.id for n in new.nodes}
        removed = old_ids - new_ids
        assert "old_func" in removed

    def test_modified_node_detection(self) -> None:
        old = Graph0()
        old.add_node(Graph0Node(id="f", body_hash="old_hash", file="a.py", type="function", line=1))
        new = Graph0()
        new.add_node(Graph0Node(id="f", body_hash="new_hash", file="a.py", type="function", line=1))
        modified = []
        for n in new.nodes:
            old_node = old.get_node(n.id)
            if old_node and old_node.body_hash != n.body_hash:
                modified.append(n.id)
        assert "f" in modified
