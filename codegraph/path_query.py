"""codegraph.path_query — Pattern-based path queries across the dependency graph.

Supports glob-pattern path queries like:
    codegraph path "api/* -> database/*"
    codegraph path "controller/* -> repository/*"

Detects forbidden paths for architecture enforcement.
"""

from __future__ import annotations

import fnmatch
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from codegraph.index import IndexStore
from codegraph.logging_config import get_logger

logger = get_logger("path_query")


@dataclass
class PathResult:
    """Result of a pattern-based path query."""

    source_pattern: str = ""
    target_pattern: str = ""
    paths_found: List[List[str]] = field(default_factory=list)
    source_matches: int = 0
    target_matches: int = 0
    violation: bool = False

    @property
    def has_paths(self) -> bool:
        return len(self.paths_found) > 0

    def to_dict(self) -> dict:
        return {
            "source_pattern": self.source_pattern,
            "target_pattern": self.target_pattern,
            "paths_found": self.paths_found,
            "source_matches": self.source_matches,
            "target_matches": self.target_matches,
            "violation": self.violation,
            "total_paths": len(self.paths_found),
        }

    def format(self, verbose: bool = False) -> str:
        lines: List[str] = []
        if not self.paths_found:
            lines.append(f"No path found: {self.source_pattern} -> {self.target_pattern}")
            return "\n".join(lines)

        lines.append(
            f"Found {len(self.paths_found)} path(s): "
            f"{self.source_pattern} -> {self.target_pattern}"
        )
        for i, path in enumerate(self.paths_found):
            lines.append(f"\n  Path {i + 1}:")
            for j, node in enumerate(path):
                prefix = "    -> " if j > 0 else "    "
                lines.append(f"{prefix}{node}")
        return "\n".join(lines)


def find_pattern_paths(
    source_pattern: str,
    target_pattern: str,
    index: IndexStore,
    *,
    max_depth: int = 20,
    max_paths: int = 10,
) -> PathResult:
    """Find paths between nodes matching source and target glob patterns."""
    result = PathResult(
        source_pattern=source_pattern,
        target_pattern=target_pattern,
    )

    all_nodes = _get_all_node_ids(index)
    sources = [n for n in all_nodes if fnmatch.fnmatch(n, source_pattern)]
    targets = set(n for n in all_nodes if fnmatch.fnmatch(n, target_pattern))

    result.source_matches = len(sources)
    result.target_matches = len(targets)

    if not sources or not targets:
        return result

    for source in sources:
        if len(result.paths_found) >= max_paths:
            break
        path = _bfs_to_set(source, targets, index, max_depth)
        if path:
            result.paths_found.append(path)

    return result


def check_forbidden_path(
    source_pattern: str,
    target_pattern: str,
    index: IndexStore,
    *,
    max_depth: int = 20,
) -> PathResult:
    """Check if any forbidden path exists between source and target patterns."""
    result = find_pattern_paths(
        source_pattern, target_pattern, index,
        max_depth=max_depth, max_paths=5,
    )
    result.violation = result.has_paths
    return result


def _bfs_to_set(
    source: str,
    targets: Set[str],
    index: IndexStore,
    max_depth: int,
) -> List[str]:
    """BFS from source to any node in targets set."""
    if source in targets:
        return [source]

    visited: Set[str] = {source}
    queue: deque[Tuple[str, List[str]]] = deque([(source, [source])])

    while queue:
        current, path = queue.popleft()
        if len(path) > max_depth:
            continue
        for callee in index.get_callees(current):
            if callee in targets:
                return path + [callee]
            if callee not in visited:
                visited.add(callee)
                queue.append((callee, path + [callee]))
    return []


def _get_all_node_ids(index: IndexStore) -> List[str]:
    """Get all node IDs from the index."""
    try:
        rows = index._get_conn().execute("SELECT id FROM nodes").fetchall()
        return [r[0] for r in rows]
    except Exception:
        return []
