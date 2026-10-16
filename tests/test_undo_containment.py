"""Regression: undo_last_apply must never write outside the project root."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from codegraph.apply import run_apply, undo_last_apply
from codegraph.storage import resolve_path


def _write_undo_info(project_root: Path, files: dict[str, str]) -> None:
    undo_dir = resolve_path(project_root, "undo")
    undo_dir.mkdir(parents=True, exist_ok=True)
    (undo_dir / "last_apply.json").write_text(
        json.dumps({"timestamp": "t", "files": files, "actions": 1}),
        encoding="utf-8",
    )


def test_undo_refuses_target_outside_project(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("original", encoding="utf-8")

    undo_dir = resolve_path(project, "undo")
    undo_dir.mkdir(parents=True, exist_ok=True)
    (undo_dir / "bak.txt").write_text("attacker", encoding="utf-8")
    _write_undo_info(project, {str(outside): str(undo_dir / "bak.txt")})

    undo_last_apply(project)

    assert outside.read_text(encoding="utf-8") == "original"


def test_undo_restores_target_inside_project(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    target = project / "mod.py"
    target.write_text("changed", encoding="utf-8")

    undo_dir = resolve_path(project, "undo")
    undo_dir.mkdir(parents=True, exist_ok=True)
    (undo_dir / "mod.py.bak").write_text("restored", encoding="utf-8")
    _write_undo_info(project, {str(target): str(undo_dir / "mod.py.bak")})

    assert undo_last_apply(project) is True
    assert target.read_text(encoding="utf-8") == "restored"


def test_undo_resolves_relative_path_against_project_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A relative entry must resolve against the project root, not the CWD."""
    project = tmp_path / "project"
    (project / "sub").mkdir(parents=True)
    target = project / "sub" / "mod.py"
    target.write_text("changed", encoding="utf-8")

    undo_dir = resolve_path(project, "undo")
    undo_dir.mkdir(parents=True, exist_ok=True)
    (undo_dir / "mod.py").write_text("restored", encoding="utf-8")
    _write_undo_info(project, {"sub/mod.py": str(undo_dir / "mod.py")})

    monkeypatch.chdir(tmp_path)  # a CWD elsewhere must not redirect the restore
    assert undo_last_apply(project) is True
    assert target.read_text(encoding="utf-8") == "restored"


def test_undo_refuses_dotdot_traversal(tmp_path: Path) -> None:
    """Same class of escape as a symlink, but runnable without symlink privileges."""
    project = tmp_path / "project"
    (project / "sub").mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("original", encoding="utf-8")

    undo_dir = resolve_path(project, "undo")
    undo_dir.mkdir(parents=True, exist_ok=True)
    (undo_dir / "x.txt").write_text("attacker", encoding="utf-8")
    _write_undo_info(project, {"sub/../../outside.txt": str(undo_dir / "x.txt")})

    undo_last_apply(project)

    assert outside.read_text(encoding="utf-8") == "original"


def test_undo_refuses_symlink_escaping_project(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("original", encoding="utf-8")
    link = project / "link.py"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this platform")

    undo_dir = resolve_path(project, "undo")
    undo_dir.mkdir(parents=True, exist_ok=True)
    (undo_dir / "link.py").write_text("attacker", encoding="utf-8")
    _write_undo_info(project, {str(link): str(undo_dir / "link.py")})

    undo_last_apply(project)

    assert outside.read_text(encoding="utf-8") == "original"


def test_undo_survives_malformed_metadata(tmp_path: Path) -> None:
    """Bad JSON must not raise out of undo_last_apply."""
    project = tmp_path / "project"
    project.mkdir()
    undo_dir = resolve_path(project, "undo")
    undo_dir.mkdir(parents=True, exist_ok=True)
    (undo_dir / "last_apply.json").write_text("{not json", encoding="utf-8")

    try:
        undo_last_apply(project)
    except json.JSONDecodeError:
        pytest.fail("malformed undo metadata raised instead of failing safely")


def test_undo_restores_file_after_real_apply(
    initialized_project: Path, sample_graph0: dict,
) -> None:
    """Round trip through run_apply: backups and undo metadata come from the
    real workflow, not from hand-written JSON."""
    from codegraph.models.agent_response import AgentResponse, RepairAction
    from codegraph.models.graph0 import Graph0, Graph0Node
    from codegraph.services import GraphStore
    from codegraph.storage import get_graph_version

    project = initialized_project
    target = project / "src" / "trade.py"
    original = target.read_text(encoding="utf-8")

    GraphStore(project).save_graph0(Graph0(nodes=[
        Graph0Node(id=n["id"], body_hash=n["body_hash"], file=n["file"],
                   type=n["type"], line=n["line"])
        for n in sample_graph0["nodes"]
    ]))
    response = AgentResponse(
        graph_version=get_graph_version(project),
        repairs=[RepairAction(
            node="src/trade.py::execute_order",
            action="add_import",
            target="src.data",
            reason="round-trip test",
        )],
    )
    response_file = project / "agent_response.json"
    response_file.write_text(response.to_json(), encoding="utf-8")

    result = run_apply(response_file, project, skip_plan_check=True)

    assert result.files_modified, "apply did not modify anything — nothing to undo"
    assert target.read_text(encoding="utf-8") != original
    assert (resolve_path(project, "undo") / "last_apply.json").exists()

    assert undo_last_apply(project) is True
    assert target.read_text(encoding="utf-8") == original
