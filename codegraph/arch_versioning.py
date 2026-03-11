"""codegraph.arch_versioning — Architecture Versioning.

Tracks architecture versions in ``.codegraph/architecture/versions/``.
Each version is a snapshot of ``system.json`` with metadata.

Capabilities:
  - Save new version on every architecture change
  - List version history
  - Diff two versions
  - Rollback to a previous version
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from codegraph.logging_config import get_logger

logger = get_logger("arch_versioning")

VERSIONS_DIR = "architecture/versions"
MANIFEST_FILE = "manifest.json"


@dataclass
class ArchVersion:
    """A single architecture version snapshot."""

    version: int
    timestamp: str
    description: str = ""
    author: str = "codegraph"
    score: float = 0.0
    grade: str = ""
    subsystem_count: int = 0
    component_count: int = 0
    edge_count: int = 0
    constraint_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "timestamp": self.timestamp,
            "description": self.description,
            "author": self.author,
            "score": self.score,
            "grade": self.grade,
            "subsystem_count": self.subsystem_count,
            "component_count": self.component_count,
            "edge_count": self.edge_count,
            "constraint_count": self.constraint_count,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> ArchVersion:
        return cls(
            version=d.get("version", 0),
            timestamp=d.get("timestamp", ""),
            description=d.get("description", ""),
            author=d.get("author", "codegraph"),
            score=d.get("score", 0.0),
            grade=d.get("grade", ""),
            subsystem_count=d.get("subsystem_count", 0),
            component_count=d.get("component_count", 0),
            edge_count=d.get("edge_count", 0),
            constraint_count=d.get("constraint_count", 0),
        )


@dataclass
class ArchVersionDiff:
    """Diff between two architecture versions."""

    from_version: int
    to_version: int
    added_subsystems: List[str] = field(default_factory=list)
    removed_subsystems: List[str] = field(default_factory=list)
    added_edges: List[str] = field(default_factory=list)
    removed_edges: List[str] = field(default_factory=list)
    added_constraints: List[str] = field(default_factory=list)
    removed_constraints: List[str] = field(default_factory=list)
    score_delta: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "from_version": self.from_version,
            "to_version": self.to_version,
            "added_subsystems": self.added_subsystems,
            "removed_subsystems": self.removed_subsystems,
            "added_edges": self.added_edges,
            "removed_edges": self.removed_edges,
            "added_constraints": self.added_constraints,
            "removed_constraints": self.removed_constraints,
            "score_delta": round(self.score_delta, 3),
        }

    def format(self) -> str:
        lines = [f"Architecture Diff: v{self.from_version} → v{self.to_version}"]
        if self.score_delta:
            lines.append(f"  Score delta: {self.score_delta:+.3f}")
        if self.added_subsystems:
            lines.append(f"  + Subsystems: {', '.join(self.added_subsystems)}")
        if self.removed_subsystems:
            lines.append(f"  - Subsystems: {', '.join(self.removed_subsystems)}")
        if self.added_edges:
            lines.append(f"  + Edges: {len(self.added_edges)}")
        if self.removed_edges:
            lines.append(f"  - Edges: {len(self.removed_edges)}")
        if self.added_constraints:
            lines.append(f"  + Constraints: {len(self.added_constraints)}")
        if self.removed_constraints:
            lines.append(f"  - Constraints: {len(self.removed_constraints)}")
        if not any([self.added_subsystems, self.removed_subsystems,
                    self.added_edges, self.removed_edges,
                    self.added_constraints, self.removed_constraints]):
            lines.append("  No structural changes")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# Version Store
# ═══════════════════════════════════════════════════════════════════════


def _versions_dir(project_root: Path) -> Path:
    return project_root / ".codegraph" / VERSIONS_DIR


def _load_manifest(project_root: Path) -> Dict[str, Any]:
    path = _versions_dir(project_root) / MANIFEST_FILE
    if not path.exists():
        return {"versions": [], "latest": 0}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_manifest(
    project_root: Path, manifest: Dict[str, Any],
) -> None:
    vdir = _versions_dir(project_root)
    vdir.mkdir(parents=True, exist_ok=True)
    path = vdir / MANIFEST_FILE
    path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def save_version(
    project_root: Path,
    description: str = "",
    score: float = 0.0,
    grade: str = "",
) -> ArchVersion:
    """Snapshot current system.json as a new version."""
    system_path = (project_root / ".codegraph" / "architecture"
                   / "system.json")
    if not system_path.exists():
        raise FileNotFoundError("No system.json to version")

    system_data = json.loads(system_path.read_text(encoding="utf-8"))

    manifest = _load_manifest(project_root)
    next_version = manifest.get("latest", 0) + 1

    version = ArchVersion(
        version=next_version,
        timestamp=datetime.now(timezone.utc).isoformat(),
        description=description,
        score=score,
        grade=grade,
        subsystem_count=len(system_data.get("subsystems", [])),
        component_count=sum(
            len(s.get("components", []))
            for s in system_data.get("subsystems", [])
        ),
        edge_count=len(system_data.get("edges", [])),
        constraint_count=len(system_data.get("constraints", [])),
    )

    # Save snapshot
    vdir = _versions_dir(project_root)
    vdir.mkdir(parents=True, exist_ok=True)
    snapshot_path = vdir / f"v{next_version}.json"
    snapshot_path.write_text(
        json.dumps({
            "version_meta": version.to_dict(),
            "system": system_data,
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Update manifest
    manifest["versions"].append(version.to_dict())
    manifest["latest"] = next_version
    _save_manifest(project_root, manifest)

    logger.info("Saved architecture version %d", next_version)
    return version


def list_versions(project_root: Path) -> List[ArchVersion]:
    """List all architecture versions."""
    manifest = _load_manifest(project_root)
    return [ArchVersion.from_dict(v) for v in manifest.get("versions", [])]


def load_version(
    project_root: Path, version: int,
) -> Optional[Dict[str, Any]]:
    """Load a specific version's system.json snapshot."""
    path = _versions_dir(project_root) / f"v{version}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("system", data)


