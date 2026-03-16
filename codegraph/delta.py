"""codegraph.delta — Incremental delta engine.

Group K: K-001 through K-023.
"""

from __future__ import annotations

import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from codegraph.constants import (
    CODEGRAPH_DIR,
    DELTA_FILE,
    GRAPHS_DIR,
    WORKFLOW_DIR,
)
from codegraph.logging_config import get_logger
from codegraph.models.delta import DeltaResult
from codegraph.models.graph0 import Graph0, Graph0Node
from codegraph.models.graph1 import Graph1
from codegraph.models.workflow import Workflow
from codegraph.storage import atomic_write, resolve_path
from codegraph.utils.formatting import iso_now

logger = get_logger("delta")


# ═══════════════════════════════════════════════════════════════════════
# K-002 — Git Diff Parser
# K-003 — Uncommitted Changes Detection
# K-014 — Delta Baseline Commit Tracking
# K-015 — File Rename Tracking
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class ChangedFiles:
    """Result of git diff analysis (K-002)."""

    added: List[str] = field(default_factory=list)
    modified: List[str] = field(default_factory=list)
    deleted: List[str] = field(default_factory=list)
    renamed: List[Tuple[str, str]] = field(default_factory=list)  # (old, new)
    includes_uncommitted: bool = False

    @property
    def all_changed(self) -> List[str]:
        """All files that need re-extraction (excludes deleted)."""
        files = self.added + self.modified + [new for _, new in self.renamed]
        return list(set(files))

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.modified or self.deleted or self.renamed)


def _get_last_build_commit(project_root: Path) -> Optional[str]:
    """Read the commit hash recorded at the last build/delta (K-014)."""
    meta_path = resolve_path(project_root, "metadata.json")
    if not meta_path.exists():
        return None
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        return data.get("last_build_commit")
    except (json.JSONDecodeError, OSError):
        return None


