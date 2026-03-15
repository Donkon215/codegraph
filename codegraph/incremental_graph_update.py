from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Set

from codegraph.architecture_graph import ArchitectureGraph
from codegraph.graph_partitioning import build_partitions, load_partitions, save_partitions
from codegraph.subsystem_cache import SubsystemCache


STATE_FILE = Path(".codegraph") / "incremental" / "state.json"
HISTORY_FILE = Path(".codegraph") / "architecture" / "architecture_history.json"


@dataclass
class IncrementalUpdateResult:
    changed_files: List[str] = field(default_factory=list)
    changed_nodes: List[str] = field(default_factory=list)
    removed_nodes: List[str] = field(default_factory=list)
    changed_edges: int = 0
    recomputed_partitions: List[str] = field(default_factory=list)
    invalidated_cache_entries: int = 0
    status: str = "ok"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "changed_files": self.changed_files,
            "changed_nodes": self.changed_nodes,
            "removed_nodes": self.removed_nodes,
            "changed_edges": self.changed_edges,
            "recomputed_partitions": self.recomputed_partitions,
            "invalidated_cache_entries": self.invalidated_cache_entries,
        }


def detect_changed_files(project_root: Path) -> List[str]:
    commands = [
        ["git", "diff", "--name-only"],
        ["git", "diff", "--name-only", "--cached"],
    ]
    files: Set[str] = set()
    for cmd in commands:
        try:
            out = subprocess.check_output(cmd, cwd=str(project_root), text=True)
        except Exception:
            continue
        for line in out.splitlines():
            rel = line.strip().replace("\\", "/")
            if not rel:
                continue
            if rel.endswith(".py"):
                files.add(rel)
    return sorted(files)


def incremental_update_graph(project_root: Path, graph: ArchitectureGraph) -> IncrementalUpdateResult:
    changed_files = detect_changed_files(project_root)
    result = IncrementalUpdateResult(changed_files=changed_files)
    if not changed_files:
        result.status = "no_changes"
        return result

    file_set = set(changed_files)
    old_nodes = [dict(node) for node in graph.nodes]
    old_edges = [dict(edge) for edge in graph.edges]

    removed_nodes: Set[str] = set()
    retained_nodes: List[Dict[str, Any]] = []
    changed_nodes: List[str] = []

    for node in old_nodes:
        node_id = str(node.get("id", "")).strip()
        file_path = str(node.get("file", "")).replace("\\", "/")
        if file_path in file_set:
            removed_nodes.add(node_id)
            continue
        retained_nodes.append(node)

    # Keep changed-file nodes from the current in-memory graph snapshot.
    for node in graph.nodes:
        node_id = str(node.get("id", "")).strip()
        file_path = str(node.get("file", "")).replace("\\", "/")
        if file_path in file_set:
            retained_nodes.append(dict(node))
            changed_nodes.append(node_id)

    graph.nodes = retained_nodes

    edge_count_before = len(graph.edges)
    graph.edges = [
        edge
        for edge in old_edges
        if str(edge.get("source", "")).strip() not in removed_nodes
        and str(edge.get("target", "")).strip() not in removed_nodes
    ]
    graph.rebuild_indexes()

    result.changed_nodes = sorted(set(changed_nodes))
    result.removed_nodes = sorted(removed_nodes)
    result.changed_edges = abs(edge_count_before - len(graph.edges))

    # Partition maintenance: refresh partition files, and report impacted partition ids.
    previous = load_partitions(project_root)
    previous_map = previous.node_to_partition if previous else {}
    affected_partitions = {
        pid
        for node_id, pid in previous_map.items()
        if node_id in removed_nodes or node_id in result.changed_nodes
    }

    refreshed = build_partitions(graph)
    save_partitions(project_root, refreshed)

    if affected_partitions:
        result.recomputed_partitions = sorted(affected_partitions)
    else:
        result.recomputed_partitions = sorted(refreshed.partitions.keys())

    # Cache invalidation based on changed node set.
    cache = SubsystemCache(project_root)
    affected_nodes = set(result.changed_nodes) | set(result.removed_nodes)
    result.invalidated_cache_entries = cache.invalidate_for_nodes(affected_nodes)

    _write_incremental_state(project_root, {
        "updated_at": time.time(),
        "changed_files": changed_files,
        "changed_nodes": result.changed_nodes,
        "removed_nodes": result.removed_nodes,
        "changed_edges": result.changed_edges,
    })
    _append_architecture_history(project_root, {
        "timestamp": time.time(),
        "event": "incremental_update",
        "changed_files": changed_files,
        "changed_nodes": result.changed_nodes,
        "removed_nodes": result.removed_nodes,
        "changed_edges": result.changed_edges,
    })

    return result


def _write_incremental_state(project_root: Path, payload: Dict[str, Any]) -> None:
    path = project_root / STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _append_architecture_history(project_root: Path, entry: Dict[str, Any]) -> None:
    path = project_root / HISTORY_FILE
    path.parent.mkdir(parents=True, exist_ok=True)

    payload: Dict[str, Any]
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            payload = {}
    else:
        payload = {}

    entries = payload.get("entries", [])
    if not isinstance(entries, list):
        entries = []
    entries.append(entry)
    payload["entries"] = entries[-1000:]
    payload["last_cache_timestamp"] = time.time()
    payload["last_graph_change"] = entry.get("timestamp", time.time())

    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
