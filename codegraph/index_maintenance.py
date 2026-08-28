from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from codegraph.constants import GRAPHS_DIR, INDEX_DIR
from codegraph.storage import resolve_path

SCHEMA_VERSION = 1


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


def _check_version(conn: sqlite3.Connection) -> bool:
    try:
        row = conn.execute("SELECT version FROM schema_version").fetchone()
        if row is None:
            return False
        return row[0] == SCHEMA_VERSION
    except sqlite3.OperationalError:
        return False


@dataclass
class ConsistencyIssue:
    table: str
    message: str


def rebuild_index(project_root: Path, build_all_indexes_fn) -> Dict[str, int]:
    from codegraph.extractor import load_graph0
    from codegraph.workflow import load_workflow
    from codegraph.models.graph1 import Graph1

    graph0 = load_graph0(project_root)
    workflow = load_workflow(project_root)

    graph1_path = resolve_path(project_root, GRAPHS_DIR, "graph1.json")
    if graph1_path.exists():
        graph1 = Graph1.from_json(graph1_path.read_text(encoding="utf-8"))
    else:
        graph1 = Graph1()

    return build_all_indexes_fn(graph0, graph1, workflow, project_root)


def check_index_consistency(project_root: Path) -> List[ConsistencyIssue]:
    from codegraph.extractor import load_graph0
    from codegraph.workflow import load_workflow
    from codegraph.models.graph1 import Graph1

    issues: List[ConsistencyIssue] = []
    db_path = _index_dir(project_root) / "codegraph.db"

    if not db_path.exists():
        issues.append(ConsistencyIssue("all", "Index database does not exist"))
        return issues

    conn = _connect(db_path, readonly=True)

    if not _check_version(conn):
        issues.append(ConsistencyIssue("schema", "Schema version mismatch — rebuild needed"))
        conn.close()
        return issues

    graph0 = load_graph0(project_root)

    graph1_path = resolve_path(project_root, GRAPHS_DIR, "graph1.json")
    if graph1_path.exists():
        graph1 = Graph1.from_json(graph1_path.read_text(encoding="utf-8"))
    else:
        graph1 = Graph1()

    workflow = load_workflow(project_root)

    try:
        indexed_ids = {row[0] for row in conn.execute("SELECT id FROM nodes").fetchall()}
        graph_ids = {n.id for n in graph0.nodes}

        missing = graph_ids - indexed_ids
        extra = indexed_ids - graph_ids
        if missing:
            issues.append(ConsistencyIssue("nodes", f"{len(missing)} Graph_0 nodes missing from index"))
        if extra:
            issues.append(ConsistencyIssue("nodes", f"{len(extra)} extra nodes in index"))
    except sqlite3.OperationalError:
        issues.append(ConsistencyIssue("nodes", "Table does not exist"))

    try:
        callers_count = conn.execute("SELECT COUNT(*) FROM callers").fetchone()[0]
        callees_count = conn.execute("SELECT COUNT(*) FROM callees").fetchone()[0]
        expected = len(workflow.edges)
        if callers_count != expected:
            issues.append(ConsistencyIssue("callers", f"Row count {callers_count} != expected {expected}"))
        if callees_count != expected:
            issues.append(ConsistencyIssue("callees", f"Row count {callees_count} != expected {expected}"))
    except sqlite3.OperationalError:
        issues.append(ConsistencyIssue("callers/callees", "Table(s) do not exist"))

    conn.close()

    # Logical divergence: does the on-disk index equal a fresh build of the
    # current source? Reuses the canonical snapshot/diff machinery (G-010) so
    # content is compared semantically — a corrupted row with the same count
    # (e.g. A→B rewritten to A→C) is still detected.
    try:
        from codegraph.index import build_reference_snapshot
        from codegraph.index_snapshot import diff_index_snapshots, snapshot_index

        reference, dep_ok = build_reference_snapshot(graph0, graph1, workflow, project_root)
        actual = snapshot_index(project_root)
        if not dep_ok:
            # CAS was unavailable when building the reference; compare the actual
            # index structurally too so a missing hash column cannot be reported
            # as a divergence.
            from codegraph.index import _strip_dependency_hash

            reference = _strip_dependency_hash(reference)
            actual = _strip_dependency_hash(actual)
        logical = diff_index_snapshots(
            reference, actual, table_names=tuple(reference.tables.keys())
        )
        for table, diff in logical.items():
            only_delta = diff.get("only_in_delta", [])
            only_full = diff.get("only_in_full", [])
            if only_delta or only_full:
                issues.append(ConsistencyIssue(
                    table,
                    f"Logical mismatch in '{table}': {len(only_delta)} unexpected, "
                    f"{len(only_full)} missing vs expected index",
                ))
    except Exception as exc:  # pragma: no cover - defensive: never break the check
        issues.append(ConsistencyIssue("logical", f"Logical consistency check failed: {exc}"))

    return issues
