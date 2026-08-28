"""Regression tests for Issue #2: delta must detect staged-but-uncommitted changes.

These tests build a throwaway git repository inside a pytest tmp_path so they
never touch the developer's real working tree.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from codegraph.delta import get_changed_files


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@codegraph.dev")
    _git(repo, "config", "user.name", "codegraph test")
    _git(repo, "config", "commit.gpgsign", "false")
    return repo


def _commit(repo: Path, name: str, content: str) -> str:
    (repo / name).write_text(content, encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", f"add {name}")
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path):
    return _make_repo(tmp_path)


def test_unstaged_modification_detected(repo: Path) -> None:
    base = _commit(repo, "a.py", "x = 1\n")
    (repo / "a.py").write_text("x = 2\n", encoding="utf-8")
    changed = get_changed_files(repo, since_commit=base)
    assert "a.py" in changed.modified


def test_staged_modification_detected(repo: Path) -> None:
    base = _commit(repo, "a.py", "x = 1\n")
    (repo / "a.py").write_text("x = 2\n", encoding="utf-8")
    _git(repo, "add", "a.py")
    changed = get_changed_files(repo, since_commit=base)
    assert "a.py" in changed.modified


def test_staged_deletion_detected(repo: Path) -> None:
    base = _commit(repo, "a.py", "x = 1\n")
    _git(repo, "rm", "-q", "a.py")
    changed = get_changed_files(repo, since_commit=base)
    assert "a.py" in changed.deleted


def test_staged_rename_detected(repo: Path) -> None:
    base = _commit(repo, "a.py", "x = 1\n")
    _git(repo, "mv", "a.py", "b.py")
    changed = get_changed_files(repo, since_commit=base)
    assert ("a.py", "b.py") in changed.renamed


def test_committed_staged_unstaged_combined(repo: Path) -> None:
    base = _commit(repo, "a.py", "x = 1\n")
    # Committed change: add a new file and move HEAD forward.
    head = _commit(repo, "b.py", "y = 1\n")
    # Staged change relative to HEAD.
    (repo / "a.py").write_text("x = 2\n", encoding="utf-8")
    _git(repo, "add", "a.py")
    # Unstaged change relative to HEAD (not staged).
    (repo / "b.py").write_text("y = 2\n", encoding="utf-8")
    changed = get_changed_files(repo, since_commit=base)
    assert "b.py" in changed.added            # committed
    assert "a.py" in changed.modified         # staged
    assert "b.py" in changed.modified         # unstaged
    # No path should appear twice within a single list.
    assert len(changed.modified) == len(set(changed.modified))
    assert len(changed.added) == len(set(changed.added))
