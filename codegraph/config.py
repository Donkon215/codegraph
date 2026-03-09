"""codegraph.config — Configuration loader, project-root detection, and schema validation.

Covers tasks A-009, A-010, D-011, D-018.
"""

from __future__ import annotations

import dataclasses
import hashlib
from pathlib import Path
from typing import Any, Optional

import yaml

from codegraph.constants import (
    CODEGRAPH_DIR,
    CONFIG_FILE,
    CONVERGENCE_THRESHOLD,
    DEFAULT_DUNDER_EXCLUDE,
    DEFAULT_EDGE_FILTERS,
    MAX_ITERATIONS,
    PROJECT_ROOT_MARKERS,
)
from codegraph.exceptions import ProjectNotFoundError
from codegraph.logging_config import get_logger

logger = get_logger("config")


# ── D-011  Config schema definition ───────────────────────────────────

_CONFIG_SCHEMA: dict[str, type | tuple[type, ...]] = {
    "internal_libs": list,
    "test_dirs": list,
    "edge_filters": list,
    "dunder_exclude": list,
    "max_iterations": int,
    "convergence_threshold": (int, float),
    "include_stubs": bool,
    "track_intent_history": bool,
}


def _validate_config_types(raw: dict[str, Any]) -> list[str]:
    """Validate config value types against schema. Returns error messages."""
    errors: list[str] = []
    for key, value in raw.items():
        if key not in _CONFIG_SCHEMA:
            continue  # unknown keys are handled separately
        expected = _CONFIG_SCHEMA[key]
        if not isinstance(value, expected):
            type_name = (
                expected.__name__
                if isinstance(expected, type)
                else " or ".join(t.__name__ for t in expected)
            )
            errors.append(
                f"Config key '{key}' expects {type_name}, got {type(value).__name__}"
            )
    return errors


# ── A-009  Configuration dataclass ─────────────────────────────────────


@dataclasses.dataclass
class CodegraphConfig:
    """Parsed representation of ``.codegraph/config.yaml``."""

    internal_libs: list[str] = dataclasses.field(default_factory=list)
    test_dirs: list[str] = dataclasses.field(default_factory=list)
    edge_filters: list[str] = dataclasses.field(
        default_factory=lambda: list(DEFAULT_EDGE_FILTERS)
    )
    dunder_exclude: list[str] = dataclasses.field(
        default_factory=lambda: list(DEFAULT_DUNDER_EXCLUDE)
    )
    max_iterations: int = MAX_ITERATIONS
    convergence_threshold: float = CONVERGENCE_THRESHOLD
    include_stubs: bool = False  # C-028: extract .pyi type stubs
    track_intent_history: bool = False  # E-025: track intent change history

    # --- serialization helpers ------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CodegraphConfig":
        known = {f.name for f in dataclasses.fields(cls)}
        filtered = {k: v for k, v in d.items() if k in known}
        unknown = set(d) - known
        if unknown:
            logger.warning("Unknown config keys ignored: %s", ", ".join(sorted(unknown)))
        return cls(**filtered)

    def __str__(self) -> str:
        return (
            f"CodegraphConfig(internal_libs={self.internal_libs!r}, "
            f"test_dirs={self.test_dirs!r}, max_iterations={self.max_iterations})"
        )


def load_config(project_root: Path) -> CodegraphConfig:
    """Load ``.codegraph/config.yaml`` or return defaults.

    D-011: Validates types against schema. Raises *ValueError* on type mismatches.
    """
    config_path = project_root / CODEGRAPH_DIR / CONFIG_FILE
    if not config_path.exists():
        logger.debug("No config.yaml found — using defaults")
        return CodegraphConfig()

    try:
        text = config_path.read_text(encoding="utf-8")
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML in {config_path}: {exc}") from exc

    if not isinstance(raw, dict):
        logger.warning("config.yaml is not a mapping — using defaults")
        return CodegraphConfig()

    # D-011 — validate types
    type_errors = _validate_config_types(raw)
    if type_errors:
        raise ValueError(
            f"Config validation errors in {config_path}:\n"
            + "\n".join(f"  - {e}" for e in type_errors)
        )

    return CodegraphConfig.from_dict(raw)


# ── A-010  Project root detection ──────────────────────────────────────


def find_project_root(start_path: Optional[Path] = None) -> Path:
    """Walk upward from *start_path* to find the project root.

    The root is the first directory containing one of the marker files/dirs
    defined in :data:`PROJECT_ROOT_MARKERS` (``.codegraph/``, ``.git/``,
    ``pyproject.toml``).

    Raises :class:`ProjectNotFoundError` if the filesystem root is reached.
    """
    current = (start_path or Path.cwd()).resolve()

    while True:
        for marker in PROJECT_ROOT_MARKERS:
            if (current / marker).exists():
                logger.debug("Project root found: %s (marker: %s)", current, marker)
                return current
        parent = current.parent
        if parent == current:
            raise ProjectNotFoundError(str(start_path or Path.cwd()))
        current = parent


# ── D-018  Config hash for hot-reload detection ───────────────────────


def compute_config_hash(project_root: Path) -> str:
    """Return SHA-256 hex digest of the current config file content.

    Returns an empty string if no config file exists.
    """
    config_path = project_root / CODEGRAPH_DIR / CONFIG_FILE
    if not config_path.exists():
        return ""
    content = config_path.read_bytes()
    return hashlib.sha256(content).hexdigest()


def config_changed_since_build(project_root: Path, stored_hash: str) -> bool:
    """Return *True* when `config.yaml` differs from the hash stored at last build."""
    if not stored_hash:
        # No stored hash means first build or no previous config
        return False
    current = compute_config_hash(project_root)
    return current != stored_hash
