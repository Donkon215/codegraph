"""codegraph.storage — .codegraph/ directory manager, atomic writer, version/cycle tracking.

Covers tasks A-008, A-011, A-012, A-013, A-016, A-029.
"""

from __future__ import annotations

import json
import os
import platform
import tempfile
from pathlib import Path
from typing import Any, Optional, Union

import yaml

from codegraph.constants import (
    CODEGRAPH_DIR,
    CONFIG_FILE,
    CURRENT_FORMAT_VERSION,
    CYCLE_FILE,
    GRAPHS_DIR,
    INDEX_DIR,
    RESPONSES_DIR,
    TASKS_DIR,
    TEST_ARCHI_DIR,
    WORKFLOW_DIR,
)
from codegraph.exceptions import FormatVersionError
from codegraph.logging_config import get_logger

logger = get_logger("storage")

# ── A-008  .codegraph directory manager ────────────────────────────────

_SUBDIRS = [
    GRAPHS_DIR,
    WORKFLOW_DIR,
    INDEX_DIR,
    TASKS_DIR,
    RESPONSES_DIR,
    TEST_ARCHI_DIR,
]


def _codegraph_root(project_root: Path) -> Path:
    return project_root / CODEGRAPH_DIR


def ensure_codegraph_dir(project_root: Path) -> Path:
    """Create the ``.codegraph/`` tree if it does not exist.  Idempotent."""
    cg = _codegraph_root(project_root)
    cg.mkdir(exist_ok=True)
    for sub in _SUBDIRS:
        (cg / sub).mkdir(exist_ok=True)
    logger.debug("Ensured .codegraph/ tree at %s", cg)
    return cg


def is_initialized(project_root: Path) -> bool:
    """Return *True* if ``.codegraph/`` exists at *project_root*."""
    return _codegraph_root(project_root).is_dir()


def resolve_path(project_root: Path, *parts: str) -> Path:
    """Return an absolute path inside ``.codegraph/``."""
    return _codegraph_root(project_root).joinpath(*parts)


# ── A-011  .gitignore generator ────────────────────────────────────────

_GITIGNORE_RULES = [
    "# codegraph generated artifacts",
    ".codegraph/graphs/graph0.json",
    ".codegraph/workflow/workflow.json",
    ".codegraph/delta.json",
    ".codegraph/index/",
    ".codegraph/tasks/",
    ".codegraph/responses/",
]


def generate_gitignore(project_root: Path) -> None:
    """Append codegraph ignore rules to ``.gitignore`` (idempotent)."""
    gi_path = project_root / ".gitignore"
    existing = gi_path.read_text(encoding="utf-8") if gi_path.exists() else ""

    missing = [r for r in _GITIGNORE_RULES if r not in existing]
    if not missing:
        return

    with gi_path.open("a", encoding="utf-8") as fh:
        if existing and not existing.endswith("\n"):
            fh.write("\n")
        fh.write("\n".join(missing) + "\n")

    logger.info("Updated .gitignore with codegraph rules")


# ── A-013  Atomic file writer ──────────────────────────────────────────


def atomic_write(
    path: Union[str, Path],
    data: Any,
    fmt: str = "json",
) -> None:
    """Write *data* to *path* atomically (write-tmp-then-rename).

    Parameters
    ----------
    path:
        Destination file path.
    data:
        Data to serialize.  For ``json`` format, anything JSON-serializable.
        For ``yaml`` format, any YAML-safe structure.
    fmt:
        ``"json"`` (default) or ``"yaml"``.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "json":
        content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    elif fmt == "yaml":
        content = yaml.safe_dump(data, default_flow_style=False, sort_keys=False)
    else:
        raise ValueError(f"Unsupported format: {fmt}")

    # Write to a temp file in the same directory, then rename.
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent), suffix=".tmp", prefix=".cg_"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())

        # On Windows, target must not exist for os.rename.
        if platform.system() == "Windows" and path.exists():
            path.unlink()
        os.rename(tmp_path, str(path))
    except BaseException:
        # Clean up temp file on any failure.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    logger.debug("Wrote %s (%s)", path, fmt)


def atomic_read(path: Union[str, Path], fmt: str = "json") -> Any:
    """Read and deserialize a file written by :func:`atomic_write`."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if fmt == "json":
        return json.loads(text)
    elif fmt == "yaml":
        return yaml.safe_load(text)
    raise ValueError(f"Unsupported format: {fmt}")


# ── A-012  Graph version counter ───────────────────────────────────────


def get_graph_version(project_root: Path) -> int:
    """Return the current graph_version (starts at 0 if never built)."""
    g0_path = resolve_path(project_root, GRAPHS_DIR, "graph0.json")
    if not g0_path.exists():
        return 0
    data = json.loads(g0_path.read_text(encoding="utf-8"))
    return int(data.get("graph_version", 0))


def increment_graph_version(project_root: Path) -> int:
    """Increment and return the new graph_version.

    The authoritative version lives in the ``graph0.json`` metadata,
    but we also keep a small sidecar for quick reads before graph0 exists.
    """
    ver = get_graph_version(project_root) + 1
    # Persist as sidecar for cases where graph0 hasn't been written yet.
    sidecar = resolve_path(project_root, GRAPHS_DIR, "version.json")
    atomic_write(sidecar, {"graph_version": ver})
    logger.debug("Graph version incremented to %d", ver)
    return ver


# ── A-016  Cycle counter ──────────────────────────────────────────────


def _cycle_path(project_root: Path) -> Path:
    return resolve_path(project_root, CYCLE_FILE)


def get_current_cycle(project_root: Path) -> int:
    """Return the current cycle number (starts at 0)."""
    cp = _cycle_path(project_root)
    if not cp.exists():
        return 0
    data = json.loads(cp.read_text(encoding="utf-8"))
    return int(data.get("cycle", 0))


def increment_cycle(project_root: Path) -> int:
    """Increment and persist the cycle counter."""
    new_cycle = get_current_cycle(project_root) + 1
    atomic_write(_cycle_path(project_root), {"cycle": new_cycle})
    logger.debug("Cycle incremented to %d", new_cycle)
    return new_cycle


# ── A-029  Format-version checking ────────────────────────────────────


def check_format_version(
    data: dict,
    expected: int = CURRENT_FORMAT_VERSION,
    source_file: str = "<unknown>",
) -> None:
    """Raise :class:`FormatVersionError` if *data* has wrong version."""
    got = data.get("format_version")
    if got is None:
        return  # legacy file — treat as compatible
    if int(got) != expected:
        raise FormatVersionError(source_file, expected, int(got))


# ── D-018  Config hash storage ─────────────────────────────────────────

_BUILD_META_FILE = "build_meta.json"


def store_config_hash(project_root: Path, config_hash: str) -> None:
    """Persist the config file hash after a build."""
    meta_path = resolve_path(project_root, _BUILD_META_FILE)
    existing: dict = {}
    if meta_path.exists():
        existing = json.loads(meta_path.read_text(encoding="utf-8"))
    existing["config_hash"] = config_hash
    atomic_write(meta_path, existing)
    logger.debug("Stored config hash: %s", config_hash[:12])


def get_stored_config_hash(project_root: Path) -> str:
    """Retrieve the config hash from the last build. Returns '' if none."""
    meta_path = resolve_path(project_root, _BUILD_META_FILE)
    if not meta_path.exists():
        return ""
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    return data.get("config_hash", "")
