"""codegraph.utils.ids — Node ID generation and path normalization.

(Tasks A-022, A-026)
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


# ── A-022  Node ID generator ──────────────────────────────────────────


def generate_node_id(
    file_path: str,
    class_name: Optional[str] = None,
    func_name: Optional[str] = None,
    disambiguator: Optional[int] = None,
) -> str:
    """Generate a deterministic node ID.

    Format: ``path/file.py::ClassName::method`` or ``path/file.py::func``
    Modules use ``path/file`` (no extension).

    A numeric ``[N]`` suffix is appended when *disambiguator* >= 2.
    """
    if class_name is None and func_name is None:
        parts = file_path.rsplit(".", 1)
        nid = parts[0] if len(parts) > 1 else file_path
    else:
        components = [file_path]
        if class_name:
            components.append(class_name)
        if func_name:
            components.append(func_name)
        nid = "::".join(components)

    if disambiguator is not None and disambiguator >= 2:
        nid += f"[{disambiguator}]"

    return nid


# ── A-026  Path normalization ─────────────────────────────────────────


def normalize_path(absolute_path: Path, project_root: Path) -> str:
    """Convert *absolute_path* to a forward-slash relative string.

    Raises :class:`ValueError` if *absolute_path* is outside *project_root*.
    """
    abs_resolved = absolute_path.resolve()
    root_resolved = project_root.resolve()
    try:
        rel = abs_resolved.relative_to(root_resolved)
    except ValueError:
        raise ValueError(
            f"Path {absolute_path} is outside project root {project_root}"
        ) from None
    return rel.as_posix()
