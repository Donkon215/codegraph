"""codegraph.apply — Repair action execution (apply system).

Group J: J-001 through J-020.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from codegraph.constants import CODEGRAPH_DIR, DELTA_FILE, RESPONSES_DIR
from codegraph.exceptions import (
    AlreadyConnectedError,
    CodegraphError,
    InsufficientDeadCodeSignalsError,
    VersionMismatchError,
)
from codegraph.logging_config import get_logger
from codegraph.models.agent_response import (
    AgentResponse,
    RepairAction,
    RepairActionType,
    WorkflowSuggestion,
)
from codegraph.models.graph0 import Graph0
from codegraph.models.graph1 import Graph1
from codegraph.models.workflow import Workflow
from codegraph.storage import atomic_write, resolve_path
from codegraph.utils.formatting import iso_now

logger = get_logger("apply")


# ═══════════════════════════════════════════════════════════════════════
# Data classes
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


@dataclass
class ApplyResult:
    """Aggregate outcome of applying a full agent response (J-001, J-015)."""

    actions: List[ActionResult] = field(default_factory=list)
    intents_applied: int = 0
    suggestions_added: int = 0
    files_modified: Set[str] = field(default_factory=set)
    dry_run: bool = False

    @property
    def succeeded(self) -> int:
        return sum(1 for a in self.actions if a.status == "success")

    @property
    def failed(self) -> int:
        return sum(1 for a in self.actions if a.status == "failed")

    @property
    def skipped(self) -> int:
        return sum(1 for a in self.actions if a.status == "skipped")


# ═══════════════════════════════════════════════════════════════════════
# J-010 — Apply Lock File
# ═══════════════════════════════════════════════════════════════════════


def _lock_path(project_root: Path) -> Path:
    return resolve_path(project_root, ".apply.lock")


def _acquire_lock(project_root: Path) -> None:
    lp = _lock_path(project_root)
    if lp.exists():
        try:
            info = json.loads(lp.read_text(encoding="utf-8"))
            pid = info.get("pid", 0)
            # Stale lock detection
            try:
                os.kill(pid, 0)
                raise CodegraphError(
                    f"Another apply is running (PID {pid}, started {info.get('started', '?')}). "
                    f"Delete {lp} if the process is dead."
                )
            except OSError:
                logger.warning("Removing stale lock (PID %d no longer running)", pid)
                lp.unlink(missing_ok=True)
        except json.JSONDecodeError:
            lp.unlink(missing_ok=True)

    lp.parent.mkdir(parents=True, exist_ok=True)
    lp.write_text(
        json.dumps({"pid": os.getpid(), "started": iso_now()}),
        encoding="utf-8",
    )


def _release_lock(project_root: Path) -> None:
    _lock_path(project_root).unlink(missing_ok=True)


# ═══════════════════════════════════════════════════════════════════════
# J-009 — Transaction / Backup Management
# ═══════════════════════════════════════════════════════════════════════


def _backup_dir(project_root: Path) -> Path:
    return resolve_path(project_root, "backups")


def _create_backups(files: Set[Path], project_root: Path) -> Dict[Path, Path]:
    """Backup files before modification.  Returns mapping original → backup."""
    bd = _backup_dir(project_root)
    bd.mkdir(parents=True, exist_ok=True)
    mapping: Dict[Path, Path] = {}
    for f in files:
        if f.exists():
            backup = bd / f.name
            shutil.copy2(f, backup)
            mapping[f] = backup
    return mapping


def _restore_backups(mapping: Dict[Path, Path]) -> None:
    for original, backup in mapping.items():
        if backup.exists():
            shutil.copy2(backup, original)
    _cleanup_backups(mapping)


def _cleanup_backups(mapping: Dict[Path, Path]) -> None:
    for backup in mapping.values():
        backup.unlink(missing_ok=True)


# ═══════════════════════════════════════════════════════════════════════
# J-019 — Undo Support
# ═══════════════════════════════════════════════════════════════════════


def _save_undo(
    project_root: Path,
    backups: Dict[Path, Path],
    result: ApplyResult,
) -> None:
    undo_dir = resolve_path(project_root, "undo")
    undo_dir.mkdir(parents=True, exist_ok=True)
    undo_info = {
        "timestamp": iso_now(),
        "files": {str(k): str(v) for k, v in backups.items()},
        "actions": len(result.actions),
    }
    (undo_dir / "last_apply.json").write_text(
        json.dumps(undo_info, indent=2), encoding="utf-8",
    )
    # Copy backups to undo dir
    for orig, bak in backups.items():
        if bak.exists():
            dest = undo_dir / bak.name
            shutil.copy2(bak, dest)


def undo_last_apply(project_root: Path) -> bool:
    """Undo the last apply operation (J-019).  Returns True if undone."""
    undo_dir = resolve_path(project_root, "undo")
    info_path = undo_dir / "last_apply.json"
    if not info_path.exists():
        logger.warning("No undo information found")
        return False

    info = json.loads(info_path.read_text(encoding="utf-8"))
    for orig_str, _bak_str in info.get("files", {}).items():
        orig = Path(orig_str)
        bak = undo_dir / Path(_bak_str).name
        if bak.exists():
            shutil.copy2(bak, orig)
            logger.info("Restored %s", orig)

    # Cleanup
    info_path.unlink(missing_ok=True)
    return True


# ═══════════════════════════════════════════════════════════════════════
# J-013 — Apply Conflict Detection
# ═══════════════════════════════════════════════════════════════════════


def _check_conflicts(
    files: Set[Path], project_root: Path,
) -> List[str]:
    """Check for uncommitted non-codegraph changes (J-013)."""
    conflicts: List[str] = []
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return []

        dirty_files: Set[str] = set()
        for line in result.stdout.strip().splitlines():
            if len(line) > 3:
                # Status codes: XY filename
                fname = line[3:].strip()
                dirty_files.add(fname)

        for f in files:
            try:
                rel = str(f.relative_to(project_root))
            except ValueError:
                continue
            rel_unix = rel.replace("\\", "/")
            if rel_unix in dirty_files:
                # Check if it's a codegraph-generated change
                pending = resolve_path(project_root, ".pending_changes")
                if pending.exists():
                    pending_data = json.loads(pending.read_text(encoding="utf-8"))
                    if rel_unix in pending_data.get("files", []):
                        continue
                conflicts.append(rel_unix)

    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return conflicts


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
    # node_id format: "path/to/file.py::ClassName::method" or "path/file.py::func"
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


def handle_connect_call(
    action: RepairAction,
    project_root: Path,
    graph0: Graph0,
    workflow: Workflow,
    *,
    dry_run: bool = False,
) -> ActionResult:
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
    import_diff = ""
    if target_module and not _has_import(lines, target_module.split(".")[-1]):
        import_line = f"from {target_module} import {target_func}\n"
        import_end = _find_import_block_end(lines)
        import_diff = _insert_line(source_file, import_end + 1, import_line, dry_run=dry_run)
        if not dry_run:
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
) -> ActionResult:
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
) -> ActionResult:
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
) -> ActionResult:
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


# ═══════════════════════════════════════════════════════════════════════
# J-006 — Workflow Suggestion Handling
# ═══════════════════════════════════════════════════════════════════════


def _apply_workflow_suggestions(
    suggestions: List[WorkflowSuggestion],
    project_root: Path,
) -> int:
    """Process workflow suggestions from agent response (J-006)."""
    from codegraph.suggest import promote_suggestion

    count = 0
    for s in suggestions:
        try:
            promote_suggestion(
                suggestion_type=s.type,
                source=s.source,
                target=s.target,
                reason=s.reason,
                project_root=project_root,
            )
            count += 1
        except Exception as exc:
            logger.warning("Failed to promote suggestion: %s", exc)

    return count


# ═══════════════════════════════════════════════════════════════════════
# J-008 — Code Formatter Integration (Black)
# ═══════════════════════════════════════════════════════════════════════


def _format_file(file_path: Path) -> bool:
    """Run code formatter on a file (J-008).  Returns True if successful."""
    try:
        result = subprocess.run(
            ["black", "--quiet", str(file_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode == 0
    except FileNotFoundError:
        logger.debug("black not installed — skipping formatting")
        return False
    except subprocess.TimeoutExpired:
        logger.warning("Formatter timed out on %s", file_path)
        return False


# ═══════════════════════════════════════════════════════════════════════
# J-007 — Graph_1 Update After Apply
# ═══════════════════════════════════════════════════════════════════════


def _update_graph1_after_apply(
    result: ApplyResult,
    project_root: Path,
    graph0: Graph0,
    graph1: Graph1,
) -> None:
    """Update Graph_1 body hashes and stale flags after apply (J-007)."""
    import hashlib

    for ar in result.actions:
        if ar.status != "success" or ar.file_modified is None:
            continue

        node_id = ar.node
        g0_node = graph0.get_node(node_id)
        g1_node = graph1.get_node(node_id)

        if ar.action == "remove_dead_code":
            # Remove from Graph_1
            graph1.remove_node(node_id)
            continue

        if g0_node and g1_node:
            # Re-hash the function body
            source_file = project_root / g0_node.file
            if source_file.exists():
                try:
                    new_source = source_file.read_text(encoding="utf-8")
                    new_hash = hashlib.sha256(
                        new_source.encode("utf-8")
                    ).hexdigest()[:5]
                    # If hash changed, mark intent as stale
                    if g1_node.intent_body_hash and g1_node.intent_body_hash != new_hash:
                        logger.info("Marking intent stale for %s (body changed)", node_id)
                except Exception:
                    pass


# ═══════════════════════════════════════════════════════════════════════
# J-020 — Apply Validation Post-Check
# ═══════════════════════════════════════════════════════════════════════


def _validate_modified_files(
    files: Set[str], project_root: Path,
) -> List[str]:
    """Re-parse modified files to ensure they're still valid Python (J-020)."""
    errors: List[str] = []
    for f in files:
        fp = project_root / f
        if fp.exists() and fp.suffix == ".py":
            try:
                source = fp.read_text(encoding="utf-8")
                ast.parse(source, filename=str(fp))
            except SyntaxError as exc:
                errors.append(f"{f}: {exc}")
    return errors


