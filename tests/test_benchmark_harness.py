"""Smoke test for the real-project scaling benchmark used by scheduled CI."""

from __future__ import annotations

from benchmarks.index_benchmark import benchmark_codegraph_project


def test_codegraph_benchmark_runs_build_delta_and_measures_process_memory() -> None:
    result = benchmark_codegraph_project(1_000)

    assert result["requested_functions"] == 1_000
    assert result["graph_nodes_after_build"] == 1_010
    assert result["graph_nodes_after_delta"] == 1_011
    assert result["build_seconds"] > 0
    assert result["delta_seconds"] > 0
    assert isinstance(result["peak_rss_bytes"], int)
    assert result["peak_rss_bytes"] > 0
