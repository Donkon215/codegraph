"""Issue #9 — equivalence of full-build index vs build->delta index.

For the same final source state, ``codegraph build`` and
``codegraph build -> codegraph delta`` must produce logically identical index
rows. These tests drive the REAL CLI in throwaway git repos and compare
canonical snapshots (see ``codegraph/index_snapshot.py``).

They currently FAIL on ``main`` because the delta path does not maintain every
table the way a full build does (``layers``, ``dependency_hashes``, and
symbol-universe-sensitive edges). The fix (workflow + index reconciliation)
must make every scenario below pass.
"""
from __future__ import annotations

import os
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
    p.write_text(text, encoding="utf-8")


def _make_repo(files: dict) -> Path:
    d = Path(tempfile.mkdtemp(prefix="cg9_"))
    _git(d, "init", "-q")
    for name, text in files.items():
        _write(d / name, text)
        _git(d, "add", name)
    _git(d, "commit", "-qm", "init")
    return d


def assert_equivalence(initial: dict, final: dict) -> None:
    """Build ``initial``, delta to ``final``; build ``final`` fresh; compare."""
    from codegraph.index_snapshot import diff_index_snapshots, snapshot_index

    delta_dir = _make_repo(initial)
    _cg(delta_dir, "build")
    for name, text in final.items():
        _write(delta_dir / name, text)
        _git(delta_dir, "add", name)
    for name in initial:
        if name not in final:
            _git(delta_dir, "rm", name)
    _cg(delta_dir, "delta")

    full_dir = _make_repo(final)
    _cg(full_dir, "build")

    diff = diff_index_snapshots(snapshot_index(delta_dir), snapshot_index(full_dir))
    if diff:
        import pprint

        pytest.fail("build<->delta index divergence:\n" + pprint.pformat(diff))


def test_modify_function_body():
    assert_equivalence({"a.py": "def f():\n    return 1\n"}, {"a.py": "def f():\n    return 2\n"})


def test_add_function():
    # caller references bar before bar exists; adding bar.py must resolve it.
    assert_equivalence(
        {"a.py": "def caller():\n    return bar()\n"},
        {"a.py": "def caller():\n    return bar()\n", "b.py": "def bar():\n    return 1\n"},
    )


def test_delete_function():
    assert_equivalence(
        {"a.py": "def caller():\n    return foo()\n", "b.py": "def foo():\n    return 1\n"},
        {"a.py": "def caller():\n    return 1\n"},
    )


def test_rename_function_resolution():
    # caller (a.py, unchanged) resolves `helper` to b.py::helper initially.
    # Rename b.py::helper -> helper2 and add c.py::helper. Final resolution
    # must move to c.py::helper, but a.py is NOT in the changed file set, so a
    # delta that only rebuilds changed files keeps a stale edge.
    assert_equivalence(
        {
            "a.py": "def caller():\n    return helper()\n",
            "b.py": "def helper():\n    return 1\n",
        },
        {
            "a.py": "def caller():\n    return helper()\n",
            "b.py": "def helper2():\n    return 1\n",
            "c.py": "def helper():\n    return 2\n",
        },
    )