# ═══════════════════════════════════════════════════════════════════════
# J-015 — Apply Result Reporter
# ═══════════════════════════════════════════════════════════════════════


def format_apply_result(result: ApplyResult, *, as_json: bool = False) -> str:
    """Format apply results for display (J-015)."""
    if as_json:
        data = {
            "total": len(result.actions),
            "succeeded": result.succeeded,
            "failed": result.failed,
            "skipped": result.skipped,
            "intents_applied": result.intents_applied,
            "suggestions_added": result.suggestions_added,
            "files_modified": sorted(result.files_modified),
            "dry_run": result.dry_run,
            "actions": [
                {
                    "action": a.action,
                    "node": a.node,
                    "status": a.status,
                    "message": a.message,
                    "file": a.file_modified,
                }
                for a in result.actions
            ],
        }
        return json.dumps(data, indent=2)

    lines = []
    if result.dry_run:
        lines.append("=== DRY RUN (no files modified) ===\n")

    lines.append(f"Apply Result: {len(result.actions)} actions")
    lines.append(f"  Succeeded: {result.succeeded}")
    lines.append(f"  Failed:    {result.failed}")
    lines.append(f"  Skipped:   {result.skipped}")

    if result.intents_applied:
        lines.append(f"  Intents applied: {result.intents_applied}")
    if result.suggestions_added:
        lines.append(f"  Suggestions added: {result.suggestions_added}")
    if result.files_modified:
        lines.append(f"  Files modified: {len(result.files_modified)}")

    if result.actions:
        lines.append("\nDetails:")
        for a in result.actions:
            status_icon = {"success": "+", "failed": "!", "skipped": "-"}.get(
                a.status, "?"
            )
            lines.append(f"  [{status_icon}] {a.action} {a.node}: {a.message}")
            if a.diff and not result.dry_run:
                for dl in a.diff.splitlines():
                    lines.append(f"      {dl}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# J-001 — Apply Engine Core
# J-011 — Apply Dry Run Mode
# ═══════════════════════════════════════════════════════════════════════


def apply_response(
    response: AgentResponse,
    project_root: Path,
    graph0: Graph0,
    graph1: Graph1,
    workflow: Workflow,
    *,
    index: Any = None,
    dry_run: bool = False,
) -> ApplyResult:
    """Apply an agent response to the codebase (J-001).

    Dispatches each repair action to its handler.  Supports dry_run (J-011).
    Uses transaction management (J-009) and lock file (J-010).
    """
    from codegraph.annotator import apply_intents_batch, save_graph1
    from codegraph.storage import get_graph_version

    result = ApplyResult(dry_run=dry_run)

    # Validate version (J-001)
    current_version = get_graph_version(project_root)
    ok, msg = response.validate_version(current_version)
    if not ok:
        raise VersionMismatchError(current_version, response.graph_version)

    if not dry_run:
        _acquire_lock(project_root)

    try:
        # Collect files that will be modified for conflict check / backup
        files_to_modify: Set[Path] = set()
        for repair in response.repairs:
            action_type = RepairActionType(repair.action)
            if action_type.modifies_code():
                g0_node = graph0.get_node(repair.node)
                if g0_node:
                    files_to_modify.add(project_root / g0_node.file)

        # J-013 — Conflict detection
        if not dry_run and files_to_modify:
            conflicts = _check_conflicts(files_to_modify, project_root)
            if conflicts:
                logger.warning(
                    "Uncommitted changes in: %s", ", ".join(conflicts),
                )

        # J-009 — Create backups
        backups: Dict[Path, Path] = {}
        if not dry_run and files_to_modify:
            backups = _create_backups(files_to_modify, project_root)

        # Dispatch repair actions
        had_failure = False
        for repair in response.repairs:
            action_type = RepairActionType(repair.action)
            ar: ActionResult

            try:
                if action_type == RepairActionType.CONNECT_CALL:
                    ar = handle_connect_call(
                        repair, project_root, graph0, workflow, dry_run=dry_run,
                    )
                elif action_type == RepairActionType.ADD_IMPORT:
                    ar = handle_add_import(
                        repair, project_root, graph0, dry_run=dry_run,
                    )
                elif action_type == RepairActionType.REMOVE_DEAD_CODE:
                    ar = handle_remove_dead_code(
                        repair, project_root, graph0, graph1, workflow,
                        index=index, dry_run=dry_run,
                    )
                elif action_type == RepairActionType.FLAG_FOR_HUMAN_REVIEW:
                    ar = handle_flag_for_review(repair, project_root)
                else:
                    ar = ActionResult(
                        action=repair.action, node=repair.node,
                        status="skipped", message=f"Unknown action: {repair.action}",
                    )
            except Exception as exc:
                ar = ActionResult(
                    action=repair.action, node=repair.node,
                    status="failed", message=str(exc),
                )
                had_failure = True

            result.actions.append(ar)
            if ar.file_modified:
                result.files_modified.add(ar.file_modified)

        # J-008 — Format modified files
        if not dry_run:
            for f in result.files_modified:
                _format_file(project_root / f)

        # Apply intents from response
        if response.intents and not dry_run:
            try:
                batch_result = apply_intents_batch(
                    graph1, response.intents, "agent",
                    graph0=graph0,
                )
                result.intents_applied = batch_result.applied
            except Exception as exc:
                logger.warning("Failed to apply intents: %s", exc)

        # J-006 — Workflow suggestions
        if response.workflow_suggestions and not dry_run:
            result.suggestions_added = _apply_workflow_suggestions(
                response.workflow_suggestions, project_root,
            )

        # J-007 — Update Graph_1
        if not dry_run:
            _update_graph1_after_apply(result, project_root, graph0, graph1)
            save_graph1(graph1, project_root)

        # J-020 — Validate modified files
        if not dry_run and result.files_modified:
            validation_errors = _validate_modified_files(
                result.files_modified, project_root,
            )
            if validation_errors:
                logger.warning("Post-apply validation errors:")
                for err in validation_errors:
                    logger.warning("  %s", err)
                # Restore backups on validation failure
                if backups:
                    logger.warning("Restoring backups due to validation errors")
                    _restore_backups(backups)
                    for ar in result.actions:
                        if ar.status == "success":
                            ar.status = "failed"
                            ar.message += " (reverted due to validation error)"
                    return result

        # J-019 — Save undo info
        if not dry_run and backups:
            _save_undo(project_root, backups, result)
            _cleanup_backups(backups)

    finally:
        if not dry_run:
            _release_lock(project_root)

    return result


# ═══════════════════════════════════════════════════════════════════════
# Top-level CLI orchestrator
# ═══════════════════════════════════════════════════════════════════════


def run_apply(
    response_file: Path,
    project_root: Path,
    *,
    dry_run: bool = False,
) -> ApplyResult:
    """Load agent response and apply it (CLI entry point)."""
    from codegraph.extractor import load_graph0
    from codegraph.annotator import load_graph1
    from codegraph.workflow import load_workflow

    text = response_file.read_text(encoding="utf-8")
    response = AgentResponse.from_json(text)

    graph0 = load_graph0(project_root)
    graph1 = load_graph1(project_root)
    workflow = load_workflow(project_root)

    index = None
    try:
        from codegraph.index import IndexStore
        index = IndexStore(project_root)
    except FileNotFoundError:
        pass

    result = apply_response(
        response, project_root, graph0, graph1, workflow,
        index=index, dry_run=dry_run,
    )

    if index is not None:
        index.close()

    return result
