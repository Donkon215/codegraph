"""Query system performance benchmarks (O-025).

Run with: python benchmarks/benchmark_query.py
"""

from __future__ import annotations

import sqlite3
import tempfile
import time
from pathlib import Path


def _build_index(db_path: Path, n_nodes: int) -> None:
    """Build a synthetic index for query benchmarking."""
    import random

    random.seed(99)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")

    conn.execute(
        "CREATE TABLE nodes (id TEXT PRIMARY KEY, file TEXT, type TEXT, "
        "line INTEGER, body_hash TEXT, layer INTEGER, arch_layer TEXT, "
        "dependency_hash TEXT)"
    )
    conn.execute(
        "CREATE TABLE callers (node_id TEXT, caller_id TEXT, "
        "edge_type TEXT, confidence TEXT)"
    )
    conn.execute(
        "CREATE TABLE callees (node_id TEXT, callee_id TEXT, "
        "edge_type TEXT, confidence TEXT)"
    )
    conn.execute("CREATE INDEX idx_callers_node ON callers(node_id)")
    conn.execute("CREATE INDEX idx_callees_node ON callees(node_id)")

    types = ["function", "method", "class", "module"]
    nodes = [
        (f"pkg/mod{i // 50}.py::item_{i}", f"pkg/mod{i // 50}.py",
         types[i % 4], i, f"h{i:06x}", i % 6, "", "")
        for i in range(n_nodes)
    ]
    conn.executemany("INSERT INTO nodes VALUES (?, ?, ?, ?, ?, ?, ?, ?)", nodes)

    edges = []
    for _ in range(n_nodes * 3):
        s = random.randint(0, n_nodes - 1)
        t = random.randint(0, n_nodes - 1)
        edges.append((
            f"pkg/mod{t // 50}.py::item_{t}",
            f"pkg/mod{s // 50}.py::item_{s}",
            "call", "static",
        ))
    conn.executemany("INSERT INTO callers VALUES (?, ?, ?, ?)", edges)
    conn.executemany(
        "INSERT INTO callees VALUES (?, ?, ?, ?)",
        [(e[1], e[0], e[2], e[3]) for e in edges],
    )
    conn.commit()
    conn.close()


def bench_prefix_search(db_path: Path, iterations: int = 200) -> float:
    conn = sqlite3.connect(str(db_path))
    t0 = time.perf_counter()
    for i in range(iterations):
        conn.execute(
            "SELECT id FROM nodes WHERE id LIKE ?",
            (f"pkg/mod{i % 20}.py%",),
        ).fetchall()
    elapsed = time.perf_counter() - t0
    conn.close()
    return elapsed / iterations * 1000


def bench_type_filter(db_path: Path, iterations: int = 200) -> float:
    conn = sqlite3.connect(str(db_path))
    t0 = time.perf_counter()
    for _ in range(iterations):
        conn.execute(
            "SELECT id FROM nodes WHERE type = ?", ("function",)
        ).fetchall()
    elapsed = time.perf_counter() - t0
    conn.close()
    return elapsed / iterations * 1000


def bench_callers_join(db_path: Path, iterations: int = 200) -> float:
    conn = sqlite3.connect(str(db_path))
    t0 = time.perf_counter()
    for i in range(iterations):
        conn.execute(
            "SELECT c.caller_id, n.file FROM callers c "
            "JOIN nodes n ON n.id = c.caller_id WHERE c.node_id = ?",
            (f"pkg/mod{i % 20}.py::item_{i % 1000}",),
        ).fetchall()
    elapsed = time.perf_counter() - t0
    conn.close()
    return elapsed / iterations * 1000


def main() -> None:
    for n_nodes, label in [
        (1_000, "1k nodes"),
        (10_000, "10k nodes"),
        (50_000, "50k nodes"),
    ]:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "query_bench.db"
            _build_index(db, n_nodes)
            print(f"\n--- {label} ---")

            iters = min(200, n_nodes)
            prefix_ms = bench_prefix_search(db, iters)
            type_ms = bench_type_filter(db, iters)
            join_ms = bench_callers_join(db, iters)

            print(f"  Prefix search: {prefix_ms:.3f} ms/query")
            print(f"  Type filter:   {type_ms:.3f} ms/query")
            print(f"  Callers join:  {join_ms:.3f} ms/query")

            if max(prefix_ms, type_ms, join_ms) < 10.0:
                print("  ✓ All within target")
            else:
                print("  ⚠ Some queries exceed 10 ms target")


if __name__ == "__main__":
    main()
