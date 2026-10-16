"""Regression tests for issue #54: source discovery follows the project's .gitignore.

Note for readers of these tests: python -m codegraph analyze reads an index.
The fixes here change what discover_source_files returns; the analyze output
only changes after the index is rebuilt, so these tests call the discovery
function directly rather than the cached analyze report.
"""

from pathlib import Path

from codegraph.utils.file_discovery import (
    IgnoreRules,
    discover_source_files,
    load_gitignore_patterns,
)


def _write(path: Path, text: str = "x = 1\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _names(files, root: Path):
    return {p.relative_to(root).as_posix() for p in files}


def test_gitignored_folder_scratch_file_is_not_discovered(tmp_path):
    _write(tmp_path / "src" / "app.py")
    _write(tmp_path / "deleter" / "scratch_test_field_loss.py")
    (tmp_path / ".gitignore").write_text("deleter/\n", encoding="utf-8")

    found = _names(discover_source_files(tmp_path), tmp_path)

    assert "src/app.py" in found
    assert "deleter/scratch_test_field_loss.py" not in found


def test_exclusion_comes_from_gitignore_not_a_folder_list(tmp_path):
    # A folder name that appears nowhere in the code must still be excluded
    # when the project's .gitignore lists it.
    _write(tmp_path / "src" / "app.py")
    _write(tmp_path / "scratchpad_xyz" / "throwaway.py")
    (tmp_path / ".gitignore").write_text("scratchpad_xyz/\n", encoding="utf-8")

    found = _names(discover_source_files(tmp_path), tmp_path)

    assert found == {"src/app.py"}


def test_the_four_folders_in_this_repos_gitignore_are_excluded(tmp_path):
    for folder in ("htmlcov", "sample_project", "graphify-out", "deleter"):
        _write(tmp_path / folder / "module.py")
    _write(tmp_path / "keep" / "module.py")
    (tmp_path / ".gitignore").write_text(
        "htmlcov/\nsample_project/\ngraphify-out/\ndeleter/\n", encoding="utf-8"
    )

    found = _names(discover_source_files(tmp_path), tmp_path)

    assert found == {"keep/module.py"}


def test_anchored_pattern_matches_only_at_root(tmp_path):
    _write(tmp_path / "only_here.py")
    _write(tmp_path / "nested" / "only_here.py")
    (tmp_path / ".gitignore").write_text("/only_here.py\n", encoding="utf-8")

    found = _names(discover_source_files(tmp_path), tmp_path)

    assert found == {"nested/only_here.py"}


def test_unanchored_name_matches_at_any_depth(tmp_path):
    _write(tmp_path / "a" / "gen_stub.py")
    _write(tmp_path / "a" / "b" / "gen_stub.py")
    _write(tmp_path / "real.py")
    (tmp_path / ".gitignore").write_text("gen_stub.py\n", encoding="utf-8")

    found = _names(discover_source_files(tmp_path), tmp_path)

    assert found == {"real.py"}


def test_directory_only_pattern_does_not_hide_a_file_of_the_same_name(tmp_path):
    _write(tmp_path / "cache" / "inside.py")
    _write(tmp_path / "cache.py")
    (tmp_path / ".gitignore").write_text("cache/\n", encoding="utf-8")

    found = _names(discover_source_files(tmp_path), tmp_path)

    assert found == {"cache.py"}


def test_double_star_pattern_excludes_everything_below(tmp_path):
    _write(tmp_path / "docs" / "conf.py")
    _write(tmp_path / "docs" / "deep" / "more.py")
    _write(tmp_path / "code.py")
    (tmp_path / ".gitignore").write_text("docs/**\n", encoding="utf-8")

    found = _names(discover_source_files(tmp_path), tmp_path)

    assert found == {"code.py"}


def test_negated_pattern_is_dropped_so_the_file_stays_excluded(tmp_path):
    # Negation is not supported. The exclusion stands rather than being
    # silently re-included, which is the conservative failure.
    _write(tmp_path / "keep.py")
    (tmp_path / ".gitignore").write_text("*.py\n!keep.py\n", encoding="utf-8")

    assert load_gitignore_patterns(tmp_path) == ["*.py"]
    assert discover_source_files(tmp_path) == []


def test_comments_and_blank_lines_are_ignored(tmp_path):
    (tmp_path / ".gitignore").write_text(
        "# a comment\n\n   \ndeleter/\n", encoding="utf-8"
    )

    assert load_gitignore_patterns(tmp_path) == ["deleter/"]


def test_missing_gitignore_still_discovers_source(tmp_path):
    _write(tmp_path / "app.py")

    assert _names(discover_source_files(tmp_path), tmp_path) == {"app.py"}


def test_node_modules_is_still_excluded_without_a_gitignore_entry(tmp_path):
    _write(tmp_path / "app.py")
    _write(tmp_path / "node_modules" / "pkg" / "index.py")

    assert _names(discover_source_files(tmp_path), tmp_path) == {"app.py"}


def test_ignore_rules_match_a_path_under_an_ignored_ancestor():
    rules = IgnoreRules(["deleter/"])

    assert rules.is_ignored("deleter/scratch.py", is_dir=False)
    assert not rules.is_ignored("src/deleter_notes.py", is_dir=False)
