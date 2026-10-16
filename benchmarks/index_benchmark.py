"""Synthetic index and end-to-end CodeGraph scaling benchmarks (G-015).

Run with: python benchmarks/index_benchmark.py
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sqlite3
import subprocess
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FUNCTIONS_PER_FILE = 100


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
            print(f"  Index fixture setup: {build_seconds:.2f}s")
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
                "index_setup_seconds": round(build_seconds, 6),
                "peak_python_bytes": peak_bytes,
                "index_bytes": db_bytes,
                "node_lookup_ms": round(lookup_ms, 6),
                "callers_query_ms": round(callers_ms, 6),
                "delta_insert_delete_ms_per_edge": round(delta_ms, 6),
            })
    return reports


def _write_synthetic_repository(project: Path, function_count: int) -> Path:
    """Create a small real Python project with *function_count* functions."""
    source = project / "src"
    source.mkdir(parents=True)
    (project / "pyproject.toml").write_text(
        "[project]\nname = 'codegraph-scaling-fixture'\nversion = '0.0.0'\n",
        encoding="utf-8",
    )
    remaining = function_count
    file_index = 0
    first_file: Path | None = None
    while remaining:
        count = min(FUNCTIONS_PER_FILE, remaining)
        module = source / f"module_{file_index:05d}.py"
        if first_file is None:
            first_file = module
        lines: list[str] = []
        for local_index in range(count):
            name = f"function_{file_index:05d}_{local_index:03d}"
            if local_index + 1 < count:
                next_name = f"function_{file_index:05d}_{local_index + 1:03d}"
                lines.extend([f"def {name}():", f"    return {next_name}()", ""])
            else:
                lines.extend([f"def {name}():", "    return 1", ""])
        module.write_text("\n".join(lines), encoding="utf-8")
        remaining -= count
        file_index += 1
    assert first_file is not None
    return first_file


def _sample_peak_rss_bytes(pid: int) -> int | None:
    """Read a live child process's peak working set on Linux or Windows."""
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class ProcessMemoryCounters(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            psapi.GetProcessMemoryInfo.argtypes = [
                wintypes.HANDLE, ctypes.POINTER(ProcessMemoryCounters), wintypes.DWORD,
            ]
            psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
            handle = kernel32.OpenProcess(0x0400 | 0x0010, False, pid)
            if not handle:
                return None
            try:
                counters = ProcessMemoryCounters()
                counters.cb = ctypes.sizeof(counters)
                if psapi.GetProcessMemoryInfo(
                    handle, ctypes.byref(counters), counters.cb,
                ):
                    return int(counters.PeakWorkingSetSize)
            finally:
                kernel32.CloseHandle(handle)
        except (AttributeError, OSError, TypeError, ValueError):
            return None
        return None

    status = Path(f"/proc/{pid}/status")
    try:
        for line in status.read_text(encoding="ascii").splitlines():
            if line.startswith("VmHWM:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def _run_measured(command: list[str], cwd: Path, env: dict[str, str]) -> dict[str, object]:
    """Run a child command, recording wall time and sampled peak RSS."""
    peak_rss = 0
    with tempfile.TemporaryFile() as output:
        started = time.perf_counter()
        process = subprocess.Popen(
            command, cwd=cwd, env=env, stdout=output, stderr=subprocess.STDOUT,
        )
        while process.poll() is None:
            measured = _sample_peak_rss_bytes(process.pid)
            if measured is not None:
                peak_rss = max(peak_rss, measured)
            time.sleep(0.02)
        measured = _sample_peak_rss_bytes(process.pid)
        if measured is not None:
            peak_rss = max(peak_rss, measured)
        elapsed = time.perf_counter() - started
        if process.returncode:
            output.seek(max(0, output.tell() - 16_384))
            tail = output.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Command failed ({process.returncode}): {' '.join(command)}\n{tail}"
            )
    return {
        "seconds": round(elapsed, 6),
        "peak_rss_bytes": peak_rss or None,
    }


def _git(project: Path, *args: str, env: dict[str, str]) -> None:
    subprocess.run(["git", *args], cwd=project, env=env, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def benchmark_codegraph_project(function_count: int) -> dict[str, object]:
    """Measure real CodeGraph build and one-file incremental delta runs."""
    print(f"\n--- CodeGraph project ({function_count:,} functions) ---")
    with tempfile.TemporaryDirectory(prefix="codegraph_scale_") as directory:
        project = Path(directory)
        changed_file = _write_synthetic_repository(project, function_count)
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(filter(None, (
            str(REPOSITORY_ROOT), env.get("PYTHONPATH", ""),
        )))
        env["PYTHONIOENCODING"] = "utf-8"
        env.update({
            "GIT_AUTHOR_NAME": "CodeGraph benchmark",
            "GIT_AUTHOR_EMAIL": "benchmark@example.invalid",
            "GIT_COMMITTER_NAME": "CodeGraph benchmark",
            "GIT_COMMITTER_EMAIL": "benchmark@example.invalid",
        })
        _git(project, "init", "-q", env=env)
        _git(project, "add", "pyproject.toml", "src", env=env)
        _git(project, "commit", "-qm", "benchmark baseline", env=env)

        build = _run_measured(
            [sys.executable, "-m", "codegraph", "build"], project, env,
        )
        graph0_path = project / ".codegraph" / "graphs" / "graph0.json"
        graph0 = json.loads(graph0_path.read_text(encoding="utf-8"))
        node_count = len(graph0.get("nodes", []))

        with changed_file.open("a", encoding="utf-8") as source:
            source.write("\n\ndef benchmark_delta_added():\n    return 42\n")
        delta = _run_measured(
            [sys.executable, "-m", "codegraph", "delta"], project, env,
        )
        delta_graph = json.loads(graph0_path.read_text(encoding="utf-8"))
        measured_rss = [n for n in (build["peak_rss_bytes"], delta["peak_rss_bytes"])
                        if isinstance(n, int)]
        report: dict[str, object] = {
            "requested_functions": function_count,
            "graph_nodes_after_build": node_count,
            "graph_nodes_after_delta": len(delta_graph.get("nodes", [])),
            "build_seconds": build["seconds"],
            "delta_seconds": delta["seconds"],
            "build_peak_rss_bytes": build["peak_rss_bytes"],
            "delta_peak_rss_bytes": delta["peak_rss_bytes"],
            "peak_rss_bytes": max(measured_rss) if measured_rss else None,
        }
        print(f"  Graph nodes: {report['graph_nodes_after_build']:,} -> "
              f"{report['graph_nodes_after_delta']:,}")
        print(f"  CodeGraph build: {report['build_seconds']:.2f}s; "
              f"delta: {report['delta_seconds']:.2f}s")
        print(f"  Peak process RSS: {report['peak_rss_bytes']}")
        return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, help="Write comparable measurements as JSON.")
    parser.add_argument(
        "--quick", action="store_true",
        help="Run 1k/10k SQLite benchmarks and the 1k-function CodeGraph fixture.",
    )
    args = parser.parse_args()
    sizes = [(1_000, 5_000), (10_000, 50_000)]
    if not args.quick:
        sizes.append((100_000, 500_000))
    index_reports = run_benchmarks(sizes)
    codegraph_sizes = [1_000] if args.quick else [1_000, 10_000, 100_000]
    codegraph_reports = [benchmark_codegraph_project(n) for n in codegraph_sizes]
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps({
            "python": platform.python_version(),
            "platform": platform.platform(),
            "benchmarks": index_reports,
            "codegraph_end_to_end": codegraph_reports,
        }, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
