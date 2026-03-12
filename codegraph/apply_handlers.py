"""codegraph.apply_handlers — Repair action handlers and AST code helpers.

Extracted from apply.py to reduce god-module complexity (J-016, J-002..J-005).
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from dataclasses import dataclass

from codegraph.logging_config import get_logger
from codegraph.models.agent_response import RepairAction
from codegraph.models.graph0 import Graph0
from codegraph.models.graph1 import Graph1
from codegraph.models.workflow import Workflow
from codegraph.storage import atomic_write, resolve_path
from codegraph.utils.formatting import iso_now

logger = get_logger("apply_handlers")


# ═══════════════════════════════════════════════════════════════════════
# Data classes (shared with apply.py)
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class ActionResult:
    """Outcome of a single repair action (J-001)."""

    action: str
    node: str
    status: str  # "success" | "failed" | "skipped"
    message: str = ""
    file_modified: Optional[str] = None
    diff: str = ""


# ═══════════════════════════════════════════════════════════════════════
# J-016 — AST-Safe Code Insertion
# ═══════════════════════════════════════════════════════════════════════


def _parse_file_ast(file_path: Path) -> Optional[ast.Module]:
    """Parse a file and return its AST, or None on failure."""
    try:
        source = file_path.read_text(encoding="utf-8")
        return ast.parse(source, filename=str(file_path))
    except SyntaxError:
        return None


def _get_function_node(
    tree: ast.Module, func_name: str,
) -> Optional[ast.FunctionDef]:
    """Find a function/method definition by name in an AST."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == func_name:
                return node
    return None


def _get_class_method(
    tree: ast.Module, class_name: str, method_name: str,
) -> Optional[ast.FunctionDef]:
    """Find a method inside a class."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if item.name == method_name:
                        return item
    return None


def _find_function_in_ast(
    tree: ast.Module, node_id: str,
) -> Optional[ast.FunctionDef]:
    """Find a function by its codegraph node ID (file::QualName)."""
    parts = node_id.split("::")
    if len(parts) < 2:
        return None
    names = parts[1:]  # skip file part
    if len(names) == 1:
        return _get_function_node(tree, names[0])
    elif len(names) == 2:
        return _get_class_method(tree, names[0], names[1])
    return None


def _first_executable_line(func_node: ast.FunctionDef) -> int:
    """Return the line number for the first executable statement (J-016).

    Skips decorators, docstrings.  Returns 1-indexed line number.
    """
    for stmt in func_node.body:
        # Skip docstring
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, (ast.Constant, ast.Str)):
            continue
        return stmt.lineno
    # Function only has docstring (or is empty) — insert after last line of body
    if func_node.body:
        return func_node.body[-1].end_lineno + 1 if hasattr(func_node.body[-1], "end_lineno") else func_node.body[-1].lineno + 1
    return func_node.lineno + 1


def _detect_indentation(lines: List[str], func_node: ast.FunctionDef) -> str:
    """Detect indentation level for the function body (J-016)."""
    for stmt in func_node.body:
        line = lines[stmt.lineno - 1]
        stripped = line.lstrip()
        if stripped:
            return line[: len(line) - len(stripped)]
    # Fallback: use 4 spaces more than function def
    func_line = lines[func_node.lineno - 1]
    func_stripped = func_line.lstrip()
    base_indent = func_line[: len(func_line) - len(func_stripped)]
    return base_indent + "    "


def _has_import(lines: List[str], module_name: str) -> bool:
    """Check if a module is already imported."""
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if f"import {module_name}" in stripped or f"from {module_name}" in stripped:
            return True
    return False


def _find_import_block_end(lines: List[str]) -> int:
    """Find the line index after the last import statement (0-indexed)."""
    last_import = -1
    in_docstring = False

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Track module docstring
        if i == 0 and stripped.startswith('"""') or stripped.startswith("'''"):
            quote = stripped[:3]
            if stripped.count(quote) == 1:
                in_docstring = True
            continue
        if in_docstring:
            if '"""' in stripped or "'''" in stripped:
                in_docstring = False
            continue

        if stripped.startswith("import ") or stripped.startswith("from "):
            last_import = i
        elif stripped and not stripped.startswith("#") and last_import >= 0:
            # Non-import, non-blank, non-comment after imports → block ended
            break

    return last_import + 1 if last_import >= 0 else 0


def _insert_line(
    file_path: Path,
    line_number: int,
    text: str,
    *,
    dry_run: bool = False,
) -> str:
    """Insert a line at 1-indexed position.  Returns diff text."""
    lines = file_path.read_text(encoding="utf-8").splitlines(keepends=True)
    idx = max(0, line_number - 1)

    new_line = text if text.endswith("\n") else text + "\n"
    diff = f"+{line_number}: {text.strip()}"

    if not dry_run:
        lines.insert(idx, new_line)
        file_path.write_text("".join(lines), encoding="utf-8")

    return diff


