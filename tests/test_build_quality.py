"""Tests for codegraph.build_quality — build defects a report can read (#79)."""

from __future__ import annotations

import json

from codegraph.build_quality import (
    BUILD_QUALITY_PATH,
    load_build_quality,
    record_build_quality,
    unresolved_call_summary,
)


def test_record_is_persisted_and_readable(tmp_path):
    record_build_quality(tmp_path, unresolved_calls=17)
    assert (tmp_path / BUILD_QUALITY_PATH).exists()
    assert load_build_quality(tmp_path)["unresolved_calls"] == 17


def test_stages_merge_without_clobbering_each_other(tmp_path):
    # Extraction writes collisions, the workflow builder writes unresolved
    # calls, in either order. Neither may erase the other.
    record_build_quality(tmp_path, collision_count=1)
    record_build_quality(tmp_path, unresolved_calls=17392)
    record_build_quality(tmp_path, collision_count=1)
    data = load_build_quality(tmp_path)
    assert data["collision_count"] == 1
    assert data["unresolved_calls"] == 17392


def test_summary_reports_unknown_rather_than_zero(tmp_path):
    # A report must never imply a clean build it cannot prove.
    assert unresolved_call_summary(None) == {
        "build_quality": "unknown",
        "unresolved_calls": None,
        "collisions": None,
        "warnings": None,
    }
    assert unresolved_call_summary({})["build_quality"] == "unknown"


def test_summary_counts_recorded_defects(tmp_path):
    record_build_quality(
        tmp_path,
        unresolved_calls=42,
        collision_ids=["a -> a[2]", "b -> b[2]"],
        warnings=["API route extraction failed"],
    )
    summary = unresolved_call_summary(load_build_quality(tmp_path))
    assert summary["build_quality"] == "recorded"
    assert summary["unresolved_calls"] == 42
    assert summary["collisions"] == 2
    assert summary["warnings"] == 1


def test_corrupt_record_is_replaced_not_fatal(tmp_path):
    path = tmp_path / BUILD_QUALITY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{broken", encoding="utf-8")
    assert load_build_quality(tmp_path) is None
    record_build_quality(tmp_path, unresolved_calls=1)
    assert load_build_quality(tmp_path)["unresolved_calls"] == 1


def test_saved_metrics_report_carries_build_quality(tmp_path):
    from codegraph.architecture_metrics import compute_architecture_metrics, save_report
    from codegraph.architecture_graph import ArchitectureGraph

    graph = ArchitectureGraph(
        nodes=[{"id": "a.py::A"}, {"id": "b.py::B"}],
        edges=[{"source": "a.py::A", "target": "b.py::B", "edge_type": "call"}],
    )
    record_build_quality(tmp_path, unresolved_calls=5)
    save_report(tmp_path, compute_architecture_metrics(graph))

    saved = json.loads((tmp_path / ".codegraph" / "architecture_metrics.json").read_text())
    quality = saved["metadata"]["build_quality"]
    assert quality["unresolved_calls"] == 5
    assert quality["build_quality"] == "recorded"


def test_saved_metrics_report_without_a_build_is_unknown(tmp_path):
    from codegraph.architecture_metrics import compute_architecture_metrics, save_report
    from codegraph.architecture_graph import ArchitectureGraph

    graph = ArchitectureGraph(
        nodes=[{"id": "a.py::A"}], edges=[],
    )
    save_report(tmp_path, compute_architecture_metrics(graph))
    saved = json.loads((tmp_path / ".codegraph" / "architecture_metrics.json").read_text())
    assert saved["metadata"]["build_quality"]["build_quality"] == "unknown"