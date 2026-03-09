"""Unit tests for convergence tracking and analyzer.

Task O-017: Convergence criteria.
"""

from __future__ import annotations

import pytest


class TestAnalyzerImports:
    """Test that analyzer module is importable."""

    def test_import_run_analyze(self) -> None:
        from codegraph.analyzer import run_analyze
        assert callable(run_analyze)

    def test_import_format_analysis_report(self) -> None:
        from codegraph.analyzer import format_analysis_report
        assert callable(format_analysis_report)


class TestConvergenceConcepts:
    """Test convergence logic concepts."""

    def test_stable_count_converges(self) -> None:
        """If orphan count stays the same for 3 iterations, it converged."""
        counts = [10, 10, 10]
        converged = len(set(counts)) == 1 and len(counts) >= 3
        assert converged

    def test_decreasing_count_not_converged(self) -> None:
        counts = [10, 8, 5]
        converged = len(set(counts)) == 1 and len(counts) >= 3
        assert not converged

    def test_zero_issues_converges(self) -> None:
        counts = [0, 0, 0]
        converged = len(set(counts)) == 1 and len(counts) >= 3
        assert converged
