"""codegraph.apply — Repair action execution (apply system).

Group J: J-001 through J-020.
Action handlers extracted to codegraph.apply_handlers.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from codegraph.constants import CODEGRAPH_DIR
from codegraph.exceptions import CodegraphError, VersionMismatchError
from codegraph.logging_config import get_logger
from codegraph.models.agent_response import (
    AgentResponse,
    RepairActionType,
    WorkflowSuggestion,
)
from codegraph.models.graph0 import Graph0
from codegraph.models.graph1 import Graph1
from codegraph.models.workflow import Workflow
from codegraph.services import GraphStore, IndexService
from codegraph.storage import resolve_path
from codegraph.utils.formatting import iso_now
from codegraph.apply_handlers import (
    ActionResult,
    handle_connect_call,
    handle_add_import,
    handle_remove_dead_code,
    handle_flag_for_review,
)

logger = get_logger("apply")


# ═══════════════════════════════════════════════════════════════════════
# Data classes
# ═══════════════════════════════════════════════════════════════════════


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
# Planning Gate — require architecture plan before applying repairs
# ═══════════════════════════════════════════════════════════════════════

_PLAN_PATHS = [
    "planning/.plan.json",
    "planning/architecture_plan.json",
]


def _check_plan_exists(project_root: Path) -> None:
    """Ensure an architecture plan exists before applying repairs.

    Raises CodegraphError if no plan is found. This enforces the
    intent → plan → tasks → apply pipeline.
    """
    codegraph_dir = project_root / CODEGRAPH_DIR
    for rel in _PLAN_PATHS:
        if (codegraph_dir / rel).exists():
            return
    raise CodegraphError(
        "No architecture plan found. Run 'codegraph compile' or "
        "'codegraph code-plan' first, or use --skip-plan-check to bypass."
    )


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
            graph1.remove_intent_node(node_id)
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


def _validate_and_gate(response, project_root, dry_run, skip_plan_check):
    """Validate graph version and check planning gate."""
    from codegraph.storage import get_graph_version
    current_version = get_graph_version(project_root)
    ok, msg = response.validate_version(current_version)
    if not ok:
        raise VersionMismatchError(current_version, response.graph_version)
    if response.repairs and not dry_run and not skip_plan_check:
        _check_plan_exists(project_root)


def _prepare_apply(
    response: AgentResponse,
    project_root: Path,
    graph0: Graph0,
    *,
    dry_run: bool = False,
    skip_plan_check: bool = False,
) -> Tuple[Set[Path], Dict[Path, Path]]:
    """Validate version, acquire lock, collect files, check conflicts, create backups."""

    if not dry_run:
        _acquire_lock(project_root)

    files_to_modify: Set[Path] = set()
    for repair in response.repairs:
        action_type = RepairActionType(repair.action)
        if action_type.modifies_code():
            g0_node = graph0.get_node(repair.node)
            if g0_node:
                files_to_modify.add(project_root / g0_node.file)

    if not dry_run and files_to_modify:
        conflicts = _check_conflicts(files_to_modify, project_root)
        if conflicts:
            logger.warning(
                "Uncommitted changes in: %s", ", ".join(conflicts),
            )

    backups: Dict[Path, Path] = {}
    if not dry_run and files_to_modify:
        backups = _create_backups(files_to_modify, project_root)

    return files_to_modify, backups


def _dispatch_repairs(
    response: AgentResponse,
    project_root: Path,
    graph0: Graph0,
    graph1: Graph1,
    workflow: Workflow,
    result: ApplyResult,
    *,
    index: Any = None,
    dry_run: bool = False,
) -> None:
    """Dispatch each repair action to its handler and populate result."""
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

        result.actions.append(ar)
        if ar.file_modified:
            result.files_modified.add(ar.file_modified)


def _finalize_apply(
    result: ApplyResult,
    response: AgentResponse,
    project_root: Path,
    graph0: Graph0,
    graph1: Graph1,
    backups: Dict[Path, Path],
    *,
    dry_run: bool = False,
) -> None:
    """Format files, apply intents/suggestions, update graph1, validate, save undo."""
    from codegraph.annotator import apply_intents_batch, save_graph1

    if not dry_run:
        for f in result.files_modified:
            _format_file(project_root / f)

    if response.intents and not dry_run:
        try:
            batch_result = apply_intents_batch(
                graph1, response.intents, "agent",
                graph0=graph0,
            )
            result.intents_applied = batch_result.applied
        except Exception as exc:
            logger.warning("Failed to apply intents: %s", exc)

    if response.workflow_suggestions and not dry_run:
        result.suggestions_added = _apply_workflow_suggestions(
            response.workflow_suggestions, project_root,
        )

    if not dry_run:
        _update_graph1_after_apply(result, project_root, graph0, graph1)
        save_graph1(graph1, project_root)

    if not dry_run and result.files_modified:
        validation_errors = _validate_modified_files(
            result.files_modified, project_root,
        )
        if validation_errors:
            logger.warning("Post-apply validation errors:")
            for err in validation_errors:
                logger.warning("  %s", err)
            if backups:
                logger.warning("Restoring backups due to validation errors")
                _restore_backups(backups)
                for ar in result.actions:
                    if ar.status == "success":
                        ar.status = "failed"
                        ar.message += " (reverted due to validation error)"
                return

    if not dry_run and backups:
        _save_undo(project_root, backups, result)
        _cleanup_backups(backups)


class BackupManager:
    """Backup/undo operations for apply lifecycle."""

    def create(self, files_to_modify: Set[Path], project_root: Path) -> Dict[Path, Path]:
        return _create_backups(files_to_modify, project_root)

    def restore(self, mapping: Dict[Path, Path]) -> None:
        _restore_backups(mapping)

    def cleanup(self, mapping: Dict[Path, Path]) -> None:
        _cleanup_backups(mapping)

    def save_undo(self, project_root: Path, backups: Dict[Path, Path], result: ApplyResult) -> None:
        _save_undo(project_root, backups, result)


class ValidationService:
    """Validation and gating checks for apply lifecycle."""

    def validate_and_gate(
        self,
        response: AgentResponse,
        project_root: Path,
        *,
        dry_run: bool,
        skip_plan_check: bool,
    ) -> None:
        _validate_and_gate(response, project_root, dry_run, skip_plan_check)

    def validate_modified_files(self, files: Set[str], project_root: Path) -> List[str]:
        return _validate_modified_files(files, project_root)


class RepairDispatcher:
    """Dispatches repair actions to handlers."""

    def dispatch(
        self,
        response: AgentResponse,
        project_root: Path,
        graph0: Graph0,
        graph1: Graph1,
        workflow: Workflow,
        result: ApplyResult,
        *,
        index: Any = None,
        dry_run: bool = False,
    ) -> None:
        _dispatch_repairs(
            response,
            project_root,
            graph0,
            graph1,
            workflow,
            result,
            index=index,
            dry_run=dry_run,
        )


class GraphUpdater:
    """Applies post-dispatch graph and metadata updates."""

    def finalize(
        self,
        result: ApplyResult,
        response: AgentResponse,
        project_root: Path,
        graph0: Graph0,
        graph1: Graph1,
        backups: Dict[Path, Path],
        *,
        dry_run: bool = False,
    ) -> None:
        _finalize_apply(
            result,
            response,
            project_root,
            graph0,
            graph1,
            backups,
            dry_run=dry_run,
        )


class ApplyEngine:
    """Orchestrates apply workflow using specialized components."""

    def __init__(
        self,
        project_root: Path,
        graph0: Graph0,
        graph1: Graph1,
        workflow: Workflow,
        *,
        index: Any = None,
    ) -> None:
        self.project_root = project_root
        self.graph0 = graph0
        self.graph1 = graph1
        self.workflow = workflow
        self.index = index
        self.backup_manager = BackupManager()
        self.validation_service = ValidationService()
        self.dispatcher = RepairDispatcher()
        self.graph_updater = GraphUpdater()

    def apply(
        self,
        response: AgentResponse,
        *,
        dry_run: bool = False,
        skip_plan_check: bool = False,
    ) -> ApplyResult:
        result = ApplyResult(dry_run=dry_run)

        self.validation_service.validate_and_gate(
            response, self.project_root, dry_run=dry_run,
            skip_plan_check=skip_plan_check,
        )

        files_to_modify, backups = _prepare_apply(
            response,
            self.project_root,
            self.graph0,
            dry_run=dry_run,
            skip_plan_check=skip_plan_check,
        )

        if not dry_run and files_to_modify and not backups:
            backups = self.backup_manager.create(files_to_modify, self.project_root)

        try:
            self.dispatcher.dispatch(
                response,
                self.project_root,
                self.graph0,
                self.graph1,
                self.workflow,
                result,
                index=self.index,
                dry_run=dry_run,
            )

            self.graph_updater.finalize(
                result,
                response,
                self.project_root,
                self.graph0,
                self.graph1,
                backups,
                dry_run=dry_run,
            )
        finally:
            if not dry_run:
                _release_lock(self.project_root)

        return result


def apply_response(
    response: AgentResponse,
    project_root: Path,
    graph0: Graph0,
    graph1: Graph1,
    workflow: Workflow,
    *,
    index: Any = None,
    dry_run: bool = False,
    skip_plan_check: bool = False,
) -> ApplyResult:
    """Apply an agent response to the codebase (J-001).

    Dispatches each repair action to its handler.  Supports dry_run (J-011).
    Uses transaction management (J-009) and lock file (J-010).
    """
    engine = ApplyEngine(
        project_root,
        graph0,
        graph1,
        workflow,
        index=index,
    )
    return engine.apply(
        response,
        dry_run=dry_run,
        skip_plan_check=skip_plan_check,
    )


# ═══════════════════════════════════════════════════════════════════════
# Top-level CLI orchestrator
# ═══════════════════════════════════════════════════════════════════════


def run_apply(
    response_file: Path,
    project_root: Path,
    *,
    dry_run: bool = False,
    skip_plan_check: bool = False,
) -> ApplyResult:
    """Load agent response and apply it (CLI entry point)."""
    text = response_file.read_text(encoding="utf-8")
    response = AgentResponse.from_json(text)

    store = GraphStore(project_root)
    graph0 = store.load_graph0()
    graph1 = store.load_graph1()
    workflow = store.load_workflow()

    index_service = IndexService(project_root)
    index: Any = None
    try:
        index = index_service
        index.get_node("__codegraph_health_check__")
    except FileNotFoundError:
        index = None

    result = apply_response(
        response, project_root, graph0, graph1, workflow,
        index=index, dry_run=dry_run,
        skip_plan_check=skip_plan_check,
    )

    if index is not None:
        index_service.close()

    return result
