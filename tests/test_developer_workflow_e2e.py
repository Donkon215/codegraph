"""Issue #10 — end-to-end developer workflow regression test.

Drives the REAL CLI through the stateful workflow
``build -> change -> delta -> query/analyze -> repeat`` in a throwaway git
repo, and asserts the on-disk index stays consistent (equivalent to a fresh
``build``) and the call graph reflects each edit at every stage.

Copies the small CLI/repo helpers locally (does not touch existing tests).
"""
from __future__ import annotations

import json
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
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _make_repo(files: dict) -> Path:
    d = Path(tempfile.mkdtemp(prefix="cg10_e2e_"))
    _git(d, "init", "-q")
    for name, text in files.items():
        _write(d / name, text)
        _git(d, "add", name)
    _git(d, "commit", "-qm", "init")
    return d


def _consistency(cwd: Path):
    from codegraph.index_maintenance import check_index_consistency

    return check_index_consistency(cwd)


def _query_count(cwd: Path, expr: str) -> int:
    r = subprocess.run(
        [PYTHON, "-m", "codegraph", "query", "--format", "count", expr],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=_env(),
    )
    if r.returncode != 0:
        raise RuntimeError(f"query {expr} failed: {r.stderr[-800:]}")
    return int(r.stdout.strip().splitlines()[-1].strip())


def _query_text(cwd: Path, expr: str) -> str:
    r = subprocess.run(
        [PYTHON, "-m", "codegraph", "query", expr],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=_env(),
    )
    if r.returncode != 0:
        raise RuntimeError(f"query {expr} failed: {r.stderr[-800:]}")
    return r.stdout


def _analyze_json(cwd: Path) -> dict:
    r = subprocess.run(
        [PYTHON, "-m", "codegraph", "analyze", "--json"],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=_env(),
    )
    if r.returncode != 0:
        raise RuntimeError(f"analyze failed: {r.stderr[-800:]}")
    out = r.stdout
    s = out.find("{"); e = out.rfind("}")
    return json.loads(out[s:e + 1])


# Node ids use package-qualified imports so the extractor resolves cross-file
# calls into real edges (bare calls do not resolve across files here).
UTIL = "app/util.py::util"
CORE = "app/core.py::helper"
MAIN = "app/main.py::main"
SIDE = "app/side.py::side"
NEWMOD = "app/newmod.py::newfn"

FILES_INIT = {
    "app/util.py": "def util():\n    return 42\n",
    "app/core.py": "from app.util import util\n\n\ndef helper():\n    return util()\n",
    "app/main.py": "from app.core import helper\n\n\ndef main():\n    return helper()\n",
    "app/side.py": "from app.core import helper\n\n\ndef side():\n    return helper()\n",
}


def test_clean_build_is_consistent():
    repo = _make_repo(
        {"a.py": "def f():\n    return 1\n", "b.py": "from a import f\n\n\ndef g():\n    return f()\n"}
    )
    _cg(repo, "build")
    assert _consistency(repo) == [], "fresh build must be consistent"


def test_developer_workflow_e2e():
    repo = _make_repo(FILES_INIT)

    # Stage 1: build -> consistent.
    _cg(repo, "build")
    assert _consistency(repo) == [], "post-build index must be consistent"

    # Stage 2: query callers(helper) == 2 (main + side); analyze clean.
    assert _query_count(repo, f"callers({CORE})") == 2
    report = _analyze_json(repo)
    assert report["orphans"] == 0, "no orphans on clean build"
    assert report["stale_intents"] == 0, "no stale intents on clean build"

    # Stage 3: main() now calls util() instead of helper().
    _write(repo / "app/main.py", "from app.util import util\n\n\ndef main():\n    return util()\n")
    _git(repo, "add", "app/main.py")
    _git(repo, "commit", "-qm", "main calls util")
    _cg(repo, "delta")
    assert _consistency(repo) == [], "post-delta (modify) must be consistent"
    assert _query_count(repo, f"callers({CORE})") == 1  # only side
    # util is called by helper (unchanged) AND now main -> 2 callers.
    assert _query_count(repo, f"callers({UTIL})") == 2  # helper + main

    # Stage 4: add newmod.py that calls helper().
    _write(repo / "app/newmod.py", "from app.core import helper\n\n\ndef newfn():\n    return helper()\n")
    _git(repo, "add", "app/newmod.py")
    _git(repo, "commit", "-qm", "add newmod")
    _cg(repo, "delta")
    assert _consistency(repo) == [], "post-delta (add) must be consistent"
    assert _query_count(repo, f"callers({CORE})") == 2  # side + newfn

    # Stage 5: delete side.py.
    _git(repo, "rm", "app/side.py")
    _git(repo, "commit", "-qm", "delete side")
    _cg(repo, "delta")
    assert _consistency(repo) == [], "post-delta (delete) must be consistent"
    assert _query_count(repo, f"callers({CORE})") == 1  # newfn only
    # The deleted relationship must be gone: side must not appear as a caller.
    helper_callers_text = _query_text(repo, f"callers({CORE})")
    assert SIDE not in helper_callers_text, "deleted side must not appear as a caller of helper"

    # Stage 6: repeat — newfn() now calls util() instead of helper().
    _write(repo / "app/newmod.py", "from app.util import util\n\n\ndef newfn():\n    return util()\n")
    _git(repo, "add", "app/newmod.py")
    _git(repo, "commit", "-qm", "newfn calls util")
    _cg(repo, "delta")
    assert _consistency(repo) == [], "post-delta (repeat) must still be consistent"
    assert _query_count(repo, f"callers({CORE})") == 0  # nothing calls helper now
    # util now called by helper, main and newfn.
    assert _query_count(repo, f"callers({UTIL})") == 3  # helper + main + newfn
