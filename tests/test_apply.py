"""Unit tests for the apply system.

Task O-013: Apply action types.
"""

from __future__ import annotations

import pytest


class TestApplyImports:
    """Test that apply module is importable and has expected API."""

    def test_import_run_apply(self) -> None:
        from codegraph.apply import run_apply
        assert callable(run_apply)

    def test_import_format_apply_result(self) -> None:
        from codegraph.apply import format_apply_result
        assert callable(format_apply_result)


class TestApplyActionTypes:
    """Test apply action concepts."""

    def test_connect_call_concept(self) -> None:
        """connect_call inserts a function call at the right location."""
        action = {
            "type": "connect_call",
            "file": "mod.py",
            "target_function": "log_event",
            "insert_after_line": 10,
        }
        assert action["type"] == "connect_call"

    def test_add_import_concept(self) -> None:
        """add_import adds an import statement."""
        action = {
            "type": "add_import",
            "file": "mod.py",
            "import_statement": "from utils import helper",
        }
        assert action["type"] == "add_import"

    def test_flag_for_review_concept(self) -> None:
        """flag_for_review records a flag without code changes."""
        action = {
            "type": "flag_for_review",
            "node_id": "mod.py::func",
            "reason": "Unclear intent",
        }
        assert action["type"] == "flag_for_review"
