"""T8 — production index consistency checker (Issue #9).

The checker must detect *logical* divergence, not just row-count parity. A row
like ``A -> B`` rewritten to ``A -> C`` keeps the same count but is wrong; the
canonical snapshot/diff machinery (index_snapshot) catches it.

These tests drive the REAL CLI in a throwaway git repo and then call
``check_index_consistency`` directly.
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

CODEGRAPH = Path(__file__).resolve().parents[1]
PYTHON = sys.executable


def _env() -> dict:
    return dict(os.environ, PYTHONPATH=str(CODEGRAPH), PYTHONIOENCODING="utf-8")


def _git(cwd: Path, *args: str) -> None:
    env = {
        **_env(),
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t.com",
    }
    r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, env=env)
    if r.returncode != 0:
        raise RuntimeError(f"git {args} failed: {r.stderr[-500:]}")


def _cg(cwd: Path, *args: str) -> None:
    r = subprocess.run(
        [PYTHON, "-m", "codegraph", *args], cwd=str(cwd), capture_output=True, text=True, env=_env()
    )
    if r.returncode != 0:
        raise RuntimeError(f"codegraph {args} failed: {r.stderr[-800:]}")


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _make_repo(files: dict) -> Path:
    d = Path(tempfile.mkdtemp(prefix="cg9_consist_"))
    _git(d, "init", "-q")
    for name, text in files.items():
        _write(d / name, text)
        _git(d, "add", name)
    _git(d, "commit", "-qm", "init")
    return d


def _index_db(cwd: Path) -> Path:
    from codegraph.index_maintenance import _index_dir

    return _index_dir(cwd) / "codegraph.db"


def _consistency(cwd: Path):
    from codegraph.index_maintenance import check_index_consistency

    return check_index_consistency(cwd)


def _repo_with_edges() -> dict:
    # Explicit import so the cross-file call resolves into a real edge.
    return {
        "a.py": "from b import helper\n\n\ndef caller():\n    return helper()\n",
        "b.py": "def helper():\n    return 1\n",
    }


def test_clean_index_is_consistent():
    repo = _make_repo(_repo_with_edges())
    _cg(repo, "build")
    issues = _consistency(repo)
    assert issues == [], [ (i.table, i.message) for i in issues ]


def test_corrupted_callee_same_count_detected():
    repo = _make_repo(_repo_with_edges())
    _cg(repo, "build")

    # Rewrite the callee target but keep the row count identical.
    db = _index_db(repo)
    conn = sqlite3.connect(str(db))
    conn.execute("UPDATE callees SET callee_id='c.py::ghost' WHERE node_id='a.py::caller'")
    conn.commit()
    conn.close()

    issues = _consistency(repo)
    tables = {i.table for i in issues}
    assert "callees" in tables, [ (i.table, i.message) for i in issues ]


def test_corrupted_caller_same_count_detected():
    repo = _make_repo(_repo_with_edges())
    _cg(repo, "build")

    db = _index_db(repo)
    conn = sqlite3.connect(str(db))
    conn.execute("UPDATE callers SET caller_id='x.py::ghost' WHERE node_id='b.py::helper'")
    conn.commit()
    conn.close()

    issues = _consistency(repo)
    tables = {i.table for i in issues}
    assert "callers" in tables, [ (i.table, i.message) for i in issues ]


def test_corrupted_node_layer_same_count_detected():
    repo = _make_repo(_repo_with_edges())
    _cg(repo, "build")

    db = _index_db(repo)
    conn = sqlite3.connect(str(db))
    # Flip a layer value; layers row count is unchanged.
    conn.execute("UPDATE layers SET layer=0 WHERE node_id='a.py::caller'")
    conn.commit()
    conn.close()

    issues = _consistency(repo)
    tables = {i.table for i in issues}
    assert "layers" in tables, [ (i.table, i.message) for i in issues ]


def test_cas_failure_does_not_false_diverge(monkeypatch):
    # If CAS is unavailable when the reference snapshot is built, the checker must
    # fall back to a structural comparison rather than report a false divergence
    # on the dependency_hash column (concern #2 hardening).
    repo = _make_repo(_repo_with_edges())
    _cg(repo, "build")

    import codegraph.cas as cas_mod

    def _boom(*_a, **_k):
        raise RuntimeError("CAS down")

    monkeypatch.setattr(cas_mod, "run_cas_pipeline", _boom)

    issues = _consistency(repo)
    tables = {i.table for i in issues}
    assert "nodes" not in tables, [ (i.table, i.message) for i in issues ]
    assert "dependency_hashes" not in tables, [ (i.table, i.message) for i in issues ]
