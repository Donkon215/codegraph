"""CLI tests for the architecture overview artifact (issue #67).

Covers:
* ``codegraph build`` writes the stable community overview artifact
  (``.codegraph/architecture/community_overview.json``);
* ``partitions --overview --save`` persists the artifact;
* ``--save --json`` emits valid JSON only on stdout (save notice on stderr);
* ``--save`` without ``--overview`` is rejected.

All tests use tmp project roots only; no existing ``.codegraph`` user data is
touched.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from codegraph.cli.core import main

GRAPHS_DIR = Path(".codegraph") / "graphs"
WORKFLOW_DIR = Path(".codegraph") / "workflow"
ARCHITECTURE_DIR = Path(".codegraph") / "architecture"
ARTIFACT = ARCHITECTURE_DIR / "community_overview.json"


def _write_graph_views(root: Path) -> None:
    """Write minimal graph0/graph1/workflow views so ArchitectureGraph.load works."""
    (root / GRAPHS_DIR).mkdir(parents=True, exist_ok=True)
    (root / WORKFLOW_DIR).mkdir(parents=True, exist_ok=True)
    (root / GRAPHS_DIR / "graph0.json").write_text(
        json.dumps(
            {
                "format_version": 1,
                "graph_version": 1,
                "extracted_at": "",
                "source_files": [],
                "nodes": [
                    {"id": "a.py::A", "body_hash": "1", "file": "a.py", "type": "class", "line": 1},
                    {"id": "b.py::B", "body_hash": "2", "file": "b.py", "type": "class", "line": 1},
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (root / GRAPHS_DIR / "graph1.json").write_text(
        json.dumps({"format_version": 1, "nodes": []}, indent=2), encoding="utf-8"
    )
    (root / WORKFLOW_DIR / "workflow.json").write_text(
        json.dumps(
            {
                "format_version": 1,
                "built_at": "",
                "level": "function",
                "edges": [
                    {
                        "source": "a.py::A",
                        "target": "b.py::B",
                        "edge_type": "call",
                        "confidence": "static",
                        "source_detail": "",
                        "conditional": False,
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _invoke(args: list[str], root: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(root)
    runner = CliRunner()
    return runner.invoke(main, args, standalone_mode=False)


def test_build_writes_community_overview_artifact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """``codegraph build`` on a real project writes the overview artifact."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "__init__.py").write_text("", encoding="utf-8")
    (src / "payments.py").write_text("def charge():\n    return 1\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "smoke"\nversion = "0.1.0"\n', encoding="utf-8"
    )

    result = _invoke(["build"], tmp_path, monkeypatch)
    assert result.exit_code == 0, result.output

    artifact = tmp_path / ARTIFACT
    assert artifact.exists(), f"artifact not written: {artifact}"
    data = json.loads(artifact.read_text(encoding="utf-8"))
    assert "communities" in data
    assert "cross_community_links" in data
    assert "metrics" in data
    # Every community carries the new #67 fields.
    for community in data["communities"]:
        assert "files" in community
        assert "directories" in community
        assert "boundary_edges" in community


def test_partitions_overview_save_persists_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """``partitions --overview --save --json`` writes the artifact to disk."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "smoke"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    _write_graph_views(tmp_path)

    result = _invoke(["partitions", "--rebuild", "--overview", "--save", "--json"], tmp_path, monkeypatch)
    assert result.exit_code == 0, result.output

    artifact = tmp_path / ARTIFACT
    assert artifact.exists()
    saved = json.loads(artifact.read_text(encoding="utf-8"))
    printed = json.loads(result.output)
    assert saved == printed


def test_save_json_stdout_is_valid_json_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """``--save --json`` stdout is valid JSON only; the save notice is not
    emitted on stdout in JSON mode (machine-readable output stays clean)."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "smoke"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    _write_graph_views(tmp_path)

    result = _invoke(["partitions", "--rebuild", "--overview", "--save", "--json"], tmp_path, monkeypatch)
    assert result.exit_code == 0, result.output
    # stdout must be parseable as JSON and contain no save notice.
    data = json.loads(result.output)
    assert "communities" in data
    assert "Community overview saved" not in result.output
    # The artifact was still persisted.
    assert (tmp_path / ARTIFACT).exists()


def test_save_without_overview_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """``--save`` without ``--overview`` is rejected with a non-zero exit."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "smoke"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    _write_graph_views(tmp_path)

    result = _invoke(["partitions", "--save", "--json"], tmp_path, monkeypatch)
    assert result.exit_code != 0
