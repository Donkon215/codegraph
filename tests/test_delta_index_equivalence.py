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
    p.parent.mkdir(parents=True, exist_ok=True)
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
    # Explicit import so the cross-file edge actually forms (bare calls don't
    # resolve across files in this extractor).
    assert_equivalence(
        {"a.py": "from b import bar\n\n\ndef caller():\n    return bar()\n"},
        {"a.py": "from b import bar\n\n\ndef caller():\n    return bar()\n", "b.py": "def bar():\n    return 1\n"},
    )


def test_delete_function():
    assert_equivalence(
        {"a.py": "from b import foo\n\n\ndef caller():\n    return foo()\n", "b.py": "def foo():\n    return 1\n"},
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


def test_resolved_edge_change():
    # a.py imports `helper` from b and calls it (a real, resolved edge
    # caller -> b.py::helper). v2 renames b.py::helper -> helper2, so the edge
    # disappears. The dependency hash of `caller` therefore changes between v1
    # and v2; delta must recompute CAS against the *new* workflow, otherwise
    # its hash (keyed on the stale v1 edge) diverges from a fresh full build.
    assert_equivalence(
        {
            "a.py": "from b import helper\n\n\ndef caller():\n    return helper()\n",
            "b.py": "def helper():\n    return 1\n",
        },
        {
            "a.py": "from b import helper\n\n\ndef caller():\n    return helper()\n",
            "b.py": "def helper2():\n    return 1\n",
            "c.py": "def helper():\n    return 2\n",
        },
    )


def test_chain_dependency_propagation():
    # A -> B -> C chain. Modifying the leaf C must propagate the dependency
    # hash invalidation up through B to A in BOTH the full build and the
    # delta, so all three hashes agree. Explicit imports make the edges real.
    assert_equivalence(
        {
            "a.py": "from b import b\n\n\ndef a():\n    return b()\n",
            "b.py": "from c import c\n\n\ndef b():\n    return c()\n",
            "c.py": "def c():\n    return 1\n",
        },
        {
            "a.py": "from b import b\n\n\ndef a():\n    return b()\n",
            "b.py": "from c import c\n\n\ndef b():\n    return c()\n",
            "c.py": "def c():\n    return 2\n",
        },
    )


def test_chain_delete_leaf():
    # Deleting the leaf C removes the edge into it, which must re-hash B and
    # then A (the whole affected closure), not just C.
    assert_equivalence(
        {
            "a.py": "from b import b\n\n\ndef a():\n    return b()\n",
            "b.py": "from c import c\n\n\ndef b():\n    return c()\n",
            "c.py": "def c():\n    return 1\n",
        },
        {
            "a.py": "def a():\n    return 1\n",
            "b.py": "def b():\n    return 1\n",
        },
    )


def test_diamond_dependency_propagation():
    # A -> {B, C} -> D. Modifying D must invalidate B, C and A.
    assert_equivalence(
        {
            "a.py": "from b import b\nfrom c import c\n\n\ndef a():\n    return b() + c()\n",
            "b.py": "from d import d\n\n\ndef b():\n    return d()\n",
            "c.py": "from d import d\n\n\ndef c():\n    return d()\n",
            "d.py": "def d():\n    return 1\n",
        },
        {
            "a.py": "from b import b\nfrom c import c\n\n\ndef a():\n    return b() + c()\n",
            "b.py": "from d import d\n\n\ndef b():\n    return d()\n",
            "c.py": "from d import d\n\n\ndef c():\n    return d()\n",
            "d.py": "def d():\n    return 2\n",
        },
    )


def test_cycle_scc():
    # A <-> B mutual recursion (an SCC). Modifying one node must recompute the
    # SCC hash for both, identically in full build and delta.
    assert_equivalence(
        {
            "a.py": "from b import b\n\n\ndef a():\n    return b()\n",
            "b.py": "from a import a\n\n\ndef b():\n    return a()\n",
        },
        {
            "a.py": "from b import b\n\n\ndef a():\n    return b()\n",
            "b.py": "from a import a\n\n\ndef b():\n    return a() + 1\n",
        },
    )


def test_file_rename():
    # Rename the module that defines `helper` (a.py -> mod.py). The unchanged
    # caller re-resolves `helper` to mod.py::helper in BOTH paths. Explicit
    # import makes the caller->helper edge real.
    assert_equivalence(
        {
            "a.py": "def helper():\n    return 1\n",
            "b.py": "from a import helper\n\n\ndef caller():\n    return helper()\n",
        },
        {
            "mod.py": "def helper():\n    return 1\n",
            "b.py": "from mod import helper\n\n\ndef caller():\n    return helper()\n",
        },
    )


def test_import_change():
    # Flip the import so `caller` resolves to c.py::helper instead of
    # b.py::helper. Delta must rebuild the caller edge and re-hash it.
    assert_equivalence(
        {
            "a.py": "from b import helper\n\n\ndef caller():\n    return helper()\n",
            "b.py": "def helper():\n    return 1\n",
            "c.py": "def helper():\n    return 2\n",
        },
        {
            "a.py": "from c import helper\n\n\ndef caller():\n    return helper()\n",
            "b.py": "def helper():\n    return 1\n",
            "c.py": "def helper():\n    return 2\n",
        },
    )


def test_test_relationship_change():
    # Adding a tested function and a new test that exercises it must keep the
    # `tests` table in lock-step between full build and delta.
    assert_equivalence(
        {
            "app.py": "def do_work():\n    return 1\n",
            "tests/test_app.py": (
                "from app import do_work\n\n"
                "def test_work():\n    assert do_work() == 1\n"
            ),
        },
        {
            "app.py": (
                "def do_work():\n    return 1\n\n"
                "def do_more():\n    return 2\n"
            ),
            "tests/test_app.py": (
                "from app import do_work, do_more\n\n"
                "def test_work():\n    assert do_work() == 1\n\n"
                "def test_more():\n    assert do_more() == 2\n"
            ),
        },
    )


def test_multiple_simultaneous_changes():
    # Delete b.py, add c.py (redefining helper + a new fn), and modify a.py
    # to call both. Exercises deletion + addition + modification + resolution
    # flip in a single delta. Explicit imports make the edges real.
    assert_equivalence(
        {
            "a.py": "from b import helper\n\n\ndef caller():\n    return helper()\n",
            "b.py": "def helper():\n    return 1\n",
        },
        {
            "a.py": "from c import helper, added\n\n\ndef caller():\n    return helper() + added()\n",
            "c.py": "def added():\n    return 2\ndef helper():\n    return 9\n",
        },
    )


def test_noop_delta():
    # A second delta with no source change must leave the index identical to a
    # fresh full build of the same state.
    from codegraph.index_snapshot import diff_index_snapshots, snapshot_index

    initial = {"a.py": "def f():\n    return 1\n"}
    delta_dir = _make_repo(initial)
    _cg(delta_dir, "build")
    _cg(delta_dir, "delta")  # no changes

    full_dir = _make_repo(initial)
    _cg(full_dir, "build")

    diff = diff_index_snapshots(snapshot_index(delta_dir), snapshot_index(full_dir))
    if diff:
        import pprint

        pytest.fail("build<->no-op-delta divergence:\n" + pprint.pformat(diff))


def test_repeated_delta():
    # Two successive deltas must converge to the same index as a fresh full
    # build of the final state (incremental state must persist correctly).
    from codegraph.index_snapshot import diff_index_snapshots, snapshot_index

    initial = {"a.py": "def f():\n    return 1\n"}
    mid = {"a.py": "def f():\n    return 2\n"}
    final = {"a.py": "def f():\n    return 3\n"}

    delta_dir = _make_repo(initial)
    _cg(delta_dir, "build")
    _write(delta_dir / "a.py", mid["a.py"])
    _git(delta_dir, "add", "a.py")
    _cg(delta_dir, "delta")
    _write(delta_dir / "a.py", final["a.py"])
    _git(delta_dir, "add", "a.py")
    _cg(delta_dir, "delta")

    full_dir = _make_repo(final)
    _cg(full_dir, "build")

    diff = diff_index_snapshots(snapshot_index(delta_dir), snapshot_index(full_dir))
    if diff:
        import pprint

        pytest.fail("build<->repeated-delta divergence:\n" + pprint.pformat(diff))