def _remove_lines(
    file_path: Path,
    start: int,
    end: int,
    *,
    dry_run: bool = False,
) -> str:
    """Remove lines [start, end] (1-indexed inclusive).  Returns diff."""
    lines = file_path.read_text(encoding="utf-8").splitlines(keepends=True)
    removed = lines[start - 1 : end]
    diff_lines = [f"-{start + i}: {l.rstrip()}" for i, l in enumerate(removed)]
    diff = "\n".join(diff_lines)

    if not dry_run:
        del lines[start - 1 : end]
        file_path.write_text("".join(lines), encoding="utf-8")

    return diff


# ═══════════════════════════════════════════════════════════════════════
# J-012 — Already-Connected Detection
# ═══════════════════════════════════════════════════════════════════════


def _is_already_connected(
    source_id: str, target_id: str, workflow: Workflow,
) -> bool:
    """Check if an edge already exists in the workflow (J-012)."""
    for edge in workflow.get_edges_from(source_id):
        if edge.target == target_id:
            return True
    return False


# ═══════════════════════════════════════════════════════════════════════
# J-002 — connect_call Action Handler
# ═══════════════════════════════════════════════════════════════════════


def _maybe_insert_import(source_file, lines, target_module, target_func, dry_run):
    """Insert import statement if needed. Returns diff string or empty."""
    if target_module and not _has_import(lines, target_module.split(".")[-1]):
        import_line = f"from {target_module} import {target_func}\n"
        import_end = _find_import_block_end(lines)
        return _insert_line(source_file, import_end + 1, import_line, dry_run=dry_run)
    return ""


def handle_connect_call(
    action: RepairAction,
    project_root: Path,
    graph0: Graph0,
    workflow: Workflow,
    *,
    dry_run: bool = False,
) -> "ActionResult":
    """Insert a function call at the first executable statement (J-002)."""

    source_id = action.node
    target_id = action.target or ""

    # J-012 — Already connected check
    if _is_already_connected(source_id, target_id, workflow):
        return ActionResult(
            action="connect_call",
            node=source_id,
            status="skipped",
            message=f"Already connected: {source_id} → {target_id}",
        )

    # Find source file
    source_node = graph0.get_node(source_id)
    if not source_node:
        return ActionResult(
            action="connect_call", node=source_id, status="failed",
            message=f"Source node not found: {source_id}",
        )

    source_file = project_root / source_node.file
    if not source_file.exists():
        return ActionResult(
            action="connect_call", node=source_id, status="failed",
            message=f"Source file not found: {source_file}",
        )

    # Parse AST
    tree = _parse_file_ast(source_file)
    if tree is None:
        return ActionResult(
            action="connect_call", node=source_id, status="failed",
            message=f"Cannot parse {source_file}",
        )

    func_node = _find_function_in_ast(tree, source_id)
    if func_node is None:
        return ActionResult(
            action="connect_call", node=source_id, status="failed",
            message=f"Function not found in AST: {source_id}",
        )

    lines = source_file.read_text(encoding="utf-8").splitlines(keepends=True)

    # Determine target call expression
    target_parts = target_id.split("::")
    target_func = target_parts[-1] if target_parts else target_id
    target_module = target_parts[0].replace("/", ".").replace(".py", "") if len(target_parts) > 1 else ""

    # Check if import needed
    import_diff = _maybe_insert_import(
        source_file, lines, target_module, target_func, dry_run,
    )
    if import_diff and not dry_run:
            # Re-read lines after import insertion
            lines = source_file.read_text(encoding="utf-8").splitlines(keepends=True)
            tree = _parse_file_ast(source_file)
            if tree:
                func_node = _find_function_in_ast(tree, source_id)

    # Insert call
    if func_node is None:
        return ActionResult(
            action="connect_call", node=source_id, status="failed",
            message="Lost function node after import insertion",
        )

    indent = _detect_indentation(lines, func_node)
    insert_line = _first_executable_line(func_node)
    call_text = f"{indent}{target_func}()"
    call_diff = _insert_line(source_file, insert_line, call_text, dry_run=dry_run)

    diff = "\n".join(filter(None, [import_diff, call_diff]))

    return ActionResult(
        action="connect_call",
        node=source_id,
        status="success",
        message=f"Inserted call to {target_func}()",
        file_modified=str(source_node.file),
        diff=diff,
    )


# ═══════════════════════════════════════════════════════════════════════
# J-003 — add_import Action Handler
# ═══════════════════════════════════════════════════════════════════════


