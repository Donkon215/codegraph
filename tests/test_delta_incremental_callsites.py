"""Issue #16 — ``codegraph delta`` must not re-extract every source file.

After a build, a delta that changes only one file should re-parse just the
affected file(s), reusing cached call sites/imports for the rest of the repo
— instead of re-extracting the whole project on every delta.
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
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _make_repo(files: dict) -> Path:
    d = Path(tempfile.mkdtemp(prefix="cg16_"))
    _git(d, "init", "-q")
    for name, text in files.items():
        _write(d / name, text)
        _git(d, "add", name)
    _git(d, "commit", "-qm", "init")
    return d


def test_delta_only_reextracts_affected_files():
    from codegraph.delta import run_delta
    from codegraph import extractor as extractor_mod
    from codegraph.config import load_config

    # Many independent, unchanged files + one file we will keep editing.
    files = {f"u{i}.py": f"def g{i}():\n    return {i}\n" for i in range(20)}
    files["target.py"] = "def t():\n    return 1\n"
    repo = _make_repo(files)

    _cg(repo, "build")

    # Seed the persisted cache: the first delta has no cache yet, so it falls
    # back to a full re-extraction (and writes the cache for next time).
    _write(repo / "target.py", "def t():\n    return 2\n")
    _git(repo, "add", "target.py")
    _cg(repo, "delta")

    # Now make a second change and measure how many files the delta re-extracts.
    _write(repo / "target.py", "def t():\n    return 3\n")
    _git(repo, "add", "target.py")

    extracted: list[str] = []
    orig = extractor_mod.extract_file

    def _spy(fp, root):
        extracted.append(str(fp))
        return orig(fp, root)

    extractor_mod.extract_file = _spy
    try:
        run_delta(repo, load_config(repo))
    finally:
        extractor_mod.extract_file = orig

    basenames = {Path(p).name for p in extracted}

    # Only the affected file may be re-parsed; the 20 unchanged files must not.
    assert basenames == {"target.py"}, basenames
    assert "u0.py" not in basenames
    # Re-extraction (changed files) plus incremental collection (affected set)
    # both hit target.py, but never the whole repo.
    assert len(extracted) <= 2, extracted
