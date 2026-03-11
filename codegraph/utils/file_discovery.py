"""codegraph.utils.file_discovery — Source-file discovery and exclusion.

(Task A-033)
"""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path
from typing import List, Optional, Sequence

from codegraph.constants import CODEGRAPH_DIR
from codegraph.logging_config import get_logger

logger = get_logger("file_discovery")

_ALWAYS_EXCLUDE = {
    CODEGRAPH_DIR,
    "__pycache__",
    ".git",
    "node_modules",
    ".venv",
    "venv",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    "*.egg-info",
}


def _is_excluded_dir(dirname: str) -> bool:
    """Check if a directory name matches any always-excluded pattern."""
    for pat in _ALWAYS_EXCLUDE:
        if fnmatch.fnmatch(dirname, pat):
            return True
    return False


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
        Extra patterns from .gitignore to exclude.

    Returns
    -------
    list[Path]
        Sorted list of absolute paths.
    """
    if extensions is None:
        try:
            from codegraph.extractors import supported_extensions as _reg_exts
            extensions = _reg_exts() or [".py"]
        except Exception:
            extensions = [".py"]
    ext_set = set(extensions)

    results: List[Path] = []

    for dirpath, dirnames, filenames in os.walk(project_root):
        dirnames[:] = [
            d for d in dirnames
            if not d.startswith(".") or d == ".codegraph"
            if not _is_excluded_dir(d)
        ]
        dirnames[:] = [d for d in dirnames if d != CODEGRAPH_DIR]

        for fname in filenames:
            if any(fname.endswith(ext) for ext in ext_set):
                results.append(Path(dirpath) / fname)

    results.sort()
    return results
