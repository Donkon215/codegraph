"""Regression test for codegraph/cli/architecture.py: partitions --rebuild --overview.

Verifies that `codegraph partitions --rebuild --overview` persists the rebuilt
partitions (manifest + node mapping) instead of returning before save_partitions,
matching the existing `partitions --rebuild` flow.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from codegraph.cli import main
from codegraph.config import find_project_root

_GRAPH0 = {
    "format_version": 1,
    "graph_version": 1,
    "nodes": [
        {"id": "src/data.py::fetch_data", "body_hash": "1", "file": "src/data.py",
         "type": "function", "line": 1},
        {"id": "src/signal.py::generate_signal", "body_hash": "2", "file": "src/signal.py",
         "type": "function", "line": 1},
        {"id": "src/trade.py::execute_order", "body_hash": "3", "file": "src/trade.py",
         "type": "function", "line": 1},
    ],
    "edges": [
        {"source": "src/data.py::fetch_data", "target": "src/signal.py::generate_signal",
         "edge_type": "call", "confidence": "static"},
        {"source": "src/signal.py::generate_signal", "target": "src/trade.py::execute_order",
         "edge_type": "call", "confidence": "static"},
    ],
}


def _write_graphs(root: Path) -> None:
    graphs = root / ".codegraph" / "graphs"
    graphs.mkdir(parents=True, exist_ok=True)
    (graphs / "graph0.json").write_text(json.dumps(_GRAPH0, indent=2), encoding="utf-8")
    (graphs / "graph1.json").write_text('{"format_version": 1, "nodes": []}', encoding="utf-8")
    (graphs / "workflow.json").write_text(
        json.dumps({"format_version": 1, "edges": _GRAPH0["edges"]}, indent=2),
        encoding="utf-8",
    )


def test_partitions_rebuild_overview_persists_manifest_and_mapping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "data.py").write_text("def fetch_data(): ...\n", encoding="utf-8")
    (tmp_path / "src" / "signal.py").write_text("def generate_signal(): ...\n", encoding="utf-8")
    (tmp_path / "src" / "trade.py").write_text("def execute_order(): ...\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "sample"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    _write_graphs(tmp_path)

    monkeypatch.chdir(tmp_path)
    assert find_project_root() == tmp_path

    partitions_dir = tmp_path / ".codegraph" / "partitions"
    assert not partitions_dir.exists()

    runner = CliRunner()
    result = runner.invoke(
        main, ["partitions", "--rebuild", "--overview"], catch_exceptions=False,
        obj={"verbose": False},
    )
    assert result.exit_code == 0, result.output

    manifest_path = partitions_dir / "manifest.json"
    mapping_path = partitions_dir / "node_partition_map.json"
    assert manifest_path.is_file(), "manifest.json must be saved by rebuild+overview"
    assert mapping_path.is_file(), "node_partition_map.json must be saved by rebuild+overview"

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["partition_ids"], "manifest must list at least one partition"
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    assert mapping, "node partition mapping must be non-empty"
