"""codegraph.archi_test — Architecture test generation and management.

Group M: M-001 through M-006, M-014, M-015, M-017, M-019.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from codegraph.constants import TEST_ARCHI_DIR
from codegraph.logging_config import get_logger
from codegraph.models.delta import DeltaResult
from codegraph.models.graph0 import Graph0, Graph0Node
from codegraph.models.workflow import Workflow
from codegraph.storage import resolve_path

logger = get_logger("archi_test")


# ═══════════════════════════════════════════════════════════════════════
# Data Structures
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class GeneratedTest:
    """A single generated architecture test (M-001)."""

    test_name: str
    target_node_id: str
    target_file: str
    target_function: str
    target_class: Optional[str] = None
    test_code: str = ""
    template: str = "standalone"
    needs_manual_setup: bool = False
    manual_setup_reason: str = ""


@dataclass
class ArchiTestResult:
    """Result of running architecture tests (M-003)."""

    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    failures: List[Dict[str, Any]] = field(default_factory=list)
    traces: List[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0


@dataclass
class CoverageReport:
    """Architecture test coverage report (M-014)."""

    total_edges: int = 0
    covered_by_project: int = 0
    covered_by_archi: int = 0
    uncovered: int = 0
    uncovered_edges: List[tuple] = field(default_factory=list)

    @property
    def coverage_pct(self) -> float:
        if self.total_edges == 0:
            return 100.0
        return ((self.covered_by_project + self.covered_by_archi)
                / self.total_edges * 100.0)


@dataclass
class CleanupResult:
    """Result of cleaning up stale archi tests (M-015)."""

    removed: List[str] = field(default_factory=list)
    kept: int = 0


# ═══════════════════════════════════════════════════════════════════════
# M-002 — Test Archi Directory Management
# ═══════════════════════════════════════════════════════════════════════


def _archi_dir(project_root: Path) -> Path:
    return resolve_path(project_root, TEST_ARCHI_DIR)


def ensure_archi_dir(project_root: Path) -> Path:
    """Create .codegraph/test_archi/ structure (M-002)."""
    d = _archi_dir(project_root)
    d.mkdir(parents=True, exist_ok=True)

    init = d / "__init__.py"
    if not init.exists():
        init.write_text("", encoding="utf-8")

    conftest = d / "conftest.py"
    if not conftest.exists():
        conftest.write_text(
            '"""Shared fixtures for architecture tests."""\n\n'
            'import sys\nfrom pathlib import Path\n\n'
            '# Ensure project root is on sys.path\n'
            'PROJECT_ROOT = Path(__file__).parent.parent.parent\n'
            'if str(PROJECT_ROOT) not in sys.path:\n'
            '    sys.path.insert(0, str(PROJECT_ROOT))\n',
            encoding="utf-8",
        )

    return d


def _test_file_name(node_id: str) -> str:
    """Generate test file name from node ID (M-002)."""
    # node_id: "file/path.py::ClassName::method_name" or "file/path.py::func"
    safe = node_id.replace("::", "_").replace("/", "_").replace(".", "_")
    safe = safe.replace(" ", "_").replace("-", "_")
    return f"test_archi_{safe}.py"


# ═══════════════════════════════════════════════════════════════════════
# M-006 — Architecture Test Template System
# M-017 — Argument Generator
# ═══════════════════════════════════════════════════════════════════════

# Type → default value mapping for minimal arguments (M-017)
_TYPE_DEFAULTS: Dict[str, str] = {
    "int": "0",
    "float": "0.0",
    "str": '""',
    "bool": "False",
    "list": "[]",
    "dict": "{}",
    "tuple": "()",
    "set": "set()",
    "bytes": 'b""',
    "None": "None",
    "Optional": "None",
}


def _generate_minimal_args(node: Graph0Node, project_root: Path) -> tuple:
    """Generate minimal arguments for a function call (M-017).

    Returns (args_str, needs_manual, reason).
    """
    file_path = project_root / node.file
    if not file_path.exists():
        return ("", False, "")

    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, SyntaxError):
        return ("", False, "")

    # Find the function definition
    func_name = node.id.split("::")[-1]
    parts = node.id.split("::")
    class_name = parts[-2] if len(parts) >= 3 and parts[-2][0].isupper() else None

    for ast_node in ast.walk(tree):
        if not isinstance(ast_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if ast_node.name != func_name:
            continue

        # Check if it's in the right class
        if class_name:
            # Just match function name — good enough for test generation
            pass

        args = ast_node.args
        arg_strs: List[str] = []
        needs_manual = False
        manual_reason = ""

        # Skip 'self' and 'cls'
        skip_first = class_name is not None
        all_args = args.args[1:] if skip_first else args.args

        # Calculate which args have no defaults
        n_defaults = len(args.defaults)
        n_no_default = len(all_args) - n_defaults

        for i, arg in enumerate(all_args):
            if i >= n_no_default:
                break  # Rest have defaults, skip

            annotation = None
            if arg.annotation:
                try:
                    annotation = ast.unparse(arg.annotation)
                except Exception:
                    pass

            if annotation and annotation in _TYPE_DEFAULTS:
                arg_strs.append(_TYPE_DEFAULTS[annotation])
            elif annotation and annotation.startswith("Optional"):
                arg_strs.append("None")
            elif annotation:
                needs_manual = True
                manual_reason = f"Complex type: {annotation} for param '{arg.arg}'"
                arg_strs.append("None  # TODO: provide value")
            else:
                arg_strs.append("None")

        return (", ".join(arg_strs), needs_manual, manual_reason)

    return ("", False, "")


def _generate_test_standalone(
    node: Graph0Node,
    module_import: str,
    func_name: str,
    args_str: str,
    is_async: bool = False,
) -> str:
    """Standalone function test template (M-006)."""
    if is_async:
        return textwrap.dedent(f"""\
            \"\"\"Architecture test for {node.id}.\"\"\"
            import asyncio
            from {module_import} import {func_name}

            def test_archi_{func_name}():
                asyncio.run({func_name}({args_str}))
        """)

    return textwrap.dedent(f"""\
        \"\"\"Architecture test for {node.id}.\"\"\"
        from {module_import} import {func_name}

        def test_archi_{func_name}():
            {func_name}({args_str})
    """)


def _generate_test_method(
    node: Graph0Node,
    module_import: str,
    class_name: str,
    method_name: str,
    args_str: str,
    is_async: bool = False,
) -> str:
    """Instance method test template (M-006)."""
    if is_async:
        return textwrap.dedent(f"""\
            \"\"\"Architecture test for {node.id}.\"\"\"
            import asyncio
            from {module_import} import {class_name}

            def test_archi_{class_name}_{method_name}():
                obj = {class_name}()
                asyncio.run(obj.{method_name}({args_str}))
        """)

    return textwrap.dedent(f"""\
        \"\"\"Architecture test for {node.id}.\"\"\"
        from {module_import} import {class_name}

        def test_archi_{class_name}_{method_name}():
            obj = {class_name}()
            obj.{method_name}({args_str})
    """)


def _generate_test_classmethod(
    node: Graph0Node,
    module_import: str,
    class_name: str,
    method_name: str,
    args_str: str,
) -> str:
    """Classmethod/staticmethod test template (M-006)."""
    return textwrap.dedent(f"""\
        \"\"\"Architecture test for {node.id}.\"\"\"
        from {module_import} import {class_name}

        def test_archi_{class_name}_{method_name}():
            {class_name}.{method_name}({args_str})
    """)


def _is_async_function(node: Graph0Node, project_root: Path) -> bool:
    """Check if a function is async."""
    try:
        source = (project_root / node.file).read_text(encoding="utf-8")
        tree = ast.parse(source)
        func_name = node.id.split("::")[-1]
        for n in ast.walk(tree):
            if isinstance(n, ast.AsyncFunctionDef) and n.name == func_name:
                return True
    except (OSError, SyntaxError):
        pass
    return False


def _node_to_import(node: Graph0Node) -> str:
    """Convert node file path to Python module import path."""
    module = node.file.replace("/", ".").replace("\\", ".")
    if module.endswith(".py"):
        module = module[:-3]
    return module


# ═══════════════════════════════════════════════════════════════════════
# M-001 — Architecture Test Generator
# ═══════════════════════════════════════════════════════════════════════


def generate_archi_tests(
    graph0: Graph0,
    workflow: Workflow,
    project_root: Path,
    *,
    untested_only: bool = True,
) -> List[GeneratedTest]:
    """Generate architecture test stubs for graph nodes (M-001)."""
    tests: List[GeneratedTest] = []

    # Determine which nodes have test edges
    tested_nodes: Set[str] = set()
    if untested_only:
        for edge in workflow.edges:
            if edge.edge_type == "test":
                tested_nodes.add(edge.target)

    for node in graph0.nodes:
        if node.type not in ("function", "method"):
            continue
        if untested_only and node.id in tested_nodes:
            continue
        # Skip test functions themselves
        if node.file.startswith("test") or "/test" in node.file:
            continue
        # Skip dunder methods
        func_name = node.id.split("::")[-1]
        if func_name.startswith("__") and func_name.endswith("__"):
            continue

        module_import = _node_to_import(node)
        parts = node.id.split("::")
        is_async = _is_async_function(node, project_root)

        args_str, needs_manual, manual_reason = _generate_minimal_args(node, project_root)

        gt = GeneratedTest(
            test_name=f"test_archi_{func_name}",
            target_node_id=node.id,
            target_file=node.file,
            target_function=func_name,
        )

        if len(parts) >= 3 and parts[-2][0].isupper():
            # Method on a class
            class_name = parts[-2]
            gt.target_class = class_name
            gt.template = "method"
            gt.test_code = _generate_test_method(
                node, module_import, class_name, func_name, args_str,
                is_async=is_async,
            )
        elif len(parts) >= 2:
            # Standalone function
            gt.template = "async" if is_async else "standalone"
            gt.test_code = _generate_test_standalone(
                node, module_import, func_name, args_str,
                is_async=is_async,
            )
        else:
            continue

        gt.needs_manual_setup = needs_manual
        gt.manual_setup_reason = manual_reason

        tests.append(gt)

    return tests


def write_archi_tests(
    tests: List[GeneratedTest],
    project_root: Path,
) -> int:
    """Write generated tests to disk (M-001, M-002)."""
    archi_dir = ensure_archi_dir(project_root)
    written = 0

    for gt in tests:
        test_file = archi_dir / _test_file_name(gt.target_node_id)
        if test_file.exists():
            continue  # Don't overwrite existing tests
        test_file.write_text(gt.test_code, encoding="utf-8")
        written += 1

    logger.info("Wrote %d architecture tests to %s", written, archi_dir)
    return written


# ═══════════════════════════════════════════════════════════════════════
# M-003 — Architecture Test Runner
# M-004 — Failure Handling
# ═══════════════════════════════════════════════════════════════════════


def run_archi_tests(
    project_root: Path,
    *,
    timeout: int = 300,
) -> ArchiTestResult:
    """Run architecture tests via pytest (M-003)."""
    archi_dir = _archi_dir(project_root)
    result = ArchiTestResult()

    if not archi_dir.exists() or not any(archi_dir.glob("test_archi_*.py")):
        logger.info("No architecture tests found")
        return result

    try:
        import time
        t0 = time.monotonic()

        proc = subprocess.run(
            [
                "pytest", str(archi_dir),
                "--tb=short",
                "--no-header",
                "-q",
                "--json-report",
                f"--json-report-file={archi_dir / 'last_run.json'}",
            ],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        result.elapsed_seconds = time.monotonic() - t0

        # Parse output for counts
        for line in proc.stdout.splitlines():
            if "passed" in line or "failed" in line:
                import re
                passed = re.search(r"(\d+) passed", line)
                failed = re.search(r"(\d+) failed", line)
                errors = re.search(r"(\d+) error", line)
                if passed:
                    result.passed = int(passed.group(1))
                if failed:
                    result.failed = int(failed.group(1))
                if errors:
                    result.errors = int(errors.group(1))

        # M-004 — Record failures
        if proc.returncode != 0 and proc.stdout:
            _record_failures(proc.stdout, archi_dir, result)

    except FileNotFoundError:
        logger.warning("pytest not found — cannot run architecture tests")
    except subprocess.TimeoutExpired:
        logger.warning("Architecture tests timed out after %ds", timeout)
        result.errors += 1

    return result


def _record_failures(
    output: str,
    archi_dir: Path,
    result: ArchiTestResult,
) -> None:
    """Parse and record test failures (M-004)."""
    results_path = archi_dir / "archi_test_results.json"

    failures: List[Dict[str, str]] = []
    current_test = ""

    for line in output.splitlines():
        if line.startswith("FAILED"):
            current_test = line.split("::")[1] if "::" in line else line
            failures.append({
                "test": current_test,
                "error": "",
            })
        elif failures and line.strip().startswith("E "):
            failures[-1]["error"] += line.strip() + "\n"

    result.failures = failures

    try:
        results_path.write_text(
            json.dumps(failures, indent=2), encoding="utf-8",
        )
    except OSError:
        pass


# ═══════════════════════════════════════════════════════════════════════
# M-005 — Architecture Test Regeneration
# ═══════════════════════════════════════════════════════════════════════


def regenerate_archi_tests(
    delta: DeltaResult,
    graph0: Graph0,
    workflow: Workflow,
    project_root: Path,
) -> int:
    """Regenerate archi tests for changed functions (M-005)."""
    archi_dir = _archi_dir(project_root)
    if not archi_dir.exists():
        return 0

    regenerated = 0

    # Remove tests for deleted nodes
    for node_id in delta.nodes_removed:
        test_file = archi_dir / _test_file_name(node_id)
        if test_file.exists():
            test_file.unlink()
            regenerated += 1
            logger.info("Removed archi test for deleted node: %s", node_id)

    # Regenerate tests for modified nodes
    modified_set = set(delta.nodes_modified)
    node_map = {n.id: n for n in graph0.nodes}

    for node_id in delta.nodes_modified:
        test_file = archi_dir / _test_file_name(node_id)
        if not test_file.exists():
            continue  # No existing test to regenerate

        node = node_map.get(node_id)
        if node is None:
            continue

        module_import = _node_to_import(node)
        parts = node_id.split("::")
        func_name = parts[-1]
        is_async = _is_async_function(node, project_root)
        args_str, _, _ = _generate_minimal_args(node, project_root)

        if len(parts) >= 3 and parts[-2][0].isupper():
            code = _generate_test_method(
                node, module_import, parts[-2], func_name, args_str,
                is_async=is_async,
            )
        else:
            code = _generate_test_standalone(
                node, module_import, func_name, args_str,
                is_async=is_async,
            )

        test_file.write_text(code, encoding="utf-8")
        regenerated += 1

    return regenerated


# ═══════════════════════════════════════════════════════════════════════
# M-014 — Architecture Test Coverage Report
# ═══════════════════════════════════════════════════════════════════════


def archi_test_coverage(
    workflow: Workflow,
    project_root: Path,
) -> CoverageReport:
    """Report edge coverage by project and archi tests (M-014)."""
    report = CoverageReport()
    archi_dir = _archi_dir(project_root)

    # All non-test edges
    production_edges = [
        e for e in workflow.edges
        if e.edge_type not in ("test",)
    ]
    report.total_edges = len(production_edges)

    # Test edges
    test_targets = set()
    archi_targets = set()

    for edge in workflow.edges:
        if edge.edge_type == "test":
            if edge.source_detail and "test_archi" in edge.source_detail:
                archi_targets.add(edge.target)
            else:
                test_targets.add(edge.target)

    for edge in production_edges:
        if edge.source in test_targets or edge.target in test_targets:
            report.covered_by_project += 1
        elif edge.source in archi_targets or edge.target in archi_targets:
            report.covered_by_archi += 1
        else:
            report.uncovered += 1
            report.uncovered_edges.append((edge.source, edge.target))

    return report


# ═══════════════════════════════════════════════════════════════════════
# M-015 — Archi Test Cleanup
# ═══════════════════════════════════════════════════════════════════════


def cleanup_archi_tests(
    graph0: Graph0,
    project_root: Path,
) -> CleanupResult:
    """Remove archi tests for functions that no longer exist (M-015)."""
    archi_dir = _archi_dir(project_root)
    result = CleanupResult()

    if not archi_dir.exists():
        return result

    existing_ids = {n.id for n in graph0.nodes}

    for test_file in archi_dir.glob("test_archi_*.py"):
        # Try to extract target node_id from file content
        try:
            content = test_file.read_text(encoding="utf-8")
            # Look for node ID in docstring
            match = None
            for line in content.splitlines()[:3]:
                if "Architecture test for " in line:
                    # Extract node_id after "for "
                    idx = line.index("Architecture test for ") + len("Architecture test for ")
                    node_id = line[idx:].rstrip('."\'')
                    match = node_id
                    break

            if match and match not in existing_ids:
                test_file.unlink()
                result.removed.append(str(test_file.name))
            else:
                result.kept += 1
        except (OSError, ValueError):
            result.kept += 1

    return result


# ═══════════════════════════════════════════════════════════════════════
# M-019 — Shared Fixture Generator
# ═══════════════════════════════════════════════════════════════════════


def generate_shared_fixtures(
    tests: List[GeneratedTest],
    project_root: Path,
) -> str:
    """Generate shared conftest.py for archi tests (M-019)."""
    archi_dir = ensure_archi_dir(project_root)

    # Detect common patterns
    needs_config = any("config" in t.test_code.lower() for t in tests)
    needs_db = any("database" in t.test_code.lower() or "db" in t.test_code.lower() for t in tests)

    lines = [
        '"""Shared fixtures for architecture tests (auto-generated)."""\n',
        "import sys",
        "from pathlib import Path",
        "",
        "import pytest",
        "",
        "PROJECT_ROOT = Path(__file__).parent.parent.parent",
        "if str(PROJECT_ROOT) not in sys.path:",
        "    sys.path.insert(0, str(PROJECT_ROOT))",
        "",
    ]

    if needs_config:
        lines += [
            "",
            "@pytest.fixture",
            "def project_config():",
            '    """Load project configuration."""',
            "    from codegraph.config import load_config",
            "    return load_config(PROJECT_ROOT)",
            "",
        ]

    conftest_content = "\n".join(lines) + "\n"
    conftest_path = archi_dir / "conftest.py"
    conftest_path.write_text(conftest_content, encoding="utf-8")
    return conftest_content


# ═══════════════════════════════════════════════════════════════════════
# CLI Entry Point
# ═══════════════════════════════════════════════════════════════════════


def format_archi_result(
    tests: List[GeneratedTest],
    *,
    as_json: bool = False,
) -> str:
    """Format generation results for CLI display."""
    if as_json:
        return json.dumps([{
            "test_name": t.test_name,
            "target": t.target_node_id,
            "template": t.template,
            "needs_manual": t.needs_manual_setup,
        } for t in tests], indent=2)

    if not tests:
        return "No architecture tests to generate."

    lines = [f"Generated {len(tests)} architecture tests:"]
    manual = [t for t in tests if t.needs_manual_setup]
    for t in tests[:20]:
        marker = " ⚠" if t.needs_manual_setup else ""
        lines.append(f"  {t.target_node_id} [{t.template}]{marker}")
    if len(tests) > 20:
        lines.append(f"  … and {len(tests) - 20} more")
    if manual:
        lines.append(f"\n{len(manual)} tests need manual setup")
    return "\n".join(lines)
