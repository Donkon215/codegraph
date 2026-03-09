"""codegraph.git_utils — Git interface utilities.

Wraps common git operations needed by the delta engine and diff commands.
(Task A-028)
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List, Optional

from codegraph.logging_config import get_logger

logger = get_logger("git")


def is_git_repo(path: Path) -> bool:
    """Return *True* if *path* (or an ancestor) is inside a git repository."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(path),
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0 and result.stdout.strip() == "true"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def get_current_commit(path: Path) -> Optional[str]:
    """Return the full SHA of HEAD, or ``None`` if unavailable."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(path),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def get_changed_files(path: Path, since: str = "HEAD") -> List[str]:
    """Return a list of file paths changed relative to *since*.

    Falls back to an empty list if git is not available or the repo has
    no commits yet.
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", since],
            cwd=str(path),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.warning("git diff failed: %s", result.stderr.strip())
            return []

        files = [
            f.strip()
            for f in result.stdout.strip().splitlines()
            if f.strip()
        ]

        # Also include staged changes.
        staged = subprocess.run(
            ["git", "diff", "--name-only", "--cached"],
            cwd=str(path),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if staged.returncode == 0:
            for f in staged.stdout.strip().splitlines():
                f = f.strip()
                if f and f not in files:
                    files.append(f)

        # Filter to files that actually exist and are not binary.
        existing = []
        for f in files:
            fp = path / f
            if fp.exists() and fp.is_file():
                existing.append(f)
        return existing

    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.warning("git not available: %s", exc)
        return []


def get_file_at_commit(path: Path, file_path: str, commit: str) -> Optional[str]:
    """Return the contents of *file_path* at *commit*, or ``None``."""
    try:
        result = subprocess.run(
            ["git", "show", f"{commit}:{file_path}"],
            cwd=str(path),
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            return result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def has_uncommitted_changes(path: Path) -> bool:
    """Return *True* if the working tree has uncommitted changes."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(path),
            capture_output=True,
            text=True,
            timeout=15,
        )
        return bool(result.stdout.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
