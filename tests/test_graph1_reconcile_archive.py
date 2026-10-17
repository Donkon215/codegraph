"""Safety and report regressions for Graph_1 reconciliation (#58/#59)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from codegraph.annotator import (
    list_orphans,
    orphan_store_path,
    prune_graph1,
    reconcile_graph1,
    restore_orphan,
)
from codegraph.models.graph0 import Graph0, Graph0Node
from codegraph.models.graph1 import Graph1, Graph1Node


def _g0(*nodes: Graph0Node, extracted_at: str = "2026-10-15T12:00:00Z") -> Graph0:
    return Graph0(
        extracted_at=extracted_at,
        source_files=sorted({node.file for node in nodes}),
        nodes=list(nodes),
    )


def _node(node_id: str, file: str) -> Graph0Node:
    return Graph0Node(id=node_id, body_hash="abc", file=file, type="function", line=1)


def test_prune_reports_reasons_and_never_mutates_graph1(tmp_path: Path) -> None:
    (tmp_path / "live.py").write_text("def live(): pass\n", encoding="utf-8")
    (tmp_path / "ignored.py").write_text("def ignored(): pass\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
    live = _node("live.py::live", "live.py")
    deleted = Graph1Node(id="gone.py::gone", intent="preserve this intent", last_seen_graph0="v1")
    ignored = Graph1Node(id="ignored.py::ignored", intent="preserve this too", last_seen_graph0="v1")
    never_valid = Graph1Node(id="live.py::typo", last_seen_graph0="")
    graph1 = Graph1(nodes=[deleted, ignored, never_valid])
    before = graph1.to_json()

    report = prune_graph1(_g0(live), graph1, tmp_path)

    assert {entry["id"]: entry["reason"] for entry in report.entries} == {
        "gone.py::gone": "deleted_from_source",
        "ignored.py::ignored": "excluded_by_discovery",
        "live.py::typo": "never_valid",
    }
    assert all(entry["file"] and entry["last_seen_graph0"] for entry in report.entries)
    assert graph1.to_json() == before
    assert not orphan_store_path(tmp_path).exists()


def test_reconcile_archives_annotations_before_removing_stale_overlay(tmp_path: Path) -> None:
    old_file = tmp_path / "deleted.py"
    old_file.write_text("def task(): pass\n", encoding="utf-8")
    old_node = _node("deleted.py::task", "deleted.py")
    previous = _g0(old_node, extracted_at="2026-10-14T08:30:00Z")
    old_file.unlink()
    current = _g0(_node("keep.py::keep", "keep.py"), extracted_at="2026-10-15T08:30:00Z")
    graph1 = Graph1(nodes=[Graph1Node(
        id=old_node.id,
        intent="keep the human meaning",
        intent_author="human",
        intent_version=3,
        intent_timestamp="2026-10-10T00:00:00Z",
        tags=["billing"],
        arch_layer="service",
        last_seen_graph0=previous.extracted_at,
    )])

    report = reconcile_graph1(current, graph1, tmp_path, previous)

    assert report.removed_ids == [old_node.id]
    assert report.archived_count == 1
    assert not graph1.has_node(old_node.id)
    [record] = list_orphans(tmp_path)
    assert record["node"]["intent"] == "keep the human meaning"
    assert record["node"]["intent_author"] == "human"
    assert record["node"]["tags"] == ["billing"]
    assert record["node"]["arch_layer"] == "service"
    assert record["reason"] == "deleted_from_source"
    assert record["original_path"] == "deleted.py"
    assert record["last_seen_graph0"] == previous.extracted_at
    assert record["detected_at"]

    report = prune_graph1(current, graph1, tmp_path)
    assert report.entries == [{
        "id": old_node.id,
        "file": "deleted.py",
        "reason": "deleted_from_source",
        "last_seen_graph0": previous.extracted_at,
    }]


def test_reconcile_is_idempotent_and_restore_requires_exact_live_node(tmp_path: Path) -> None:
    old_file = tmp_path / "revived.py"
    old_file.write_text("def task(): pass\n", encoding="utf-8")
    node = _node("revived.py::task", "revived.py")
    previous = _g0(node)
    old_file.unlink()
    graph1 = Graph1(nodes=[Graph1Node(id=node.id, intent="preserved intent")])
    current = _g0(_node("keep.py::keep", "keep.py"), extracted_at="2026-10-16T12:00:00Z")

    reconcile_graph1(current, graph1, tmp_path, previous)
    first = orphan_store_path(tmp_path).read_bytes()
    second_report = reconcile_graph1(current, graph1, tmp_path, previous)
    assert second_report.removed_count == 0
    assert orphan_store_path(tmp_path).read_bytes() == first

    [record] = list_orphans(tmp_path)
    with pytest.raises(ValueError, match="not present in Graph_0"):
        restore_orphan(tmp_path, record["orphan_id"], current, graph1)

    old_file.write_text("def task(): pass\n", encoding="utf-8")
    live = _g0(
        node,
        _node("keep.py::keep", "keep.py"),
        extracted_at="2026-10-17T12:00:00Z",
    )
    restored = restore_orphan(tmp_path, record["orphan_id"], live, graph1)
    assert restored.intent == "preserved intent"
    assert graph1.has_node(node.id)
    assert len(list_orphans(tmp_path)) == 1  # restore keeps the audit record


def test_orphan_records_are_reverified_against_the_current_graph(tmp_path: Path) -> None:
    """A record must stop reading "unresolved" once its file is gone (#80)."""
    gone = tmp_path / "gone.py"
    gone.write_text("def task(): pass\n", encoding="utf-8")
    node = _node("gone.py::task", "gone.py")
    previous = _g0(node)
    gone.unlink()

    graph1 = Graph1(nodes=[Graph1Node(id=node.id, intent="keep me")])
    current = _g0(_node("keep.py::keep", "keep.py"))
    reconcile_graph1(current, graph1, tmp_path, previous)

    [record] = list_orphans(tmp_path)
    # Classified at creation, not left sitting at "unresolved".
    assert record["status"] == "vanished"
    assert record["reason"] == "deleted_from_source"
    # last_seen_graph0 still names the build that actually contained the node.
    assert record["last_seen_graph0"] == previous.extracted_at

    # A rebuild that finds the node again marks it resolved.
    back = tmp_path / "gone.py"
    back.write_text("def task(): pass\n", encoding="utf-8")
    revived = _g0(node, _node("keep.py::keep", "keep.py"), extracted_at="2026-10-18T12:00:00Z")
    report = reconcile_graph1(revived, Graph1(), tmp_path, previous)
    assert report.resolved_count == 1
    [record] = list_orphans(tmp_path)
    assert record["status"] == "resolved"


def test_reverify_does_not_run_against_an_empty_graph0(tmp_path: Path) -> None:
    """An empty build must not mark the whole archive vanished (#80 data loss)."""
    gone = tmp_path / "gone.py"
    gone.write_text("def task(): pass\n", encoding="utf-8")
    node = _node("gone.py::task", "gone.py")
    previous = _g0(node)
    gone.unlink()

    graph1 = Graph1(nodes=[Graph1Node(id=node.id, intent="keep me")])
    reconcile_graph1(_g0(_node("keep.py::keep", "keep.py")), graph1, tmp_path, previous)
    before = list_orphans(tmp_path)

    reconcile_graph1(_g0(extracted_at="2026-10-19T12:00:00Z"), graph1, tmp_path, previous)
    # The archive is byte-identical: no record was reclassified by an empty build.
    assert list_orphans(tmp_path) == before


def test_empty_graph0_and_malformed_archive_do_not_remove_annotations(tmp_path: Path) -> None:
    path = tmp_path / "module.py"
    path.write_text("def f(): pass\n", encoding="utf-8")
    node = _node("module.py::f", "module.py")
    previous = _g0(node)
    graph1 = Graph1(nodes=[Graph1Node(id=node.id, intent="do not lose me")])

    empty_report = reconcile_graph1(
        _g0(extracted_at="2026-10-16T12:00:00Z"), graph1, tmp_path, previous,
    )
    assert empty_report.removed_count == 0
    assert graph1.has_node(node.id)

    path.unlink()
    archive = orphan_store_path(tmp_path)
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_text("{broken", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        reconcile_graph1(
            _g0(_node("keep.py::keep", "keep.py")), graph1, tmp_path, previous,
        )
    assert graph1.has_node(node.id)
