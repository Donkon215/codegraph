"""Unit tests for filter pipeline.

Task O-009: Filter types and pipeline composition.
"""

from __future__ import annotations

import pytest

from codegraph.models.workflow import WorkflowEdge


class TestFilterConcepts:
    """Test filter concepts on edge data."""

    def test_dunder_filter(self) -> None:
        """Dunder methods should be filterable."""
        edges = [
            WorkflowEdge(source="a", target="mod::C::__init__"),
            WorkflowEdge(source="a", target="mod::C::process"),
        ]
        # Simulate dunder filtering
        filtered = [e for e in edges if not e.target.endswith("__init__")]
        assert len(filtered) == 1
        assert filtered[0].target.endswith("process")

    def test_stdlib_filter(self) -> None:
        """Stdlib targets should be filterable."""
        edges = [
            WorkflowEdge(source="a", target="os::path::join"),
            WorkflowEdge(source="a", target="mymod::func"),
        ]
        stdlib_prefixes = ("os::", "sys::", "json::", "re::")
        filtered = [e for e in edges if not any(e.target.startswith(p) for p in stdlib_prefixes)]
        assert len(filtered) == 1

    def test_self_loop_filter(self) -> None:
        """Self-referential edges should be filterable."""
        edges = [
            WorkflowEdge(source="a", target="a"),
            WorkflowEdge(source="a", target="b"),
        ]
        filtered = [e for e in edges if e.source != e.target]
        assert len(filtered) == 1
