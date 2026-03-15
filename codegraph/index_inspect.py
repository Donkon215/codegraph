from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from codegraph.constants import INDEX_DIR
from codegraph.storage import resolve_path


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


@dataclass
class IndexStats:
    db_size_bytes: int = 0
    table_counts: Dict[str, int] = field(default_factory=dict)
    exists: bool = False

    def format(self) -> str:
        if not self.exists:
            return "Index: not built"
        lines = [f"Index: {self.db_size_bytes / 1024:.1f} KB"]
        for table, count in sorted(self.table_counts.items()):
            lines.append(f"  {table}: {count} rows")
        return "\n".join(lines)


def index_statistics(project_root: Path) -> IndexStats:
    db_path = _index_dir(project_root) / "codegraph.db"
    stats = IndexStats()

    if not db_path.exists():
        return stats

    stats.exists = True
    stats.db_size_bytes = db_path.stat().st_size

    try:
        conn = _connect(db_path, readonly=True)
        for table in ("nodes", "callers", "callees", "layers", "tests", "dependency_hashes"):
            try:
                row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                stats.table_counts[table] = row[0]
            except sqlite3.OperationalError:
                stats.table_counts[table] = -1
        conn.close()
    except Exception:
        pass

    return stats


def export_index(
    project_root: Path,
    table_name: Optional[str] = None,
) -> Dict[str, Any]:
    db_path = _index_dir(project_root) / "codegraph.db"
    if not db_path.exists():
        return {"error": "Index does not exist"}

    conn = _connect(db_path, readonly=True)
    result: Dict[str, Any] = {}

    tables = [table_name] if table_name else [
        "nodes", "callers", "callees", "layers", "tests", "dependency_hashes",
    ]

    for tbl in tables:
        try:
            rows = conn.execute(f"SELECT * FROM {tbl}").fetchall()
            cols = [desc[0] for desc in conn.execute(f"SELECT * FROM {tbl} LIMIT 0").description]
            result[tbl] = [dict(zip(cols, row)) for row in rows]
        except sqlite3.OperationalError:
            result[tbl] = {"error": f"Table '{tbl}' does not exist"}

    conn.close()
    return result
