from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from codegraph.subsystem_graph import SubsystemGraph


CACHE_DIR = Path(".codegraph") / "cache" / "subsystems"
HISTORY_FILE = Path(".codegraph") / "architecture" / "architecture_history.json"


@dataclass
class SubsystemCacheEntry:
    root_node: str
    nodes: List[Dict[str, Any]] = field(default_factory=list)
    edges: List[Dict[str, Any]] = field(default_factory=list)
    boundary_nodes: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "root_node": self.root_node,
            "nodes": self.nodes,
            "edges": self.edges,
            "boundary_nodes": self.boundary_nodes,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SubsystemCacheEntry":
        return cls(
            root_node=str(data.get("root_node", "")),
            nodes=list(data.get("nodes", [])),
            edges=list(data.get("edges", [])),
            boundary_nodes=list(data.get("boundary_nodes", [])),
            metadata=dict(data.get("metadata", {})),
            timestamp=float(data.get("timestamp", 0.0)),
        )


class SubsystemCache:
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.cache_dir = project_root / CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, root_node: str) -> Path:
        safe = root_node.replace("::", "__").replace("/", "_").replace("\\", "_")
        return self.cache_dir / f"{safe}.json"

    def get(self, root_node: str) -> Optional[SubsystemCacheEntry]:
        path = self._path_for(root_node)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return SubsystemCacheEntry.from_dict(data)
        except (json.JSONDecodeError, OSError, ValueError, TypeError):
            return None

    def put(self, root_node: str, subsystem: SubsystemGraph) -> SubsystemCacheEntry:
        entry = SubsystemCacheEntry(
            root_node=root_node,
            nodes=[dict(node) for node in subsystem.nodes],
            edges=[dict(edge) for edge in subsystem.edges],
            boundary_nodes=list(subsystem.boundary_nodes),
            metadata=dict(subsystem.metadata),
            timestamp=time.time(),
        )
        self._path_for(root_node).write_text(
            json.dumps(entry.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return entry

    def clear(self) -> int:
        removed = 0
        for file in self.cache_dir.glob("*.json"):
            try:
                file.unlink()
                removed += 1
            except OSError:
                continue
        return removed

    def invalidate_for_nodes(self, affected_nodes: Set[str]) -> int:
        if not affected_nodes:
            return 0
        removed = 0
        for file in self.cache_dir.glob("*.json"):
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            nodes = {str(node.get("id", "")) for node in data.get("nodes", [])}
            root = str(data.get("root_node", ""))
            if root in affected_nodes or (nodes & affected_nodes):
                try:
                    file.unlink()
                    removed += 1
                except OSError:
                    continue
        return removed

    def is_valid(self, entry: Optional[SubsystemCacheEntry]) -> bool:
        if entry is None:
            return False
        return entry.timestamp >= _last_graph_change_timestamp(self.project_root)

    def entry_to_subsystem(self, entry: SubsystemCacheEntry) -> SubsystemGraph:
        return SubsystemGraph(
            nodes=[dict(node) for node in entry.nodes],
            edges=[dict(edge) for edge in entry.edges],
            boundary_nodes=list(entry.boundary_nodes),
            metadata=dict(entry.metadata),
        )


def _last_graph_change_timestamp(project_root: Path) -> float:
    history_path = project_root / HISTORY_FILE
    if not history_path.exists():
        return 0.0
    try:
        payload = json.loads(history_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return 0.0

    entries = payload.get("entries", [])
    if not entries:
        return 0.0

    latest = entries[-1]
    ts = latest.get("timestamp") or latest.get("changed_at") or 0.0
    if isinstance(ts, (int, float)):
        return float(ts)
    try:
        # fallback for ISO strings
        from datetime import datetime

        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def cache_status(project_root: Path) -> Dict[str, Any]:
    cache = SubsystemCache(project_root)
    files = sorted(cache.cache_dir.glob("*.json"))
    return {
        "cache_dir": str(cache.cache_dir),
        "entries": len(files),
        "files": [f.name for f in files],
        "last_graph_change": _last_graph_change_timestamp(project_root),
    }
