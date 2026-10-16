"""Differential test: IgnoreRules against ``git check-ignore`` (issue #54 / #56).

``git check-ignore`` is the reference implementation. For a curated set of
patterns and paths, the project's matcher must agree with git on every path.

The path list is curated, not generated. It covers the awkward cases on purpose
and deliberately omits negation (``!``), which is not supported until #56.

Two known divergences from git are pinned as documented behaviour rather than
left to fail:
  * character classes (``[abc]``) are matched literally, not as classes;
  * matching is case-sensitive, even where git on Windows ignores case.

If git is not installed, the comparison is skipped, not weakened.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from codegraph.utils.file_discovery import IgnoreRules, load_gitignore_patterns

GIT = shutil.which("git")

PATTERNS = [
    "*.log",          # bare glob, matches at any depth
    "build/",         # directory only, any depth
    "/root_only.txt",  # anchored to root
    "docs/**",        # ** at the end
    "**/gen/*.py",    # ** at the start
    "a/**/b.py",      # ** in the middle
    "cache",          # bare name, matches file or directory
    "src/*.tmp",      # * does not cross a directory boundary
]

# (relative path, is_directory). Every path is created in the fixture.
CASES = [
    ("app.log", False),
    ("sub/app.log", False),
    ("build", True),
    ("build/out.py", False),
    ("build_notes.txt", False),
    ("root_only.txt", False),
    ("sub/root_only.txt", False),
    ("docs", True),
    ("docs/readme.md", False),
    ("docs/deep", True),
    ("docs/deep/x.py", False),
    ("gen", True),
    ("gen/z.py", False),
    ("gen/deep/z.py", False),
    ("x", True),
    ("x/gen/y.py", False),
    ("a", True),
    ("a/b.py", False),
    ("a/b", True),
    ("a/b/b.py", False),
    ("a/x/y/b.py", False),
    ("cache", False),
    ("cache.py", False),
    ("src", True),
    ("src/x.tmp", False),
    ("src/deep", True),
    ("src/deep/x.tmp", False),
    ("src/main.py", False),
    ("sub", True),
    ("plain.py", False),
    ("weird[1].txt", False),
]


def _build_fixture(root: Path, patterns: list[str]) -> None:
    (root / ".gitignore").write_text("\n".join(patterns) + "\n", encoding="utf-8")
    for rel, is_dir in CASES:
        target = root / rel
        if is_dir:
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("x\n", encoding="utf-8")


def _git_init(root: Path) -> None:
    subprocess.run([GIT, "init", "-q"], cwd=root, check=True)


def _git_ignored(root: Path, rel: str) -> bool:
    # --no-index: judge by .gitignore alone, not by what is already tracked.
    result = subprocess.run(
        [GIT, "check-ignore", "-q", "--no-index", "--", rel],
        cwd=root,
        capture_output=True,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(f"git check-ignore failed for {rel}: {result.stderr!r}")
    return result.returncode == 0


@pytest.mark.skipif(GIT is None, reason="git is not installed; reference unavailable")
def test_matcher_agrees_with_git_check_ignore_on_every_curated_path(tmp_path):
    _build_fixture(tmp_path, PATTERNS)
    _git_init(tmp_path)
    rules = IgnoreRules(load_gitignore_patterns(tmp_path))

    disagreements = []
    for rel, is_dir in CASES:
        ours = rules.is_ignored(rel, is_dir=is_dir)
        theirs = _git_ignored(tmp_path, rel)
        if ours != theirs:
            disagreements.append(f"{rel}: matcher={ours} git={theirs}")

    assert not disagreements, "matcher disagrees with git:\n" + "\n".join(disagreements)


@pytest.mark.skipif(GIT is None, reason="git is not installed; reference unavailable")
def test_documented_divergence_character_classes_are_literal(tmp_path):
    # Documented: [abc] is literal here. Git treats it as a character class.
    (tmp_path / ".gitignore").write_text("[abc].txt\n", encoding="utf-8")
    (tmp_path / "a.txt").write_text("x\n", encoding="utf-8")
    _git_init(tmp_path)

    assert _git_ignored(tmp_path, "a.txt") is True
    assert IgnoreRules(["[abc].txt"]).is_ignored("a.txt", is_dir=False) is False
    assert IgnoreRules(["[abc].txt"]).is_ignored("[abc].txt", is_dir=False) is True


def test_documented_divergence_matching_is_case_sensitive():
    # Documented: matching is case-sensitive. Git on Windows (core.ignorecase)
    # may ignore case, so this is not compared against git.
    rules = IgnoreRules(["Cache"])

    assert rules.is_ignored("cache", is_dir=False) is False
    assert rules.is_ignored("Cache", is_dir=False) is True
