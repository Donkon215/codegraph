"""codegraph.build_quality - machine-readable record of how good a build is.

Extraction and edge building each know about defects that silently degrade
every downstream number: unresolved calls become *absent* edges (indistinguishable
from calls that do not exist), node-id collisions rename a definition so
name-based edges attach to the wrong node, and per-extractor warnings are
logged where nobody reads them.

Logging them is not enough -- a saved analysis report has to be able to say how
much to trust it. Each stage records its own fields here; the record is merged,
so stage order does not matter.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

BUILD_QUALITY_PATH = Path(".codegraph") / "build_quality.json"


def record_build_quality(project_root: Path, **fields: Any) -> Path:
    """Merge *fields* into the project's build-quality record and return its path."""
    path = project_root / BUILD_QUALITY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    data: Dict[str, Any] = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, ValueError):
            data = {}  # corrupt record is replaced, never fatal to a build
    data.update(fields)
    data["recorded_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_build_quality(project_root: Path) -> Optional[Dict[str, Any]]:
    """Return the build-quality record, or None when there is none."""
    path = project_root / BUILD_QUALITY_PATH
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def unresolved_call_summary(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Summarise extraction defects for display next to an analysis report.

    Returns an explicit "unknown" rather than 0 when no build-quality record
    exists, so a report never implies a clean build it cannot prove.
    """
    if not data:
        return {
            "build_quality": "unknown",
            "unresolved_calls": None,
            "collisions": None,
            "warnings": None,
        }
    return {
        "build_quality": "recorded",
        "unresolved_calls": data.get("unresolved_calls"),
        "collisions": len(data.get("collision_ids", []) or []),
        "warnings": len(data.get("warnings", []) or []),
    }


def collision_notes(data: Optional[Dict[str, Any]]) -> List[str]:
    """Human-readable collision descriptions recorded at extraction time."""
    if not data:
        return []
    notes = data.get("collision_ids")
    return [str(note) for note in notes] if isinstance(notes, list) else []