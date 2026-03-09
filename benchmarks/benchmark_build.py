"""Build pipeline performance benchmarks (O-025).

Run with: python benchmarks/benchmark_build.py
"""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path


def _generate_python_file(path: Path, n_functions: int = 10) -> None:
    """Generate a synthetic Python file with functions."""
    lines = []
    for i in range(n_functions):
        lines.append(f"def func_{i}(x):")
        if i > 0:
            lines.append(f"    return func_{i - 1}(x) + 1")
        else:
            lines.append("    return x")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _setup_project(root: Path, n_files: int, funcs_per_file: int) -> None:
    """Create a synthetic project with multiple files."""
    src = root / "src"
    src.mkdir(parents=True, exist_ok=True)
    (root / "codegraph.yaml").write_text(
        "project_name: bench\nversion: '1'\n", encoding="utf-8"
    )
    for i in range(n_files):
        _generate_python_file(src / f"mod_{i}.py", funcs_per_file)


def benchmark_extraction(root: Path) -> float:
    """Benchmark AST extraction phase."""
    from codegraph.extractor import extract_graph0

    t0 = time.perf_counter()
    g0 = extract_graph0(root)
    elapsed = time.perf_counter() - t0
    print(f"    Nodes extracted: {len(g0.nodes)}")
    return elapsed


def benchmark_graph0_serialisation(root: Path) -> float:
    """Benchmark graph0 JSON write/read."""
    from codegraph.extractor import extract_graph0

    g0 = extract_graph0(root)
    t0 = time.perf_counter()
    text = g0.to_json()
    json.loads(text)
    elapsed = time.perf_counter() - t0
    print(f"    JSON size: {len(text)} chars")
    return elapsed


def main() -> None:
    scenarios = [
        (5, 5, "tiny (25 funcs)"),
        (20, 10, "small (200 funcs)"),
        (50, 20, "medium (1000 funcs)"),
    ]
    for n_files, funcs_per_file, label in scenarios:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _setup_project(root, n_files, funcs_per_file)
            print(f"\n--- {label}: {n_files} files × {funcs_per_file} funcs ---")

            try:
                ext_time = benchmark_extraction(root)
                print(f"  Extraction: {ext_time:.3f}s")

                ser_time = benchmark_graph0_serialisation(root)
                print(f"  Serialisation: {ser_time:.3f}s")

                # Soft targets
                if ext_time < 5.0:
                    print("  ✓ Extraction within target")
                else:
                    print(f"  ⚠ Extraction slow: {ext_time:.1f}s")
            except Exception as exc:
                print(f"  ⚠ Skipped: {exc}")


if __name__ == "__main__":
    main()