def handle_add_import(
    action: RepairAction,
    project_root: Path,
    graph0: Graph0,
    *,
    dry_run: bool = False,
) -> "ActionResult":
    """Append an import statement to the import block (J-003)."""

    node_id = action.node
    target = action.target or ""

    g0_node = graph0.get_node(node_id)
    if not g0_node:
        return ActionResult(
            action="add_import", node=node_id, status="failed",
            message=f"Node not found: {node_id}",
        )

    target_file = project_root / g0_node.file
    if not target_file.exists():
        return ActionResult(
            action="add_import", node=node_id, status="failed",
            message=f"File not found: {target_file}",
        )

    lines = target_file.read_text(encoding="utf-8").splitlines(keepends=True)

    # Check if already imported
    target_module = target.replace("/", ".").replace(".py", "")
    if _has_import(lines, target_module.split(".")[-1]):
        return ActionResult(
            action="add_import", node=node_id, status="skipped",
            message=f"Already imported: {target}",
        )

    # Determine import style from existing imports
    import_line = f"import {target_module}\n"
    # Check dominant style
    from_count = sum(1 for l in lines if l.strip().startswith("from "))
    bare_count = sum(1 for l in lines if l.strip().startswith("import ") and not l.strip().startswith("import "))
    if from_count > bare_count and "." in target_module:
        parts = target_module.rsplit(".", 1)
        import_line = f"from {parts[0]} import {parts[1]}\n"

    import_end = _find_import_block_end(lines)
    diff = _insert_line(target_file, import_end + 1, import_line, dry_run=dry_run)

    return ActionResult(
        action="add_import",
        node=node_id,
        status="success",
        message=f"Added import: {import_line.strip()}",
        file_modified=g0_node.file,
        diff=diff,
    )


# ═══════════════════════════════════════════════════════════════════════
# J-004 — remove_dead_code Action Handler
# J-014 — Dead Code Baseline Hash Store
# J-017 — Function Body Removal
# J-018 — Import Cleanup After Removal
# ═══════════════════════════════════════════════════════════════════════


