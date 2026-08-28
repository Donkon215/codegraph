"""Canonical index snapshots for build/delta equivalence (Issue #9).

The equivalence invariant for Issue #9 is defined over *logical rows*, not
SQLite file bytes (WAL mode, row ordering, and internal metadata make a byte
comparison meaningless). This module reads the index database into a canonical,
sort-stable structure so two indexes produced by different code paths (full
build vs build -> delta) can be compared semantically.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from codegraph.index_maintenance import _check_version, _connect, _index_dir

_TABLE_QUERIES: Dict[str, str] = {
    "nodes": (
        "SELECT id, file, type, line, body_hash, layer, arch_layer, dependency_hash "
        "FROM nodes ORDER BY id"
    ),
    "callers": (
        "SELECT node_id, caller_id, edge_type, confidence "
        "FROM callers ORDER BY node_id, caller_id, edge_type, confidence"
    ),
    "callees": (
        "SELECT node_id, callee_id, edge_type, confidence "
        "FROM callees ORDER BY node_id, callee_id, edge_type, confidence"
    ),
    "layers": "SELECT layer, node_id FROM layers ORDER BY layer, node_id",
    "tests": "SELECT test_id, node_id FROM tests ORDER BY test_id, node_id",
    # NOTE: `computed_at` is intentionally excluded — it is a wall-clock
    # timestamp, so two builds of identical source would never compare equal.
    "dependency_hashes": (
        "SELECT node_id, dependency_hash, body_hash "
        "FROM dependency_hashes ORDER BY node_id"
    ),
}

TABLE_NAMES = tuple(_TABLE_QUERIES)


@dataclass
class IndexSnapshot:
    tables: Dict[str, List[Tuple]] = field(default_factory=dict)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, IndexSnapshot):
            return NotImplemented
        return self.tables == other.tables

    def __repr__(self) -> str:
        sizes = {k: len(v) for k, v in self.tables.items()}
        return f"IndexSnapshot({sizes})"


def snapshot_index(project_root: Path) -> IndexSnapshot:
    """Read the index database into a canonical :class:`IndexSnapshot`."""
    db_path = _index_dir(Path(project_root)) / "codegraph.db"
    if not db_path.exists():
        return IndexSnapshot()
    conn = _connect(db_path, readonly=True)
    try:
        if not _check_version(conn):
            raise ValueError("Index schema version mismatch — rebuild needed")
        return snapshot_conn(conn)
    finally:
        conn.close()


def snapshot_conn(conn: sqlite3.Connection) -> IndexSnapshot:
    """Snapshot an already-open index database connection (G-010).

    Used to canonicalise an in-memory reference index (built from the current
    source) so it can be diffed against the on-disk index without a second
    comparison implementation.
    """
    tables: Dict[str, List[Tuple]] = {}
    for name, query in _TABLE_QUERIES.items():
        try:
            tables[name] = [tuple(row) for row in conn.execute(query).fetchall()]
        except sqlite3.OperationalError:
            tables[name] = []
    return IndexSnapshot(tables)


def diff_index_snapshots(
    a: IndexSnapshot, b: IndexSnapshot, table_names: Optional[tuple] = None
) -> Dict[str, dict]:
    """Per-table difference between two snapshots.

    Returns a mapping of table name -> ``{"only_in_delta": [...], "only_in_full": [...]}``.
    Tables without differences are omitted so the report stays focused.

    ``table_names`` restricts the comparison (defaults to all known tables).
    """
    out: Dict[str, dict] = {}
    for name in (table_names or TABLE_NAMES):
        rows_a = a.tables.get(name, [])
        rows_b = b.tables.get(name, [])
        if set(rows_a) == set(rows_b):
            continue
        only_delta = [r for r in rows_a if r not in set(rows_b)]
        only_full = [r for r in rows_b if r not in set(rows_a)]
        out[name] = {"only_in_delta": only_delta, "only_in_full": only_full}
    return out
