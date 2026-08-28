"""codegraph.index — Graph index layer (SQLite).

Covers tasks G-001 through G-022:
  G-001  Index storage backend (SQLite, WAL mode)
  G-002  Nodes index table
  G-003  Callers index table
  G-004  Callees index table
  G-005  Layers index table
  G-006  Tests index table
  G-007  Full index build orchestrator
  G-008  Delta index update
  G-009  Index rebuild command
  G-010  Index consistency check
  G-011  Index query interface (IndexStore)
  G-012  Index node search
  G-013  Recursive dependency query
  G-014  Shortest path query
  G-015  Performance benchmarks (benchmarks/index_benchmark.py)
  G-016  Index database migrations
  G-017  Index locking for concurrent access
  G-018  Index statistics
  G-019  Arch layer index
  G-020  Index export for debugging
  G-021  Dependency hash index table (CAS)
  G-022  Dependency hash in nodes table (CAS)
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from codegraph.constants import CODEGRAPH_DIR, INDEX_DIR
from codegraph.index_inspect import (
    IndexStats,
    export_index as _export_index_impl,
    index_statistics as _index_statistics_impl,
)
from codegraph.logging_config import get_logger
from codegraph.storage import resolve_path

logger = get_logger("index")

# ── Schema version ─────────────────────────────────────────────────────

SCHEMA_VERSION = 1


# ═══════════════════════════════════════════════════════════════════════
# G-001 — Database connection management
# ═══════════════════════════════════════════════════════════════════════


def _index_dir(project_root: Path) -> Path:
    """Return the .codegraph/index/ directory path."""
    return resolve_path(project_root, INDEX_DIR)


def _db_path(project_root: Path, name: str) -> Path:
    """Return path for a specific index database."""
    return _index_dir(project_root) / f"{name}.db"


def _connect(db_path: Path, readonly: bool = False) -> sqlite3.Connection:
    """Open a SQLite connection with WAL mode and proper settings (G-001, G-017)."""
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


def _ensure_version_table(conn: sqlite3.Connection) -> None:
    """Create the schema_version table if needed (G-016)."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version "
        "(version INTEGER NOT NULL)"
    )
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    if row is None:
        conn.execute("INSERT INTO schema_version VALUES (?)", (SCHEMA_VERSION,))
        conn.commit()


def _check_version(conn: sqlite3.Connection) -> bool:
    """Check if schema version matches current. Returns False if rebuild needed (G-016)."""
    try:
        row = conn.execute("SELECT version FROM schema_version").fetchone()
        if row is None:
            return False
        return row[0] == SCHEMA_VERSION
    except sqlite3.OperationalError:
        return False


# ═══════════════════════════════════════════════════════════════════════
# G-002 — Nodes index table
# ═══════════════════════════════════════════════════════════════════════


