"""Full-build regressions for stale derived references and orphaned intent."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from codegraph.constants import INDEX_DIR
from codegraph.storage import resolve_path

CODEGRAPH = Path(__file__).resolve().parents[1]
NODE_ID = "gone.py::old_service"


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(CODEGRAPH)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _cg(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        [sys.executable, "-m", "codegraph", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_env(),
        timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def _write_project(repo: Path) -> None:
    (repo / "pyproject.toml").write_text("[project]\nname='reconcile-fixture'\n", encoding="utf-8")
    (repo / "gone.py").write_text(
        "import requests\n\ndef old_service():\n    requests.get('https://example.test')\n",
        encoding="utf-8",
    )
    (repo / "keep.py").write_text("def keep():\n    return 1\n", encoding="utf-8")


def _assert_stale_references_removed(repo: Path, reason: str) -> None:
    graph1_path = resolve_path(repo, "graphs", "graph1.json")
    graph1 = json.loads(graph1_path.read_text(encoding="utf-8"))
    assert NODE_ID not in {node["id"] for node in graph1["nodes"]}

    runtime = json.loads(
        resolve_path(repo, "graphs", "graph3_runtime.json").read_text(encoding="utf-8")
    )
    assert "gone.py" not in {edge["source_file"] for edge in runtime["edges"]}

    module = json.loads(
        resolve_path(repo, "graphs", "graph_module.json").read_text(encoding="utf-8")
    )
    assert "gone.py" not in {node["id"] for node in module["nodes"]}
    assert all("gone.py" not in edge["source"] and "gone.py" not in edge["target"] for edge in module["edges"])

    system_layers = json.loads(
        resolve_path(repo, "architecture", "system_layers.json").read_text(encoding="utf-8")
    )
    assert NODE_ID not in {node_id for ids in system_layers["layers"].values() for node_id in ids}

    db_path = resolve_path(repo, INDEX_DIR, "codegraph.db")
    conn = sqlite3.connect(str(db_path))
    try:
        assert NODE_ID not in {row[0] for row in conn.execute("SELECT node_id FROM layers")}
    finally:
        conn.close()
    consistency = subprocess.run(
        [sys.executable, "-c", "from codegraph.index_maintenance import check_index_consistency; "
         "from pathlib import Path; import sys; errors = check_index_consistency(Path(sys.argv[1])); "
         "print(errors); sys.exit(bool(errors))", str(repo)],
        cwd=repo,
        capture_output=True,
        text=True,
        env=_env(),
        timeout=30,
    )
    assert consistency.returncode == 0, consistency.stdout + consistency.stderr

    archive = json.loads(
        resolve_path(repo, "graphs", "graph1_orphans.json").read_text(encoding="utf-8")
    )
    [record] = [item for item in archive["records"] if item["node"]["id"] == NODE_ID]
    assert record["reason"] == reason
    assert record["node"]["intent"] == "preserve this human-authored purpose"

    prune_output = _cg(repo, "prune")
    assert NODE_ID in prune_output
    assert reason in prune_output
    assert "nothing deleted" in prune_output


@pytest.mark.parametrize(
    ("change", "reason"),
    [("delete", "deleted_from_source"), ("ignore", "excluded_by_discovery")],
)
def test_full_build_reconciles_all_derived_graphs_and_preserves_intent(change: str, reason: str) -> None:
    with tempfile.TemporaryDirectory(prefix=".test_reconcile_build_", dir=CODEGRAPH) as folder:
        repo = Path(folder)
        _write_project(repo)
        _cg(repo, "build")
        _cg(
            repo,
            "annotate",
            "--node", NODE_ID,
            "--intent", "preserve this human-authored purpose",
            "--author", "human",
        )

        if change == "delete":
            (repo / "gone.py").unlink()
        else:
            (repo / ".gitignore").write_text("gone.py\n", encoding="utf-8")

        build_output = _cg(repo, "build")
        assert "Graph_1 reconciled:" in build_output, build_output
        _assert_stale_references_removed(repo, reason)