def diff_versions(
    project_root: Path,
    from_version: int,
    to_version: int,
) -> Optional[ArchVersionDiff]:
    """Diff two architecture versions."""
    old_data = load_version(project_root, from_version)
    new_data = load_version(project_root, to_version)
    if old_data is None or new_data is None:
        return None

    old_subs = {s["name"] for s in old_data.get("subsystems", [])}
    new_subs = {s["name"] for s in new_data.get("subsystems", [])}

    old_edges = {
        f"{e.get('from', '')} -> {e.get('to', '')}"
        for e in old_data.get("edges", [])
    }
    new_edges = {
        f"{e.get('from', '')} -> {e.get('to', '')}"
        for e in new_data.get("edges", [])
    }

    old_constraints = {
        f"{c.get('source', '')} -/-> {c.get('target', '')}"
        for c in old_data.get("constraints", [])
    }
    new_constraints = {
        f"{c.get('source', '')} -/-> {c.get('target', '')}"
        for c in new_data.get("constraints", [])
    }

    # Get scores from manifest
    manifest = _load_manifest(project_root)
    versions_map = {v["version"]: v for v in manifest.get("versions", [])}
    old_score = versions_map.get(from_version, {}).get("score", 0.0)
    new_score = versions_map.get(to_version, {}).get("score", 0.0)

    return ArchVersionDiff(
        from_version=from_version,
        to_version=to_version,
        added_subsystems=sorted(new_subs - old_subs),
        removed_subsystems=sorted(old_subs - new_subs),
        added_edges=sorted(new_edges - old_edges),
        removed_edges=sorted(old_edges - new_edges),
        added_constraints=sorted(new_constraints - old_constraints),
        removed_constraints=sorted(old_constraints - new_constraints),
        score_delta=new_score - old_score,
    )


def rollback_version(
    project_root: Path, version: int,
) -> bool:
    """Rollback system.json to a previous version.

    Creates a new version snapshot of current state before overwriting.
    """
    snapshot = load_version(project_root, version)
    if snapshot is None:
        return False

    # Save current as a version before rollback
    save_version(
        project_root,
        description=f"Pre-rollback snapshot (rolling back to v{version})",
    )

    # Overwrite system.json
    system_path = (project_root / ".codegraph" / "architecture"
                   / "system.json")
    system_path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    logger.info("Rolled back architecture to version %d", version)
    return True


def format_version_history(versions: List[ArchVersion]) -> str:
    """Format version history for display."""
    if not versions:
        return "No architecture versions found."
    lines = ["Architecture Version History:"]
    for v in reversed(versions):
        grade_str = f" [{v.grade}]" if v.grade else ""
        lines.append(
            f"  v{v.version}{grade_str} — {v.description or 'no description'} "
            f"({v.subsystem_count} subsystems, {v.edge_count} edges) "
            f"@ {v.timestamp[:19]}"
        )
    return "\n".join(lines)