def _create_nodes_table(conn: sqlite3.Connection) -> None:
    """Create nodes table with arch_layer and dependency_hash columns (G-002, G-019, G-022)."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS nodes ("
        "  id TEXT PRIMARY KEY,"
        "  file TEXT NOT NULL,"
        "  type TEXT NOT NULL,"
        "  line INTEGER NOT NULL,"
        "  body_hash TEXT NOT NULL,"
        "  layer INTEGER DEFAULT 3,"
        "  arch_layer TEXT DEFAULT '',"
        "  dependency_hash TEXT DEFAULT ''"
        ")"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_nodes_file ON nodes(file)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_nodes_layer ON nodes(layer)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_nodes_arch_layer ON nodes(arch_layer)")


def build_nodes_index(
    conn: sqlite3.Connection,
    graph0_nodes: list,
    graph1_index: Dict[str, Any],
) -> int:
    """Populate nodes table from Graph_0 and Graph_1 data (G-002, G-019, G-022)."""
    _create_nodes_table(conn)
    conn.execute("DELETE FROM nodes")

    rows = []
    for node in graph0_nodes:
        g1 = graph1_index.get(node.id)
        layer = g1.layer if g1 else 3
        arch_layer = (g1.arch_layer or "") if g1 else ""
        dep_hash = node.dependency_hash or ""
        rows.append((
            node.id, node.file, node.type, node.line,
            node.body_hash, layer, arch_layer, dep_hash,
        ))

    conn.executemany(
        "INSERT INTO nodes (id, file, type, line, body_hash, layer, arch_layer, dependency_hash) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    return len(rows)


# ═══════════════════════════════════════════════════════════════════════
# G-003 — Callers index table
# ═══════════════════════════════════════════════════════════════════════


def _create_callers_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS callers ("
        "  node_id TEXT NOT NULL,"
        "  caller_id TEXT NOT NULL,"
        "  edge_type TEXT DEFAULT 'call',"
        "  confidence TEXT DEFAULT 'static'"
        ")"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_callers_node ON callers(node_id)")


def build_callers_index(conn: sqlite3.Connection, edges: list) -> int:
    """Populate callers table (reverse call graph) (G-003)."""
    _create_callers_table(conn)
    conn.execute("DELETE FROM callers")

    rows = [(e.target, e.source, e.edge_type, e.confidence) for e in edges]
    conn.executemany(
        "INSERT INTO callers (node_id, caller_id, edge_type, confidence) VALUES (?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    return len(rows)


# ═══════════════════════════════════════════════════════════════════════
# G-004 — Callees index table
# ═══════════════════════════════════════════════════════════════════════


def _create_callees_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS callees ("
        "  node_id TEXT NOT NULL,"
        "  callee_id TEXT NOT NULL,"
        "  edge_type TEXT DEFAULT 'call',"
        "  confidence TEXT DEFAULT 'static'"
        ")"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_callees_node ON callees(node_id)")


def build_callees_index(conn: sqlite3.Connection, edges: list) -> int:
    """Populate callees table (forward call graph) (G-004)."""
    _create_callees_table(conn)
    conn.execute("DELETE FROM callees")

    rows = [(e.source, e.target, e.edge_type, e.confidence) for e in edges]
    conn.executemany(
        "INSERT INTO callees (node_id, callee_id, edge_type, confidence) VALUES (?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    return len(rows)


# ═══════════════════════════════════════════════════════════════════════
# G-005 — Layers index table
# ═══════════════════════════════════════════════════════════════════════


def _create_layers_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS layers ("
        "  layer INTEGER NOT NULL,"
        "  node_id TEXT NOT NULL"
        ")"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_layers_layer ON layers(layer)")


def build_layers_index(conn: sqlite3.Connection, graph1_nodes: list) -> int:
    """Populate layers table (G-005)."""
    _create_layers_table(conn)
    conn.execute("DELETE FROM layers")

    rows = [(n.layer, n.id) for n in graph1_nodes]
    conn.executemany("INSERT INTO layers (layer, node_id) VALUES (?, ?)", rows)
    conn.commit()
    return len(rows)


# ═══════════════════════════════════════════════════════════════════════
# G-006 — Tests index table
# ═══════════════════════════════════════════════════════════════════════


def _create_tests_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS tests ("
        "  test_id TEXT NOT NULL,"
        "  node_id TEXT NOT NULL"
        ")"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tests_test ON tests(test_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tests_node ON tests(node_id)")


def _generate_test_rows(edges: list, graph0_nodes: list) -> List[Tuple[str, str]]:
    """Return canonical (test_id, node_id) rows from test-type workflow edges.

    This is the single source of truth for which test relationships exist. Both
    the full build and the incremental delta update must use it so the two stay
    consistent (Issue #6).
    """
    test_ids = {n.id for n in graph0_nodes
                if n.file.startswith("test") or "/test" in n.file or "\\test" in n.file}
    rows = []
    for e in edges:
        if e.edge_type == "test" or e.source in test_ids:
            rows.append((e.source, e.target))
    return rows


def build_tests_index(conn: sqlite3.Connection, edges: list, graph0_nodes: list) -> int:
    """Populate tests table from test-type workflow edges (G-006)."""
    _create_tests_table(conn)
    conn.execute("DELETE FROM tests")

    rows = _generate_test_rows(edges, graph0_nodes)

    conn.executemany("INSERT INTO tests (test_id, node_id) VALUES (?, ?)", rows)
    conn.commit()
    return len(rows)


# ═══════════════════════════════════════════════════════════════════════
# G-021 — Dependency hash index table (CAS)
# ═══════════════════════════════════════════════════════════════════════


def _create_dependency_hashes_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS dependency_hashes ("
        "  node_id TEXT PRIMARY KEY,"
        "  dependency_hash TEXT NOT NULL,"
        "  body_hash TEXT DEFAULT '',"
        "  computed_at TEXT DEFAULT ''"
        ")"
    )


def build_dependency_hash_index(
    conn: sqlite3.Connection,
    graph0_nodes: list,
) -> int:
    """Populate dependency_hashes table from Graph_0 nodes (G-021)."""
    _create_dependency_hashes_table(conn)
    conn.execute("DELETE FROM dependency_hashes")

    rows = [
        (n.id, n.dependency_hash or "", n.body_hash, "")
        for n in graph0_nodes
        if n.dependency_hash
    ]
    conn.executemany(
        "INSERT INTO dependency_hashes (node_id, dependency_hash, body_hash, computed_at) "
        "VALUES (?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    return len(rows)


# ═══════════════════════════════════════════════════════════════════════
# G-007 — Full index build orchestrator
# ═══════════════════════════════════════════════════════════════════════


def build_all_indexes(
    graph0: Any,
    graph1: Any,
    workflow: Any,
    project_root: Path,
) -> Dict[str, int]:
    """Build all index tables from graph data (G-007).

    Returns dict of table_name → row_count.
    """
    idx_dir = _index_dir(project_root)
    idx_dir.mkdir(parents=True, exist_ok=True)

    # Use a single database file for simplicity
    db_path = idx_dir / "codegraph.db"

    # Drop existing
    if db_path.exists():
        db_path.unlink()

    conn = _connect(db_path)
    _ensure_version_table(conn)

    results: Dict[str, int] = {}
    t0 = time.monotonic()

    # Build Graph_1 index for node lookups
    g1_index = {n.id: n for n in graph1.nodes} if graph1 and graph1.nodes else {}

    # G-002 nodes
    t = time.monotonic()
    results["nodes"] = build_nodes_index(conn, graph0.nodes, g1_index)
    logger.debug("nodes index: %d rows (%.2fs)", results["nodes"], time.monotonic() - t)

    # G-003 callers
    t = time.monotonic()
    edges = workflow.edges if workflow else []
    results["callers"] = build_callers_index(conn, edges)
    logger.debug("callers index: %d rows (%.2fs)", results["callers"], time.monotonic() - t)

    # G-004 callees
    t = time.monotonic()
    results["callees"] = build_callees_index(conn, edges)
    logger.debug("callees index: %d rows (%.2fs)", results["callees"], time.monotonic() - t)

    # G-005 layers
    t = time.monotonic()
    g1_nodes = graph1.nodes if graph1 else []
    results["layers"] = build_layers_index(conn, g1_nodes)
    logger.debug("layers index: %d rows (%.2fs)", results["layers"], time.monotonic() - t)

    # G-006 tests
    t = time.monotonic()
    results["tests"] = build_tests_index(conn, edges, graph0.nodes)
    logger.debug("tests index: %d rows (%.2fs)", results["tests"], time.monotonic() - t)

    # G-021 dependency hashes
    t = time.monotonic()
    results["dependency_hashes"] = build_dependency_hash_index(conn, graph0.nodes)
    logger.debug("dependency_hashes index: %d rows (%.2fs)", results["dependency_hashes"], time.monotonic() - t)

    conn.close()
    elapsed = time.monotonic() - t0
    total = sum(results.values())
    logger.info("Index built: %d total rows across %d tables (%.2fs)", total, len(results), elapsed)
    return results


# ═══════════════════════════════════════════════════════════════════════
# G-008 — Delta index update
# ═══════════════════════════════════════════════════════════════════════


def update_index_delta(
    changed_node_ids: List[str],
    graph0: Any,
    graph1: Any,
    workflow: Any,
    project_root: Path,
    affected_set: Any = None,
) -> int:
    """Incrementally update index for changed nodes only (G-008)."""
    from codegraph.index_delta import update_index_delta as _update_index_delta_impl

    return _update_index_delta_impl(
        changed_node_ids,
        graph0,
        graph1,
        workflow,
        project_root,
        build_all_indexes,
        affected_set=affected_set,
    )


# ═══════════════════════════════════════════════════════════════════════
# G-009 — Index rebuild command
# ═══════════════════════════════════════════════════════════════════════


def rebuild_index(project_root: Path) -> Dict[str, int]:
    """Rebuild index from committed graph files without re-extraction (G-009)."""
    from codegraph.index_maintenance import rebuild_index as _rebuild_index_impl

    return _rebuild_index_impl(project_root, build_all_indexes)


# ═══════════════════════════════════════════════════════════════════════
# G-010 — Index consistency check
# ═══════════════════════════════════════════════════════════════════════


from codegraph.index_maintenance import ConsistencyIssue


def check_index_consistency(project_root: Path) -> List[ConsistencyIssue]:
    """Verify index data matches current graph files (G-010)."""
    from codegraph.index_maintenance import (
        check_index_consistency as _check_index_consistency_impl,
    )

    return _check_index_consistency_impl(project_root)


# ═══════════════════════════════════════════════════════════════════════
# G-011 — Index query interface (IndexStore)
# ═══════════════════════════════════════════════════════════════════════


class IndexStore:
    """High-level query interface for graph indexes (G-011).

    Isolates other modules from SQLite details.
    """

    def __init__(self, project_root: Path) -> None:
        self._root = project_root
        self._db_path = _index_dir(project_root) / "codegraph.db"
        self._conn: Optional[sqlite3.Connection] = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            if not self._db_path.exists():
                raise FileNotFoundError(
                    f"Index not found at {self._db_path}. "
                    "Run 'codegraph build' or 'codegraph index rebuild'."
                )
            self._conn = _connect(self._db_path, readonly=True)
        return self._conn

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "IndexStore":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ── G-002 node queries ────────────────────────────────────────────

    def get_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        """O(1) node lookup by ID (G-002)."""
        row = self._get_conn().execute(
            "SELECT * FROM nodes WHERE id = ?", (node_id,)
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    def get_nodes_by_file(self, file_path: str) -> List[Dict[str, Any]]:
        """Return all nodes in a file (G-002)."""
        rows = self._get_conn().execute(
            "SELECT * FROM nodes WHERE file = ?", (file_path,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_node_ids(self) -> List[str]:
        """Return all indexed node IDs (G-011)."""
        rows = self._get_conn().execute("SELECT id FROM nodes ORDER BY id").fetchall()
        return [r[0] for r in rows]

    # ── G-003 callers queries ─────────────────────────────────────────

    def get_callers(self, node_id: str) -> List[str]:
        """O(1) reverse call graph lookup (G-003)."""
        rows = self._get_conn().execute(
            "SELECT caller_id FROM callers WHERE node_id = ?", (node_id,)
        ).fetchall()
        return [r[0] for r in rows]

    # ── G-004 callees queries ─────────────────────────────────────────

    def get_callees(self, node_id: str) -> List[str]:
        """O(1) forward call graph lookup (G-004)."""
        rows = self._get_conn().execute(
            "SELECT callee_id FROM callees WHERE node_id = ?", (node_id,)
        ).fetchall()
        return [r[0] for r in rows]

    # ── G-005 layer queries ───────────────────────────────────────────

    def get_nodes_at_layer(self, layer: int) -> List[str]:
        """Return all node IDs at a given layer (G-005)."""
        rows = self._get_conn().execute(
            "SELECT node_id FROM layers WHERE layer = ?", (layer,)
        ).fetchall()
        return [r[0] for r in rows]

    # ── G-006 test queries ────────────────────────────────────────────

    def get_tests_for_node(self, node_id: str) -> List[str]:
        """Return test IDs that cover a node (G-006)."""
        rows = self._get_conn().execute(
            "SELECT test_id FROM tests WHERE node_id = ?", (node_id,)
        ).fetchall()
        return [r[0] for r in rows]

    def get_nodes_for_test(self, test_id: str) -> List[str]:
        """Return node IDs covered by a test (G-006)."""
        rows = self._get_conn().execute(
            "SELECT node_id FROM tests WHERE test_id = ?", (test_id,)
        ).fetchall()
        return [r[0] for r in rows]

    # ── G-019 arch layer queries ──────────────────────────────────────

    def get_nodes_by_arch_layer(self, arch_layer: str) -> List[str]:
        """Return node IDs with a specific arch_layer (G-019)."""
        rows = self._get_conn().execute(
            "SELECT id FROM nodes WHERE arch_layer = ?", (arch_layer,)
        ).fetchall()
        return [r[0] for r in rows]

    # ── G-021 dependency hash queries ─────────────────────────────────

    def get_dependency_hash(self, node_id: str) -> Optional[str]:
        """O(1) dependency hash lookup (G-021)."""
        row = self._get_conn().execute(
            "SELECT dependency_hash FROM dependency_hashes WHERE node_id = ?",
            (node_id,),
        ).fetchone()
        return row[0] if row else None

    def get_all_dependency_hashes(self) -> Dict[str, str]:
        """Bulk load all dependency hashes (G-021)."""
        rows = self._get_conn().execute(
            "SELECT node_id, dependency_hash FROM dependency_hashes"
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    # ── G-011 orphan detection ────────────────────────────────────────

    def get_orphans(self) -> List[str]:
        """Return node IDs with no incoming or outgoing edges (G-011)."""
        conn = self._get_conn()
        all_ids = {r[0] for r in conn.execute("SELECT id FROM nodes WHERE type != 'module'").fetchall()}
        connected = set()
        for r in conn.execute("SELECT DISTINCT node_id FROM callers").fetchall():
            connected.add(r[0])
        for r in conn.execute("SELECT DISTINCT caller_id FROM callers").fetchall():
            connected.add(r[0])
        for r in conn.execute("SELECT DISTINCT node_id FROM callees").fetchall():
            connected.add(r[0])
        for r in conn.execute("SELECT DISTINCT callee_id FROM callees").fetchall():
            connected.add(r[0])
        return sorted(all_ids - connected)

    # ── G-012 node search ─────────────────────────────────────────────

    def search_nodes(self, pattern: str, limit: int = 100) -> List[str]:
        """Search nodes by pattern — supports exact, prefix, and glob (G-012)."""
        # Convert glob to SQL LIKE
        sql_pattern = pattern.replace("*", "%").replace("?", "_")
        if "%" not in sql_pattern and "_" not in sql_pattern:
            sql_pattern = f"%{sql_pattern}%"
        rows = self._get_conn().execute(
            "SELECT id FROM nodes WHERE id LIKE ? ORDER BY id LIMIT ?",
            (sql_pattern, limit),
        ).fetchall()
        return [r[0] for r in rows]

    # ── G-013 recursive dependency query ──────────────────────────────

    def get_dependencies_recursive(
        self,
        node_id: str,
        max_depth: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> Tuple[List[str], bool]:
        """BFS through callees for transitive dependencies (G-013).

        If ``limit`` is given, traversal stops as soon as that many dependency
        nodes have been discovered, so callers can bound expensive queries on
        large graphs. Returns ``(nodes, truncated)`` where ``truncated`` is
        ``True`` when the limit cut the traversal short.
        """
        visited: Set[str] = set()
        queue: deque[Tuple[str, int]] = deque([(node_id, 0)])
        truncated = False

        while queue:
            current, depth = queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            if limit is not None and len(visited) - 1 >= limit:
                # Enough dependency nodes found. Only mark truncated if more
                # nodes remain undiscovered in the queue.
                truncated = len(queue) > 0
                break
            if max_depth is not None and depth >= max_depth:
                continue
            for callee in self.get_callees(current):
                if callee not in visited:
                    queue.append((callee, depth + 1))

        visited.discard(node_id)
        return sorted(visited), truncated

    # ── G-014 shortest path ───────────────────────────────────────────

    def shortest_path(
        self,
        source: str,
        target: str,
        max_depth: int = 50,
    ) -> List[str]:
        """BFS shortest path between two nodes (G-014)."""
        if source == target:
            return [source]

        visited: Set[str] = {source}
        queue: deque[Tuple[str, List[str]]] = deque([(source, [source])])

        while queue:
            current, path = queue.popleft()
            if len(path) > max_depth:
                continue
            for callee in self.get_callees(current):
                if callee == target:
                    return path + [callee]
                if callee not in visited:
                    visited.add(callee)
                    queue.append((callee, path + [callee]))

        return []


# ═══════════════════════════════════════════════════════════════════════
# G-018 — Index statistics
# ═══════════════════════════════════════════════════════════════════════


def index_statistics(project_root: Path) -> IndexStats:
    """Report index size and health (G-018)."""
    return _index_statistics_impl(project_root)


# ═══════════════════════════════════════════════════════════════════════
# G-020 — Index export for debugging
# ═══════════════════════════════════════════════════════════════════════


def export_index(
    project_root: Path,
    table_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Export index contents as JSON for debugging (G-020)."""
    return _export_index_impl(project_root, table_name)
