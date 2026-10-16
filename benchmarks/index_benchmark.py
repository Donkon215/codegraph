"""Index performance benchmarks (G-015).

Run with: python benchmarks/index_benchmark.py
"""

from __future__ import annotations

import argparse
import json
import platform
import sqlite3
import tempfile
import time
import tracemalloc
from pathlib import Path


def _create_synthetic_index(db_path: Path, node_count: int, edge_count: int) -> None:
    """Create a synthetic index database for benchmarking."""
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
    conn.execute("CREATE INDEX idx_callers_node ON callers(node_id)")
    conn.execute(
        "CREATE TABLE callees (node_id TEXT, callee_id TEXT, "
        "edge_type TEXT, confidence TEXT)"
    )
    conn.execute("CREATE INDEX idx_callees_node ON callees(node_id)")

    # Insert nodes
    nodes = [(f"mod{i // 100}.py::func_{i}", f"mod{i // 100}.py", "function",
              i, f"hash{i}", 3, "", "") for i in range(node_count)]
    conn.executemany("INSERT INTO nodes VALUES (?, ?, ?, ?, ?, ?, ?, ?)", nodes)

    # Insert edges
    import random
    random.seed(42)
    edges = []
    for _ in range(edge_count):
        src = random.randint(0, node_count - 1)
        tgt = random.randint(0, node_count - 1)
        edges.append((
            f"mod{tgt // 100}.py::func_{tgt}",
            f"mod{src // 100}.py::func_{src}",
            "call", "static",
        ))
    conn.executemany("INSERT INTO callers VALUES (?, ?, ?, ?)", edges)
    conn.executemany(
        "INSERT INTO callees VALUES (?, ?, ?, ?)",
        [(e[1], e[0], e[2], e[3]) for e in edges],
    )

    conn.commit()
    conn.close()


def benchmark_lookup(db_path: Path, iterations: int = 1000) -> float:
    """Benchmark single-node lookup time."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")

    t0 = time.perf_counter()
    for i in range(iterations):
        conn.execute("SELECT * FROM nodes WHERE id = ?",
                     (f"mod{i % 100}.py::func_{i % 10000}",)).fetchone()
    elapsed = time.perf_counter() - t0
    conn.close()
    return elapsed / iterations * 1000  # ms per lookup


def benchmark_callers(db_path: Path, iterations: int = 1000) -> float:
    """Benchmark callers query time."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")

    t0 = time.perf_counter()
    for i in range(iterations):
        conn.execute("SELECT caller_id FROM callers WHERE node_id = ?",
                     (f"mod{i % 100}.py::func_{i % 10000}",)).fetchall()
    elapsed = time.perf_counter() - t0
    conn.close()
    return elapsed / iterations * 1000


def benchmark_delta(db_path: Path, iterations: int = 1000) -> float:
    """Measure indexed edge insert/delete batches in a single transaction each."""
    conn = sqlite3.connect(str(db_path))
    rows = [
        (f"delta_target_{i}", f"delta_source_{i}", "call", "static")
        for i in range(iterations)
    ]
    t0 = time.perf_counter()
    conn.executemany("INSERT INTO callers VALUES (?, ?, ?, ?)", rows)
    conn.executemany(
        "INSERT INTO callees VALUES (?, ?, ?, ?)",
        [(caller, callee, edge_type, confidence)
         for callee, caller, edge_type, confidence in rows],
    )
    conn.commit()
    conn.executemany("DELETE FROM callers WHERE node_id = ? AND caller_id = ?",
                     [(row[0], row[1]) for row in rows])
    conn.executemany("DELETE FROM callees WHERE node_id = ? AND callee_id = ?",
                     [(row[1], row[0]) for row in rows])
    conn.commit()
    elapsed = time.perf_counter() - t0
    conn.close()
    return elapsed / iterations * 1000


def run_benchmarks(sizes: list[tuple[int, int]]) -> list[dict[str, object]]:
    reports: list[dict[str, object]] = []
    for node_count, edge_count in sizes:
        label = f"{node_count:,} nodes"
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "bench.db"
            print(f"\n--- {label} ({edge_count} edges) ---")

            tracemalloc.start()
            t0 = time.perf_counter()
            _create_synthetic_index(db, node_count, edge_count)
            build_seconds = time.perf_counter() - t0
            _, peak_bytes = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            db_bytes = db.stat().st_size
            print(f"  Build: {build_seconds:.2f}s")
            print(f"  Peak Python memory: {peak_bytes / 1024 / 1024:.1f} MB")
            print(f"  DB size: {db_bytes / 1024 / 1024:.1f} MB")

            iters = min(1000, node_count)
            lookup_ms = benchmark_lookup(db, iters)
            callers_ms = benchmark_callers(db, iters)
            delta_ms = benchmark_delta(db, iters)
            print(f"  Node lookup: {lookup_ms:.3f} ms/query")
            print(f"  Callers query: {callers_ms:.3f} ms/query")
            print(f"  Delta insert/delete: {delta_ms:.3f} ms/edge")

            # Assert performance targets
            assert lookup_ms < 1.0, f"Lookup too slow: {lookup_ms:.3f}ms"
            assert callers_ms < 10.0, f"Callers too slow: {callers_ms:.3f}ms"
            print("  Performance targets met")
            reports.append({
                "nodes": node_count,
                "edges": edge_count,
                "build_seconds": round(build_seconds, 6),
                "peak_python_bytes": peak_bytes,
                "index_bytes": db_bytes,
                "node_lookup_ms": round(lookup_ms, 6),
                "callers_query_ms": round(callers_ms, 6),
                "delta_insert_delete_ms_per_edge": round(delta_ms, 6),
            })
    return reports


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, help="Write comparable measurements as JSON.")
    parser.add_argument("--quick", action="store_true", help="Run 1k/10k cases only.")
    args = parser.parse_args()
    sizes = [(1_000, 5_000), (10_000, 50_000)]
    if not args.quick:
        sizes.append((100_000, 500_000))
    reports = run_benchmarks(sizes)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps({
            "python": platform.python_version(),
            "platform": platform.platform(),
            "benchmarks": reports,
        }, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