def _store_build_commit(project_root: Path, commit: str) -> None:
    """Store the current commit hash after a successful build/delta (K-014)."""
    meta_path = resolve_path(project_root, "metadata.json")
    meta_path.parent.mkdir(parents=True, exist_ok=True)

    data: Dict[str, Any] = {}
    if meta_path.exists():
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    data["last_build_commit"] = commit
    data["last_build_at"] = iso_now()
    meta_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _detect_uncommitted(project_root: Path) -> bool:
    """Check for uncommitted changes in the working tree (K-003)."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return False


def get_changed_files(
    project_root: Path,
    since_commit: Optional[str] = None,
) -> ChangedFiles:
    """Parse git diff to determine changed files (K-002, K-015)."""
    result = ChangedFiles()

    if since_commit is None:
        since_commit = _get_last_build_commit(project_root)

    # K-003 — Check for uncommitted changes
    if _detect_uncommitted(project_root):
        result.includes_uncommitted = True
        logger.warning("Processing uncommitted changes")

    if since_commit is None:
        # No previous commit — indicate full rebuild needed
        logger.info("No previous build commit — all files are 'changed'")
        return result

    # K-015 — Use -M for rename detection
    try:
        proc = subprocess.run(
            ["git", "diff", "--name-status", "-M", f"{since_commit}..HEAD"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode != 0:
            # Commit might not exist (rebase) — fall back
            logger.warning("git diff failed (commit %s may not exist): %s",
                           since_commit, proc.stderr.strip())
            return result

        for line in proc.stdout.strip().splitlines():
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            status = parts[0]
            if status == "A":
                result.added.append(parts[1])
            elif status == "M":
                result.modified.append(parts[1])
            elif status == "D":
                result.deleted.append(parts[1])
            elif status.startswith("R"):
                # Rename: old_path → new_path
                if len(parts) >= 3:
                    result.renamed.append((parts[1], parts[2]))

    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.warning("git not available: %s", exc)

    # Also include uncommitted changes (working tree)
    if result.includes_uncommitted:
        try:
            proc = subprocess.run(
                ["git", "diff", "--name-only"],
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=30,
            )
            if proc.returncode == 0:
                for f in proc.stdout.strip().splitlines():
                    f = f.strip()
                    if f and f not in result.modified and f not in result.added:
                        if (project_root / f).exists():
                            result.modified.append(f)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    # Filter to Python files that exist
    result.added = [f for f in result.added if f.endswith(".py") and (project_root / f).exists()]
    result.modified = [f for f in result.modified if f.endswith(".py") and (project_root / f).exists()]
    result.deleted = [f for f in result.deleted if f.endswith(".py")]
    result.renamed = [(o, n) for o, n in result.renamed
                      if n.endswith(".py") and (project_root / n).exists()]

    return result


# ═══════════════════════════════════════════════════════════════════════
# K-019 — Delta Trigger Detection
# ═══════════════════════════════════════════════════════════════════════


def needs_delta(project_root: Path) -> bool:
    """Quick check: have any files changed since the last build? (K-019)."""
    from codegraph.git_utils import get_current_commit

    since = _get_last_build_commit(project_root)
    if since is None:
        return True

    current = get_current_commit(project_root)
    if current and current != since:
        return True

    return _detect_uncommitted(project_root)


# ═══════════════════════════════════════════════════════════════════════
# K-004 — Incremental AST Re-Extraction
# K-006 — Body Hash Change Detection
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class LogicChange:
    """A node whose body_hash changed (K-006)."""

    node_id: str
    old_hash: str
    new_hash: str
    file: str


@dataclass
class Graph0Updates:
    """Result of incremental re-extraction (K-004)."""

    added_nodes: List[Graph0Node] = field(default_factory=list)
    removed_node_ids: List[str] = field(default_factory=list)
    modified_nodes: List[Graph0Node] = field(default_factory=list)
    logic_changes: List[LogicChange] = field(default_factory=list)
    call_sites: Dict[str, List[Any]] = field(default_factory=dict)
    imports: Dict[str, List[Any]] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)


def reextract_changed(
    changed: ChangedFiles,
    graph0: Graph0,
    project_root: Path,
    *,
    parallel: bool = False,
) -> Graph0Updates:
    """Re-extract AST only for changed files (K-004, K-006)."""
    from codegraph.extractor import extract_file

    updates = Graph0Updates()

    # Build map of old nodes by file
    old_nodes_by_file: Dict[str, List[Graph0Node]] = {}
    for node in graph0.nodes:
        old_nodes_by_file.setdefault(node.file, []).append(node)

    # Handle deleted files — mark all their nodes as removed
    for deleted_file in changed.deleted:
        for node in old_nodes_by_file.get(deleted_file, []):
            updates.removed_node_ids.append(node.id)

    # Handle renamed files — mark old nodes removed
    for old_path, new_path in changed.renamed:
        for node in old_nodes_by_file.get(old_path, []):
            updates.removed_node_ids.append(node.id)

    # Files to re-extract
    files_to_extract = changed.all_changed

    def _extract_one(rel_path: str) -> Optional[Any]:
        fp = project_root / rel_path
        if not fp.exists():
            return None
        try:
            return extract_file(fp, project_root)
        except Exception as exc:
            updates.warnings.append(f"{rel_path}: {exc}")
            return None

    # K-016 — Parallel extraction for many files
    results: Dict[str, Any] = {}
    if parallel and len(files_to_extract) > 10:
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(_extract_one, f): f for f in files_to_extract}
            for future in futures:
                f = futures[future]
                try:
                    results[f] = future.result()
                except Exception as exc:
                    updates.warnings.append(f"{f}: {exc}")
    else:
        for f in files_to_extract:
            results[f] = _extract_one(f)

    # Compare old vs new nodes
    old_node_index = {n.id: n for n in graph0.nodes}

    for rel_path, file_result in results.items():
        if file_result is None:
            continue

        # Collect call_sites and imports for workflow rebuild
        if file_result.call_sites:
            updates.call_sites.update(file_result.call_sites)
        if file_result.imports:
            updates.imports[rel_path] = file_result.imports

        # Remove old nodes for this file (they'll be replaced)
        for old_node in old_nodes_by_file.get(rel_path, []):
            if old_node.id not in updates.removed_node_ids:
                updates.removed_node_ids.append(old_node.id)

        # Add new nodes, detect logic changes
        for new_node in file_result.nodes:
            old_node = old_node_index.get(new_node.id)

            if old_node is None:
                updates.added_nodes.append(new_node)
            elif old_node.body_hash != new_node.body_hash:
                updates.modified_nodes.append(new_node)
                updates.logic_changes.append(LogicChange(
                    node_id=new_node.id,
                    old_hash=old_node.body_hash,
                    new_hash=new_node.body_hash,
                    file=new_node.file,
                ))
            else:
                # Unchanged — re-add (still part of the file)
                updates.modified_nodes.append(new_node)

    return updates


# ═══════════════════════════════════════════════════════════════════════
# K-005 — Graph_0 Merge
# ═══════════════════════════════════════════════════════════════════════


def merge_graph0(current: Graph0, updates: Graph0Updates) -> Graph0:
    """Merge delta node updates into existing Graph_0 (K-005)."""
    # Build new node list: keep existing nodes not in removed set, add new/modified
    removed_set = set(updates.removed_node_ids)
    kept_nodes = [n for n in current.nodes if n.id not in removed_set]

    # Add new and modified nodes
    existing_ids = {n.id for n in kept_nodes}
    for node in updates.added_nodes + updates.modified_nodes:
        if node.id not in existing_ids:
            kept_nodes.append(node)
            existing_ids.add(node.id)

    return Graph0(
        graph_version=current.graph_version,
        format_version=current.format_version,
        extracted_at=iso_now(),
        source_files=current.source_files,
        nodes=kept_nodes,
    )


# ═══════════════════════════════════════════════════════════════════════
# K-018 — Graph_0 Snapshot Comparison
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class Graph0Diff:
    """Detailed diff between two Graph_0 snapshots (K-018)."""

    added: List[str] = field(default_factory=list)
    removed: List[str] = field(default_factory=list)
    modified: List[str] = field(default_factory=list)
    unchanged: int = 0


def diff_graph0(old: Graph0, new: Graph0) -> Graph0Diff:
    """Compare two Graph_0 snapshots (K-018)."""
    old_map = {n.id: n for n in old.nodes}
    new_map = {n.id: n for n in new.nodes}
    result = Graph0Diff()

    for nid, node in new_map.items():
        if nid not in old_map:
            result.added.append(nid)
        elif old_map[nid].body_hash != node.body_hash:
            result.modified.append(nid)
        else:
            result.unchanged += 1

    for nid in old_map:
        if nid not in new_map:
            result.removed.append(nid)

    return result


# ═══════════════════════════════════════════════════════════════════════
# K-007 — Stale Intent Flagging
# ═══════════════════════════════════════════════════════════════════════


def flag_stale_intents(
    logic_changes: List[LogicChange],
    graph1: Graph1,
) -> List[str]:
    """Mark intents as stale when body_hash changed (K-007)."""
    stale_ids: List[str] = []
    for change in logic_changes:
        g1_node = graph1.get_node(change.node_id)
        if g1_node and g1_node.intent:
            # Update the intent_body_hash to reflect the current state
            # The intent is now stale because code changed
            stale_ids.append(change.node_id)
            logger.info("Intent stale: %s (hash %s → %s)",
                        change.node_id, change.old_hash, change.new_hash)
    return stale_ids


# ═══════════════════════════════════════════════════════════════════════
# K-008 — Workflow Edge Recomputation
# ═══════════════════════════════════════════════════════════════════════


def recompute_edges(
    changed: ChangedFiles,
    graph0: Graph0,
    workflow: Workflow,
    call_sites: Dict[str, List[Any]],
    imports: Dict[str, List[Any]],
) -> Tuple[Workflow, List[Tuple[str, str]], List[Tuple[str, str]]]:
    """Recompute workflow edges for changed files (K-008).

    Returns (new_workflow, edges_added, edges_removed).
    """
    from codegraph.workflow import update_workflow_incremental, diff_workflows

    old_workflow = workflow
    changed_files = changed.all_changed + changed.deleted

    new_workflow = update_workflow_incremental(
        workflow, changed_files, graph0, call_sites, imports,
    )

    # Compute edge diff
    wf_diff = diff_workflows(old_workflow, new_workflow)
    edges_added = [(e.source, e.target) for e in wf_diff.added]
    edges_removed = [(e.source, e.target) for e in wf_diff.removed]

    return new_workflow, edges_added, edges_removed


# ═══════════════════════════════════════════════════════════════════════
# K-009 — Index Incremental Update
# ═══════════════════════════════════════════════════════════════════════


def update_index(
    updates: Graph0Updates,
    graph0: Graph0,
    graph1: Graph1,
    workflow: Workflow,
    project_root: Path,
) -> int:
    """Incrementally update the graph index (K-009)."""
    from codegraph.index import update_index_delta

    changed_ids = (
        [n.id for n in updates.added_nodes]
        + [n.id for n in updates.modified_nodes]
        + updates.removed_node_ids
    )

    if not changed_ids:
        return 0

    return update_index_delta(changed_ids, graph0, graph1, workflow, project_root)


# ═══════════════════════════════════════════════════════════════════════
# K-010 — Graph Version Increment
# ═══════════════════════════════════════════════════════════════════════


def _increment_version(project_root: Path) -> int:
    """Increment graph_version after successful delta (K-010)."""
    from codegraph.storage import increment_graph_version
    return increment_graph_version(project_root)


# ═══════════════════════════════════════════════════════════════════════
# K-011 — Delta Result Output
# K-012 — Delta History Log
# ═══════════════════════════════════════════════════════════════════════


def _delta_dir(project_root: Path) -> Path:
    return resolve_path(project_root, "delta")


def write_delta_result(result: DeltaResult, project_root: Path) -> Path:
    """Write delta.json atomically (K-011)."""
    dest = _delta_dir(project_root) / DELTA_FILE
    dest.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(result.to_json())
    atomic_write(dest, data)
    logger.info("Delta result → %s", dest)
    return dest


_MAX_HISTORY = 100


def _append_history(result: DeltaResult, project_root: Path) -> None:
    """Append delta summary to history log (K-012)."""
    hist_path = _delta_dir(project_root) / "history.json"
    hist_path.parent.mkdir(parents=True, exist_ok=True)

    entries: List[Dict[str, Any]] = []
    if hist_path.exists():
        try:
            entries = json.loads(hist_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    entries.append({
        "version": result.current_graph_version,
        "timestamp": result.computed_at,
        "files_changed": len(result.files_changed),
        "nodes_added": len(result.nodes_added),
        "nodes_removed": len(result.nodes_removed),
        "nodes_modified": len(result.nodes_modified),
        "edges_added": len(result.workflow_edges_added),
        "edges_removed": len(result.workflow_edges_removed),
        "stale_intents": len(result.stale_intents),
    })

    # Enforce size limit
    if len(entries) > _MAX_HISTORY:
        entries = entries[-_MAX_HISTORY:]

    hist_path.write_text(json.dumps(entries, indent=2), encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════
# K-020 / K-022 — Delta Output Formatter
# ═══════════════════════════════════════════════════════════════════════


def format_delta_result(
    result: DeltaResult,
    *,
    as_json: bool = False,
    verbose: bool = False,
) -> str:
    """Format delta results for CLI display (K-020, K-022)."""
    if as_json:
        return result.to_json()

    lines = [result.summary()]

    if verbose:
        if result.files_changed:
            lines.append("\nFiles changed:")
            for f in result.files_changed:
                lines.append(f"  {f}")
        if result.nodes_added:
            lines.append(f"\nNodes added ({len(result.nodes_added)}):")
            for n in result.nodes_added[:20]:
                lines.append(f"  + {n}")
            if len(result.nodes_added) > 20:
                lines.append(f"  … and {len(result.nodes_added) - 20} more")
        if result.nodes_removed:
            lines.append(f"\nNodes removed ({len(result.nodes_removed)}):")
            for n in result.nodes_removed[:20]:
                lines.append(f"  - {n}")
            if len(result.nodes_removed) > 20:
                lines.append(f"  … and {len(result.nodes_removed) - 20} more")
        if result.stale_intents:
            lines.append(f"\nStale intents ({len(result.stale_intents)}):")
            for n in result.stale_intents:
                lines.append(f"  ⚠ {n}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# K-015 — File Rename Tracking (Graph_1 migration)
# ═══════════════════════════════════════════════════════════════════════


def _migrate_renames(
    renamed: List[Tuple[str, str]],
    graph1: Graph1,
) -> int:
    """Migrate Graph_1 intents from old → new file paths (K-015)."""
    migrated = 0
    for old_path, new_path in renamed:
        # Find all Graph_1 nodes for old path
        to_migrate: List[Any] = []
        for node in graph1.nodes:
            if node.id.startswith(old_path + "::"):
                to_migrate.append(node)

        for node in to_migrate:
            new_id = node.id.replace(old_path + "::", new_path + "::", 1)
            # Remove old, add with new ID
            graph1.remove_intent_node(node.id)
            node.id = new_id
            graph1.upsert_node(node)
            migrated += 1
            logger.info("Migrated intent: %s → %s", node.id, new_id)

    return migrated


# ═══════════════════════════════════════════════════════════════════════
# K-017 — Conflict with Pending Apply
# ═══════════════════════════════════════════════════════════════════════


def _check_pending_apply(project_root: Path) -> List[str]:
    """Check for pending codegraph apply changes (K-017)."""
    pending_path = resolve_path(project_root, ".pending_changes")
    if not pending_path.exists():
        return []
    try:
        data = json.loads(pending_path.read_text(encoding="utf-8"))
        return data.get("files", [])
    except (json.JSONDecodeError, OSError):
        return []


# ═══════════════════════════════════════════════════════════════════════
# K-021 / K-023 — CAS Pipeline Integration & Fallback
# ═══════════════════════════════════════════════════════════════════════


def _try_cas_pipeline(
    updates: Graph0Updates,
    old_graph0: Graph0,
    new_graph0: Graph0,
    workflow: Any,
    result: DeltaResult,
    project_root: Path,
) -> Optional[Set[str]]:
    """Attempt CAS invalidation propagation (K-021, Q-010).

    Returns affected_set if CAS succeeds, None on failure (K-023 fallback).
    """
    try:
        from codegraph.cas import (
            run_cas_pipeline,
            load_hash_snapshot,
            save_hash_snapshot,
            detect_node_changes,
        )
        from codegraph.storage import get_graph_version

        cached_hashes = load_hash_snapshot(project_root)
        affected_set, new_hashes = run_cas_pipeline(
            old_graph0, new_graph0, workflow, cached_hashes,
        )

        # Persist updated hashes on Graph0 nodes
        new_graph0.update_dependency_hashes(new_hashes)

        # Save snapshot for next delta
        version = get_graph_version(project_root)
        save_hash_snapshot(new_hashes, project_root, version)

        # Populate CAS stats on result
        node_changes = detect_node_changes(old_graph0, new_graph0)
        result.cas_enabled = True
        result.cas_body_changed_nodes = len(node_changes.body_changed)
        result.cas_affected_nodes = len(affected_set)
        total = len(new_graph0.nodes)
        result.cas_nodes_skipped = total - len(affected_set)
        if node_changes.body_changed:
            result.cas_propagation_factor = len(affected_set) / len(node_changes.body_changed)

        logger.info("CAS pipeline: %d affected nodes", len(affected_set))
        return affected_set

    except Exception as exc:
        logger.warning("CAS pipeline failed: %s. Falling back to file-level delta.", exc)
        result.cas_enabled = False

    return None  # CAS not available or failed


# ═══════════════════════════════════════════════════════════════════════
# K-001 — Delta Engine Core
# K-013 — Delta Dry Run
# K-016 — Performance Optimization
# ═══════════════════════════════════════════════════════════════════════


def run_delta(
    project_root: Path,
    config: Any = None,
    *,
    dry_run: bool = False,
    parallel: bool = False,
    force_full_rebuild: bool = False,
) -> DeltaResult:
    """Run incremental delta: detect changes, update graphs (K-001)."""
    state = _delta_load_state(project_root)
    graph0, current_version, current_commit = state

    result = DeltaResult(
        previous_graph_version=current_version,
        current_graph_version=current_version,
    )

    # K-002 — Get changed files
    changed = get_changed_files(project_root)
    result.files_changed = changed.all_changed + changed.deleted

    if changed.is_empty and not result.files_changed:
        logger.info("No changes detected — graph is current")
        return result

    # K-016 — Full rebuild if too many files changed
    total_files = len(set(n.file for n in graph0.nodes))
    if total_files > 0 and len(result.files_changed) > total_files * 0.5:
        logger.info(
            "Large change set (%d/%d files) — consider full rebuild",
            len(result.files_changed), total_files,
        )
        if force_full_rebuild:
            logger.info("Forcing full rebuild via flag")
            return result

    # K-017 — Check pending apply
    pending = _check_pending_apply(project_root)
    if pending:
        logger.warning(
            "Pending apply changes detected: %s", ", ".join(pending[:5]),
        )
        for f in pending:
            if f not in changed.modified and f not in changed.added:
                changed.modified.append(f)

    # K-004 — Re-extract changed files
    updates = reextract_changed(changed, graph0, project_root, parallel=parallel)

    if dry_run:
        result.nodes_added = [n.id for n in updates.added_nodes]
        result.nodes_removed = updates.removed_node_ids
        result.nodes_modified = [n.id for n in updates.modified_nodes]
        result.stale_intents = [lc.node_id for lc in updates.logic_changes]
        return result

    # K-005 — Merge and update
    new_graph0 = merge_graph0(graph0, updates)
    result.nodes_added = [n.id for n in updates.added_nodes]
    result.nodes_removed = updates.removed_node_ids
    result.nodes_modified = [n.id for n in updates.modified_nodes]

    new_graph0, new_workflow, result = _delta_update_graphs(
        project_root, changed, updates, graph0, new_graph0, result,
    )

    _delta_persist(project_root, new_graph0, new_workflow, updates, result, current_commit)

    return result


def _delta_load_state(project_root: Path):
    """Load current graph state for delta computation."""
    from codegraph.extractor import load_graph0
    from codegraph.git_utils import get_current_commit
    from codegraph.storage import get_graph_version

    graph0 = load_graph0(project_root)
    current_version = get_graph_version(project_root)
    current_commit = get_current_commit(project_root)
    return graph0, current_version, current_commit


def _delta_update_graphs(project_root, changed, updates, graph0, new_graph0, result):
    """Update workflow edges and graph1 intents."""
    from codegraph.annotator import load_graph1
    from codegraph.workflow import load_workflow

    workflow = load_workflow(project_root)
    affected_set = _try_cas_pipeline(
        updates, graph0, new_graph0, workflow, result, project_root,
    )

    graph1 = load_graph1(project_root)
    if changed.renamed:
        _migrate_renames(changed.renamed, graph1)

    stale = flag_stale_intents(updates.logic_changes, graph1)
    result.stale_intents = stale

    new_workflow, edges_added, edges_removed = recompute_edges(
        changed, new_graph0, workflow, updates.call_sites, updates.imports,
    )
    result.workflow_edges_added = edges_added
    result.workflow_edges_removed = edges_removed

    return new_graph0, new_workflow, result


def _delta_persist(project_root, new_graph0, new_workflow, updates, result, current_commit):
    """Save all delta artifacts to disk."""
    from codegraph.extractor import save_graph0
    from codegraph.annotator import load_graph1, save_graph1
    from codegraph.workflow import write_workflow

    graph1 = load_graph1(project_root)
    save_graph0(new_graph0, project_root)
    save_graph1(graph1, project_root)
    write_workflow(new_workflow, project_root)

    update_index(updates, new_graph0, graph1, new_workflow, project_root)

    new_version = _increment_version(project_root)
    result.current_graph_version = new_version

    if current_commit:
        _store_build_commit(project_root, current_commit)

    write_delta_result(result, project_root)
    _append_history(result, project_root)


# ═══════════════════════════════════════════════════════════════════════
# Delta History Display
# ═══════════════════════════════════════════════════════════════════════


def format_delta_history(project_root: Path) -> str:
    """Format delta history for display (K-012)."""
    hist_path = _delta_dir(project_root) / "history.json"
    if not hist_path.exists():
        return "No delta history."

    entries = json.loads(hist_path.read_text(encoding="utf-8"))
    if not entries:
        return "No delta history."

    lines = [f"Delta History ({len(entries)} entries):"]
    for e in entries[-10:]:  # Show last 10
        lines.append(
            f"  v{e['version']} [{e['timestamp']}]: "
            f"{e['files_changed']} files, "
            f"+{e['nodes_added']}/-{e['nodes_removed']}~{e['nodes_modified']} nodes, "
            f"+{e['edges_added']}/-{e['edges_removed']} edges"
        )
    return "\n".join(lines)
