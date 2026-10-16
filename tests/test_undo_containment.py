"""Undo and apply safety regressions."""

from __future__ import annotations

import json
import multiprocessing
from pathlib import Path

import pytest

from codegraph.apply import (
    ApplyResult,
    _acquire_lock,
    _create_backups,
    _release_lock,
    _save_undo,
    run_apply,
    undo_last_apply,
)
from codegraph.exceptions import CodegraphError
from codegraph.storage import resolve_path


def _write_undo(project: Path, files: dict[str, str]) -> Path:
    undo_dir = resolve_path(project, "undo")
    undo_dir.mkdir(parents=True, exist_ok=True)
    path = undo_dir / "last_apply.json"
    path.write_text(json.dumps({"timestamp": "test", "files": files}), encoding="utf-8")
    return undo_dir


def _race_to_acquire_lock(project: str, barrier, results) -> None:
    barrier.wait()
    try:
        _acquire_lock(Path(project))
    except CodegraphError:
        results.put("blocked")
    else:
        results.put("acquired")


def test_undo_rejects_absolute_and_dotdot_escapes(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("original", encoding="utf-8")
    undo_dir = _write_undo(project, {
        str(outside): "backup.txt",
        "nested/../../outside.txt": "backup.txt",
    })
    (undo_dir / "backup.txt").write_text("attacker", encoding="utf-8")

    assert undo_last_apply(project) is False
    assert outside.read_text(encoding="utf-8") == "original"
    assert (undo_dir / "last_apply.json").exists()


def test_undo_resolves_relative_paths_against_root(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    (project / "sub").mkdir(parents=True)
    target = project / "sub" / "mod.py"
    target.write_text("changed", encoding="utf-8")
    undo_dir = _write_undo(project, {"sub/mod.py": "mod.py.bak"})
    (undo_dir / "mod.py.bak").write_text("restored", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert undo_last_apply(project) is True
    assert target.read_text(encoding="utf-8") == "restored"


def test_undo_rejects_symlink_escape(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("original", encoding="utf-8")
    target = project / "link.txt"
    try:
        target.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable on this platform")
    undo_dir = _write_undo(project, {"link.txt": "link.bak"})
    (undo_dir / "link.bak").write_text("attacker", encoding="utf-8")

    assert undo_last_apply(project) is False
    assert outside.read_text(encoding="utf-8") == "original"


def test_undo_fails_safely_on_malformed_metadata(tmp_path: Path) -> None:
    project = tmp_path / "project"
    undo_dir = resolve_path(project, "undo")
    undo_dir.mkdir(parents=True)
    (undo_dir / "last_apply.json").write_text("{bad", encoding="utf-8")
    assert undo_last_apply(project) is False


def test_undo_backup_names_do_not_collide_on_equal_basenames(tmp_path: Path) -> None:
    project = tmp_path / "project"
    first = project / "src" / "utils.py"
    second = project / "tests" / "utils.py"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_text("source version", encoding="utf-8")
    second.write_text("test version", encoding="utf-8")

    backups = _create_backups({first, second}, project)
    assert len({path.name for path in backups.values()}) == 2
    _save_undo(project, backups, ApplyResult())
    first.write_text("changed source", encoding="utf-8")
    second.write_text("changed test", encoding="utf-8")

    assert undo_last_apply(project) is True
    assert first.read_text(encoding="utf-8") == "source version"
    assert second.read_text(encoding="utf-8") == "test version"


def test_apply_lock_is_exclusive_and_not_overwritten(tmp_path: Path) -> None:
    _acquire_lock(tmp_path)
    lock_path = resolve_path(tmp_path, ".apply.lock")
    original = lock_path.read_text(encoding="utf-8")
    with pytest.raises(CodegraphError, match="lock"):
        _acquire_lock(tmp_path)
    assert lock_path.read_text(encoding="utf-8") == original
    _release_lock(tmp_path)


def test_concurrent_apply_lock_race_has_exactly_one_winner(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    results = context.Queue()
    workers = [
        context.Process(target=_race_to_acquire_lock,
                        args=(str(tmp_path), barrier, results))
        for _ in range(2)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=10)

    assert all(worker.exitcode == 0 for worker in workers)
    outcomes = sorted([results.get(timeout=2), results.get(timeout=2)])
    assert outcomes == ["acquired", "blocked"]
    _release_lock(tmp_path)


def test_real_apply_and_undo_round_trip_restores_exact_bytes(
    initialized_project: Path, sample_graph0: dict,
) -> None:
    from codegraph.models.agent_response import AgentResponse, RepairAction
    from codegraph.models.graph0 import Graph0, Graph0Node
    from codegraph.services import GraphStore
    from codegraph.storage import get_graph_version

    project = initialized_project
    target = project / "src" / "trade.py"
    original = target.read_bytes()
    GraphStore(project).save_graph0(Graph0(nodes=[
        Graph0Node(id=node["id"], body_hash=node["body_hash"], file=node["file"],
                   type=node["type"], line=node["line"])
        for node in sample_graph0["nodes"]
    ]))
    response = AgentResponse(
        graph_version=get_graph_version(project),
        repairs=[RepairAction(
            node="src/trade.py::execute_order",
            action="add_import",
            target="src.data",
            reason="undo round-trip test",
        )],
    )
    response_file = project / "response.json"
    response_file.write_text(response.to_json(), encoding="utf-8")

    result = run_apply(response_file, project, skip_plan_check=True)

    assert result.files_modified
    assert target.read_bytes() != original
    assert undo_last_apply(project) is True
    assert target.read_bytes() == original