def _load_baseline_hashes(project_root: Path) -> Dict[str, str]:
    """Load baseline body hashes (J-014)."""
    path = resolve_path(project_root, "baselines", "hashes.json")
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_baseline_hashes(project_root: Path, hashes: Dict[str, str]) -> Path:
    """Save baseline body hashes (J-014)."""
    path = resolve_path(project_root, "baselines", "hashes.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, hashes)
    return path


def _check_dead_code_signals(
    node_id: str,
    graph0: Graph0,
    graph1: Graph1,
    workflow: Workflow,
    index: Any = None,
    project_root: Optional[Path] = None,
) -> Tuple[int, List[str]]:
    """Check all 4 dead-code signals (J-004).  Returns (count, details)."""
    signals = 0
    details: List[str] = []

    # Signal 1: Orphan node — no callers and no callees
    callers = workflow.get_edges_to(node_id)
    callees = workflow.get_edges_from(node_id)
    if not callers and not callees:
        signals += 1
        details.append("orphan: no callers or callees")
    else:
        details.append(f"NOT orphan: {len(callers)} callers, {len(callees)} callees")

    # Signal 2: No test calls
    test_edges: List[Any] = []
    if index is not None:
        try:
            test_edges = index.get_tests_for_node(node_id)
        except Exception:
            pass
    if not test_edges:
        signals += 1
        details.append("no test coverage")
    else:
        details.append(f"NOT dead: {len(test_edges)} test(s) call this")

    # Signal 3: Body hash unchanged since baseline
    g0_node = graph0.get_node(node_id)
    if project_root and g0_node:
        baseline = _load_baseline_hashes(project_root)
        base_hash = baseline.get(node_id)
        if base_hash and base_hash == g0_node.body_hash:
            signals += 1
            details.append("body_hash unchanged since baseline")
        elif not base_hash:
            # No baseline → assume unchanged (conservative)
            signals += 1
            details.append("no baseline hash (assumed unchanged)")
        else:
            details.append(f"body_hash changed since baseline")
    else:
        signals += 1
        details.append("no baseline check available (assumed unchanged)")

    # Signal 4: No intent annotation
    g1_node = graph1.get_node(node_id) if graph1 else None
    if g1_node is None or not g1_node.intent:
        signals += 1
        details.append("no intent annotation")
    else:
        details.append(f"has intent: '{g1_node.intent[:50]}'")

    return signals, details


def _remove_function_from_file(
    file_path: Path,
    func_node: ast.FunctionDef,
    *,
    dry_run: bool = False,
) -> str:
    """Remove a function definition from a file (J-017)."""
    # Include decorators
    start_line = func_node.lineno
    if func_node.decorator_list:
        start_line = func_node.decorator_list[0].lineno

    end_line = func_node.end_lineno or func_node.lineno

    return _remove_lines(file_path, start_line, end_line, dry_run=dry_run)


def _cleanup_unused_imports(file_path: Path, *, dry_run: bool = False) -> str:
    """Remove imports that are no longer referenced (J-018)."""
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except SyntaxError:
        return ""

    # Collect all name references (not in import statements)
    used_names: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used_names.add(node.id)
        elif isinstance(node, ast.Attribute):
            # Attribute access: collect the root name
            root = node
            while isinstance(root, ast.Attribute):
                root = root.value
            if isinstance(root, ast.Name):
                used_names.add(root.id)

    # Find unused imports
    lines = source.splitlines(keepends=True)
    lines_to_remove: List[int] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name.split(".")[0]
                if name not in used_names:
                    lines_to_remove.append(node.lineno)
        elif isinstance(node, ast.ImportFrom):
            # Skip star imports
            if any(a.name == "*" for a in node.names):
                continue
            all_unused = all(
                (a.asname or a.name) not in used_names for a in node.names
            )
            if all_unused:
                lines_to_remove.append(node.lineno)

    if not lines_to_remove:
        return ""

    # Remove lines (reverse order to preserve indices)
    diff_parts = []
    for ln in sorted(set(lines_to_remove), reverse=True):
        if not dry_run:
            diff_parts.append(f"-{ln}: {lines[ln - 1].rstrip()}")
            del lines[ln - 1]
        else:
            diff_parts.append(f"-{ln}: {lines[ln - 1].rstrip()}")

    if not dry_run:
        file_path.write_text("".join(lines), encoding="utf-8")

    return "\n".join(reversed(diff_parts))


def handle_remove_dead_code(
    action: RepairAction,
    project_root: Path,
    graph0: Graph0,
    graph1: Graph1,
    workflow: Workflow,
    *,
    index: Any = None,
    dry_run: bool = False,
) -> "ActionResult":
    """Remove dead code with 4-signal verification (J-004)."""

    node_id = action.node

    # Check all 4 signals
    signals, details = _check_dead_code_signals(
        node_id, graph0, graph1, workflow, index, project_root,
    )

    if signals < 4:
        return ActionResult(
            action="remove_dead_code",
            node=node_id,
            status="failed",
            message=(
                f"Insufficient dead code signals: {signals}/4. "
                + "; ".join(details)
            ),
        )

    # Find and remove the function
    g0_node = graph0.get_node(node_id)
    if not g0_node:
        return ActionResult(
            action="remove_dead_code", node=node_id, status="failed",
            message=f"Node not found: {node_id}",
        )

    source_file = project_root / g0_node.file
    tree = _parse_file_ast(source_file)
    if tree is None:
        return ActionResult(
            action="remove_dead_code", node=node_id, status="failed",
            message=f"Cannot parse {source_file}",
        )

    func_node = _find_function_in_ast(tree, node_id)
    if func_node is None:
        return ActionResult(
            action="remove_dead_code", node=node_id, status="failed",
            message=f"Function not found in AST: {node_id}",
        )

    diff = _remove_function_from_file(source_file, func_node, dry_run=dry_run)

    # J-018 — Clean unused imports
    import_diff = ""
    if not dry_run:
        import_diff = _cleanup_unused_imports(source_file, dry_run=dry_run)

    full_diff = "\n".join(filter(None, [diff, import_diff]))

    return ActionResult(
        action="remove_dead_code",
        node=node_id,
        status="success",
        message=f"Removed dead code: {node_id}",
        file_modified=g0_node.file,
        diff=full_diff,
    )


# ═══════════════════════════════════════════════════════════════════════
# J-005 — flag_for_human_review Action Handler
# ═══════════════════════════════════════════════════════════════════════


def handle_flag_for_review(
    action: RepairAction,
    project_root: Path,
) -> "ActionResult":
    """Record a review flag without modifying code (J-005)."""

    review_dir = resolve_path(project_root, "reviews")
    review_dir.mkdir(parents=True, exist_ok=True)
    pending_path = review_dir / "pending.json"

    entries: List[Dict[str, Any]] = []
    if pending_path.exists():
        entries = json.loads(pending_path.read_text(encoding="utf-8"))

    entries.append({
        "node": action.node,
        "reason": action.reason,
        "timestamp": iso_now(),
        "target": action.target,
    })

    pending_path.write_text(
        json.dumps(entries, indent=2), encoding="utf-8",
    )

    return ActionResult(
        action="flag_for_human_review",
        node=action.node,
        status="success",
        message=f"Flagged for review: {action.reason}",
    )
