"""Tests for codegraph.arch_versioning — Architecture Versioning."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from codegraph.arch_versioning import (
    ArchVersion,
    ArchVersionDiff,
    save_version,
    list_versions,
    load_version,
    diff_versions,
    rollback_version,
    format_version_history,
)


# ── Fixtures ──────────────────────────────────────────────────────────

MINIMAL_SYSTEM = {
    "name": "test-system",
    "subsystems": [
        {"name": "core", "components": [{"name": "main"}]},
        {"name": "utils", "components": [{"name": "helpers"}]},
    ],
    "edges": [{"from": "core", "to": "utils"}],
    "constraints": [{"source": "utils", "target": "core",
                     "constraint_type": "forbidden"}],
}


@pytest.fixture
def project_with_arch(tmp_path):
    """Create a project with a system.json."""
    arch_dir = tmp_path / ".codegraph" / "architecture"
    arch_dir.mkdir(parents=True)
    (arch_dir / "system.json").write_text(
        json.dumps(MINIMAL_SYSTEM, indent=2))
    return tmp_path


# ── Data Classes ──────────────────────────────────────────────────────


class TestArchVersion:
    def test_basic(self):
        v = ArchVersion(version=1, timestamp="2024-01-01T00:00:00Z")
        d = v.to_dict()
        assert d["version"] == 1
        assert d["timestamp"] == "2024-01-01T00:00:00Z"

    def test_from_dict(self):
        d = {"version": 2, "timestamp": "2024-06-01",
             "description": "test", "score": 0.75}
        v = ArchVersion.from_dict(d)
        assert v.version == 2
        assert v.description == "test"
        assert v.score == 0.75


class TestArchVersionDiff:
    def test_empty_diff(self):
        d = ArchVersionDiff(from_version=1, to_version=2)
        assert d.added_subsystems == []
        assert d.removed_subsystems == []

    def test_format(self):
        d = ArchVersionDiff(
            from_version=1, to_version=2,
            added_subsystems=["api"],
            score_delta=0.05,
        )
        text = d.format()
        assert "v1" in text
        assert "v2" in text
        assert "api" in text

    def test_format_no_changes(self):
        d = ArchVersionDiff(from_version=1, to_version=2)
        text = d.format()
        assert "No structural changes" in text


# ── Save / Load ───────────────────────────────────────────────────────


class TestSaveVersion:
    def test_save_creates_snapshot(self, project_with_arch):
        v = save_version(project_with_arch, description="initial")
        assert v.version == 1
        assert v.description == "initial"
        assert v.subsystem_count == 2
        assert v.edge_count == 1
        assert v.constraint_count == 1

    def test_save_increments_version(self, project_with_arch):
        v1 = save_version(project_with_arch, description="v1")
        v2 = save_version(project_with_arch, description="v2")
        assert v1.version == 1
        assert v2.version == 2

    def test_save_no_system_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            save_version(tmp_path)


class TestLoadVersion:
    def test_load_existing(self, project_with_arch):
        save_version(project_with_arch, description="test")
        data = load_version(project_with_arch, 1)
        assert data is not None
        assert "subsystems" in data

    def test_load_missing(self, project_with_arch):
        assert load_version(project_with_arch, 999) is None


class TestListVersions:
    def test_empty(self, project_with_arch):
        versions = list_versions(project_with_arch)
        assert versions == []

    def test_after_saves(self, project_with_arch):
        save_version(project_with_arch, description="a")
        save_version(project_with_arch, description="b")
        versions = list_versions(project_with_arch)
        assert len(versions) == 2
        assert versions[0].description == "a"
        assert versions[1].description == "b"


# ── Diff ──────────────────────────────────────────────────────────────


class TestDiffVersions:
    def test_diff_same(self, project_with_arch):
        save_version(project_with_arch, description="v1")
        save_version(project_with_arch, description="v2")
        diff = diff_versions(project_with_arch, 1, 2)
        assert diff is not None
        assert diff.added_subsystems == []
        assert diff.removed_subsystems == []

    def test_diff_with_changes(self, project_with_arch):
        save_version(project_with_arch, description="before")
        # Modify system.json
        system_path = (project_with_arch / ".codegraph" / "architecture"
                       / "system.json")
        data = json.loads(system_path.read_text())
        data["subsystems"].append({"name": "api", "components": []})
        data["edges"].append({"from": "api", "to": "core"})
        system_path.write_text(json.dumps(data))
        save_version(project_with_arch, description="after")
        diff = diff_versions(project_with_arch, 1, 2)
        assert "api" in diff.added_subsystems

    def test_diff_missing_version(self, project_with_arch):
        assert diff_versions(project_with_arch, 1, 2) is None


# ── Rollback ──────────────────────────────────────────────────────────


class TestRollback:
    def test_rollback_restores(self, project_with_arch):
        save_version(project_with_arch, description="v1-original")
        # Modify
        system_path = (project_with_arch / ".codegraph" / "architecture"
                       / "system.json")
        data = json.loads(system_path.read_text())
        data["subsystems"].append({"name": "bad", "components": []})
        system_path.write_text(json.dumps(data))
        save_version(project_with_arch, description="v2-bad")
        # Rollback
        assert rollback_version(project_with_arch, 1) is True
        restored = json.loads(system_path.read_text())
        names = [s["name"] for s in restored["subsystems"]]
        assert "bad" not in names

    def test_rollback_missing(self, project_with_arch):
        assert rollback_version(project_with_arch, 999) is False


# ── Format ────────────────────────────────────────────────────────────


class TestFormatVersionHistory:
    def test_empty(self):
        text = format_version_history([])
        assert "No architecture versions" in text

    def test_with_versions(self):
        versions = [
            ArchVersion(version=1, timestamp="2024-01-01T00:00:00Z",
                        description="initial", grade="C",
                        subsystem_count=3, edge_count=5),
            ArchVersion(version=2, timestamp="2024-02-01T00:00:00Z",
                        description="added API", grade="B",
                        subsystem_count=4, edge_count=7),
        ]
        text = format_version_history(versions)
        assert "v1" in text
        assert "v2" in text
        assert "initial" in text
        assert "added API" in text
