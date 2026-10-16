"""codegraph.utils.file_discovery — Source-file discovery and exclusion.

(Task A-033, revised for issue #54)

Which files count as project source is decided by the project's own
``.gitignore``, not by a list of folder names in this module. Paths matched by
``.gitignore`` are pruned during the walk, so their contents are never read.

Supported ``.gitignore`` syntax: plain names and globs (``*``, ``?``, ``**``),
trailing ``/`` for directories, a leading or inner ``/`` to anchor a pattern at
the project root, and ordered negation (``!pattern``). As in Git, a child of an
excluded directory cannot be re-included unless the directory is re-included
first. Character classes (``[...]``) are matched literally; nested
``.gitignore`` files, escaped trailing spaces, and Git's platform-specific
case-folding are not implemented.

This implements a documented subset of gitignore semantics, not full
compatibility with git. It does not match ``git check-ignore`` in every case.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Sequence

from codegraph.constants import CODEGRAPH_DIR
# Conventional dependency and environment folders that are not source code.
# Kept deliberately short: anything a project lists in .gitignore is handled by
# the ignore rules, so these two names are the only exceptions.
_ALWAYS_EXCLUDE = {
    "node_modules",
    "venv",
}


def load_gitignore_patterns(project_root: Path) -> List[str]:
    """Return ordered patterns from ``project_root/.gitignore``.

    Blank lines and comments are dropped. Negated patterns are retained in
    order; :class:`IgnoreRules` applies the last matching rule. Returns an
    empty list when there is no ``.gitignore``.
    """
    path = Path(project_root) / ".gitignore"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    patterns: List[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        patterns.append(line)
    return patterns


def _glob_to_regex(glob: str) -> "re.Pattern[str]":
    """Translate one gitignore glob (without trailing slash) to a regex."""
    out: List[str] = []
    i = 0
    while i < len(glob):
        c = glob[i]
        if c == "*":
            if glob[i:i + 2] == "**":
                if glob[i + 2:i + 3] == "/":
                    out.append("(?:.*/)?")  # "**/" : zero or more directories
                    i += 3
                    continue
                out.append(".*")  # "**" elsewhere: anything
                i += 2
                continue
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(c))
        i += 1
    return re.compile("".join(out))


class IgnoreRules:
    """Matches project-relative POSIX paths against gitignore patterns."""

    def __init__(self, patterns: Sequence[str]) -> None:
        self._rules: List[tuple] = []
        for pattern in patterns:
            negated = pattern.startswith("!")
            body = pattern[1:] if negated else pattern
            dir_only = body.endswith("/")
            body = body.rstrip("/")
            # A slash before the last character anchors the pattern to the root.
            anchored = "/" in body
            body = body.lstrip("/")
            if not body:
                continue
            self._rules.append((_glob_to_regex(body), dir_only, anchored, negated))

    def is_ignored(self, rel_path: str, is_dir: bool) -> bool:
        """True if *rel_path* (POSIX, relative to the root) or any ancestor matches."""
        parts = rel_path.split("/")
        for depth in range(1, len(parts) + 1):
            sub = "/".join(parts[:depth])
            name = parts[depth - 1]
            sub_is_dir = is_dir if depth == len(parts) else True
            ignored = False
            for regex, dir_only, anchored, negated in self._rules:
                if dir_only and not sub_is_dir:
                    continue
                target = sub if anchored else name
                if regex.fullmatch(target):
                    ignored = not negated
            # Git cannot re-include a child while an ancestor remains excluded.
            if depth < len(parts) and ignored:
                return True
        return ignored


def _is_always_excluded(dirname: str) -> bool:
    return dirname in _ALWAYS_EXCLUDE


def discover_source_files(
    project_root: Path,
    extensions: Optional[Sequence[str]] = None,
    gitignore_patterns: Optional[List[str]] = None,
) -> List[Path]:
    """Find all source files under *project_root*.

    Parameters
    ----------
    project_root:
        The root directory to search.
    extensions:
        File extensions to include.  When ``None``, uses all extensions
        registered in the extractor registry (falls back to ``[".py"]``).
    gitignore_patterns:
        Patterns to exclude, as returned by :func:`load_gitignore_patterns`.
        When ``None``, the project's ``.gitignore`` is read.

    Returns
    -------
    list[Path]
        Sorted list of absolute paths.
    """
    project_root = Path(project_root)
    if extensions is None:
        try:
            from codegraph.extractors import supported_extensions as _reg_exts
            extensions = _reg_exts() or [".py"]
        except Exception:
            extensions = [".py"]
    ext_set = set(extensions)

    if gitignore_patterns is None:
        gitignore_patterns = load_gitignore_patterns(project_root)
    rules = IgnoreRules(gitignore_patterns)

    results: List[Path] = []

    for dirpath, dirnames, filenames in os.walk(project_root):
        rel_dir = os.path.relpath(dirpath, project_root).replace(os.sep, "/")
        rel_dir = "" if rel_dir == "." else rel_dir

        kept: List[str] = []
        for d in dirnames:
            if d == CODEGRAPH_DIR:
                continue
            if d.startswith("."):
                continue
            if _is_always_excluded(d):
                continue
            rel = f"{rel_dir}/{d}" if rel_dir else d
            if rules.is_ignored(rel, is_dir=True):
                continue
            kept.append(d)
        dirnames[:] = kept

        for fname in filenames:
            if not any(fname.endswith(ext) for ext in ext_set):
                continue
            rel = f"{rel_dir}/{fname}" if rel_dir else fname
            if rules.is_ignored(rel, is_dir=False):
                continue
            results.append(Path(dirpath) / fname)

    results.sort()
    return results
