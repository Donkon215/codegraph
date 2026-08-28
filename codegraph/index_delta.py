from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List

from codegraph.constants import INDEX_DIR
from codegraph.logging_config import get_logger
from codegraph.storage import resolve_path

logger = get_logger("index.delta")


def _index_dir(project_root: Path) -> Path:
    return resolve_path(project_root, INDEX_DIR)


def _connect(db_path: Path, readonly: bool = False) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if readonly:
        uri = f"file:{db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=10)
    else:
        conn = sqlite3.connect(str(db_path), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    return conn


def update_index_delta(
    changed_node_ids: List[str],
    graph0: Any,
    graph1: Any,
    workflow: Any,
    project_root: Path,
    build_all_indexes_fn,
    affected_set: Any = None,
) -> int:
    db_path = _index_dir(project_root) / "codegraph.db"
    if not db_path.exists():
        logger.warning("No index found — performing full build")
        return sum(build_all_indexes_fn(graph0, graph1, workflow, project_root).values())

    conn = _connect(db_path)
    changed = set(changed_node_ids)
    # CAS may invalidate nodes that were not directly changed (e.g. a caller
    # whose callee edge was removed). Those nodes keep their stale
    # dependency_hash unless refreshed here (Issue #9).
    affected = changed | set(affected_set or set())
    updated = 0

    placeholders = ",".join("?" for _ in changed)
    if changed:
        conn.execute(f"DELETE FROM nodes WHERE id IN ({placeholders})", list(changed))
        conn.execute(
            f"DELETE FROM callers WHERE node_id IN ({placeholders}) OR caller_id IN ({placeholders})",
            list(changed) + list(changed),
        )
        conn.execute(
            f"DELETE FROM callees WHERE node_id IN ({placeholders}) OR callee_id IN ({placeholders})",
            list(changed) + list(changed),
        )
        conn.execute(f"DELETE FROM layers WHERE node_id IN ({placeholders})", list(changed))
        conn.execute(
            f"DELETE FROM tests WHERE test_id IN ({placeholders}) OR node_id IN ({placeholders})",
            list(changed) + list(changed),
        )
        conn.execute(f"DELETE FROM dependency_hashes WHERE node_id IN ({placeholders})", list(changed))

    g1_index = {n.id: n for n in graph1.nodes} if graph1 else {}
    for node in graph0.nodes:
        if node.id not in changed:
            continue
        g1 = g1_index.get(node.id)
        layer = g1.layer if g1 else 3
        arch_layer = (g1.arch_layer or "") if g1 else ""
        dep_hash = node.dependency_hash or ""
        conn.execute(
            "INSERT INTO nodes VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (node.id, node.file, node.type, node.line, node.body_hash,
             layer, arch_layer, dep_hash),
        )
        if dep_hash:
            conn.execute(
                "INSERT OR REPLACE INTO dependency_hashes VALUES (?, ?, ?, ?)",
                (node.id, dep_hash, node.body_hash, ""),
            )
        if g1:
            conn.execute("INSERT INTO layers VALUES (?, ?)", (layer, node.id))
        updated += 1

    # Refresh dependency_hash for CAS-affected nodes that were not directly
    # changed (else their stale index row survives the delta).
    if affected - changed:
        for node in graph0.nodes:
            if node.id not in affected or node.id in changed:
                continue
            dep_hash = node.dependency_hash or ""
            conn.execute(
                "UPDATE nodes SET dependency_hash = ? WHERE id = ?",
                (dep_hash, node.id),
            )
            if dep_hash:
                conn.execute(
                    "INSERT OR REPLACE INTO dependency_hashes VALUES (?, ?, ?, ?)",
                    (node.id, dep_hash, node.body_hash, ""),
                )
            updated += 1

    if workflow:
        for e in workflow.edges:
            if e.source in changed or e.target in changed:
                conn.execute(
                    "INSERT INTO callers VALUES (?, ?, ?, ?)",
                    (e.target, e.source, e.edge_type, e.confidence),
                )
                conn.execute(
                    "INSERT INTO callees VALUES (?, ?, ?, ?)",
                    (e.source, e.target, e.edge_type, e.confidence),
                )

        # G-006 — rebuild test relationships for affected nodes (Issue #6).
        # Reuse the canonical generation so the delta index stays consistent
        # with a fresh full rebuild, rather than inventing a second rule.
        from codegraph.index import _generate_test_rows

        for test_id, node_id in _generate_test_rows(workflow.edges, graph0.nodes):
            if test_id in changed or node_id in changed:
                conn.execute(
                    "INSERT INTO tests (test_id, node_id) VALUES (?, ?)",
                    (test_id, node_id),
                )

    conn.commit()
    conn.close()
    logger.info("Delta index updated: %d nodes affected", updated)
    return updated
