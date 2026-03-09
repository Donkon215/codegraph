# Group K — Delta Engine

> Incremental change detection, git diff integration, AST re-extraction, stale intent flagging, workflow recomputation, version increment, and delta output via `delta.py`.

---

### TASK K-001 — Implement Delta Engine Core

**Description:**
Create the core delta engine that detects changes since the last graph build and updates the graph incrementally.

**Reasoning:**
The delta engine is the incremental update path. Instead of full rebuild, it only processes changed files, making it much faster for large codebases.

**Implementation Steps:**
1. Create `codegraph/delta.py`
2. Implement `run_delta(project_root, config) -> DeltaResult`
3. Steps:
   a. Get changed files from git
   b. Re-extract changed files (AST)
   c. Compare new Graph_0 nodes with old
   d. Update Graph_0, flag stale Graph_1 intents
   e. Recompute workflow edges for changed files
   f. Update index incrementally
   g. Increment graph_version
4. Return DeltaResult with all change details

**Files:**
- `codegraph/delta.py`

**Dependencies:** A-017, C-020, F-023, G-008, A-012, B-012

**Validation:**
- Changed files detected and re-extracted
- Graph_0 updated with new nodes
- Graph_version incremented

---

### TASK K-002 — Implement Git Diff Parser

**Description:**
Parse `git diff` output to determine which files have changed since the last build.

**Reasoning:**
README states: "Delta detects file-level changes using git diff. It compares the current working tree against the commit recorded in the last graph build."

**Implementation Steps:**
1. Implement `get_changed_files(project_root, since_commit=None) -> ChangedFiles`
2. Run `git diff --name-status <commit>..HEAD`
3. Parse output into: added, modified, deleted, renamed file lists
4. Store last-build commit in `.codegraph/metadata.json`
5. Handle uncommitted changes

**Files:**
- `codegraph/delta.py` (modify)

**Dependencies:** A-017

**Edge Cases:**
- No git repo → error with message
- No previous build commit → fall back to full rebuild
- Uncommitted changes → README failure mode: "delta uncommitted — git diff finds changes not committed"
- Binary files in diff → skip
- Renamed files → track old→new mapping

**Validation:**
- Added files detected
- Modified files detected
- Deleted files detected
- Renamed files tracked

---

### TASK K-003 — Implement Uncommitted Changes Detection

**Description:**
Detect and handle uncommitted changes in the working tree.

**Reasoning:**
README failure mode: "delta uncommitted — git diff finds changes that are not committed. codegraph logs a warning and processes the working tree state."

**Implementation Steps:**
1. Run `git status --porcelain` to check for uncommitted changes
2. If uncommitted changes exist:
   - Log warning: "Processing uncommitted changes"
   - Include both staged and unstaged changes
   - Mark delta result as "includes_uncommitted: true"
3. Process working tree state (not just committed state)

**Files:**
- `codegraph/delta.py` (modify)

**Dependencies:** K-002

**Validation:**
- Uncommitted changes produce warning
- Changes still processed
- Delta result flagged

---

### TASK K-004 — Implement Incremental AST Re-Extraction

**Description:**
Re-extract AST only for files that have changed, reusing cached data for unchanged files.

**Reasoning:**
Full re-extraction of all files is expensive. Only changed files need new AST parsing.

**Implementation Steps:**
1. Implement `reextract_changed(changed_files, graph0, project_root) -> Graph0Updates`
2. For each changed file:
   - Parse new AST
   - Extract new nodes
   - Compare with old nodes from current Graph_0
   - Determine: added nodes, removed nodes, modified nodes (body_hash changed)
3. For deleted files: mark all their nodes as removed
4. For added files: all nodes are new

**Files:**
- `codegraph/delta.py` (modify)

**Dependencies:** K-002, C-020, B-002

**Edge Cases:**
- File renamed → old nodes removed, new nodes added (with possibly same body_hash)
- File with syntax errors → log error, skip file
- Empty file → remove all previous nodes

**Validation:**
- Only changed files re-extracted
- New/removed/modified nodes correctly classified
- Unchanged files untouched

---

### TASK K-005 — Implement Graph_0 Merge

**Description:**
Merge the delta's node updates into the existing Graph_0.

**Reasoning:**
The existing Graph_0 needs to be updated: add new nodes, remove deleted nodes, update modified nodes.

**Implementation Steps:**
1. Implement `merge_graph0(current: Graph0, updates: Graph0Updates) -> Graph0`
2. Remove nodes from deleted/modified files
3. Add new/modified nodes
4. Re-assign node IDs for renamed files
5. Validate no node ID collisions

**Files:**
- `codegraph/delta.py` (modify)

**Dependencies:** K-004, B-002

**Edge Cases:**
- Node ID collision (same function name in new file) → detect and handle per B-025
- Module node for deleted file → remove
- Class partially modified → update only changed methods

**Validation:**
- Merged Graph_0 contains correct nodes
- No stale nodes from deleted files
- No node ID collisions

---

### TASK K-006 — Implement Body Hash Change Detection

**Description:**
Compare old and new body hashes to determine which functions actually changed logic.

**Reasoning:**
A file may be modified (whitespace, comments) without changing any function's logic. Body hash comparison distinguishes real changes from cosmetic ones.

**Implementation Steps:**
1. Implement `detect_logic_changes(old_nodes, new_nodes) -> list[LogicChange]`
2. Match nodes by ID
3. Compare body_hash:
   - Same hash → no logic change (may be whitespace/comment only)
   - Different hash → logic changed
4. Return list of actually-changed nodes

**Files:**
- `codegraph/delta.py` (modify)

**Dependencies:** K-004, C-010

**Validation:**
- Whitespace-only change → no logic change detected
- Comment-only change → no logic change
- Actual code change → logic change detected

---

### TASK K-007 — Implement Stale Intent Flagging

**Description:**
Mark Graph_1 intents as stale when their corresponding function's body_hash changes.

**Reasoning:**
When code logic changes, existing intents may no longer be accurate. They must be flagged for review.

**Implementation Steps:**
1. Implement `flag_stale_intents(logic_changes: list[LogicChange], graph1: Graph1) -> Graph1`
2. For each changed node:
   - If has intent in Graph_1 → mark as stale
   - Update body_hash in Graph_1 metadata
   - Set `stale_since: graph_version`
3. Preserve original intent text (don't delete)

**Files:**
- `codegraph/delta.py` (modify)

**Dependencies:** K-006, B-004, E-005

**Validation:**
- Changed function with intent → flagged stale
- Changed function without intent → no action
- Unchanged function → not flagged

---

### TASK K-008 — Implement Workflow Edge Recomputation for Changed Files

**Description:**
Recompute workflow edges only for functions in changed files.

**Reasoning:**
Workflow edges from/to modified functions may have changed. Only those edges need updating.

**Implementation Steps:**
1. Implement `recompute_edges(changed_nodes: set[str], graph0: Graph0, workflow: Workflow) -> Workflow`
2. Remove all edges where source or target is a changed node
3. Re-extract call sites from changed files
4. Build new static edges for changed functions
5. Note: runtime trace edges NOT recomputed (would require test re-run)
6. Merge with existing unchanged edges

**Files:**
- `codegraph/delta.py` (modify)

**Dependencies:** K-005, F-001, F-023

**Validation:**
- Edges from changed functions updated
- Edges between unchanged functions preserved
- Static edges recalculated

---

### TASK K-009 — Implement Index Incremental Update

**Description:**
Update the graph index incrementally for changed nodes.

**Reasoning:**
README describes the delta index update process: remove old entries, insert new entries.

**Implementation Steps:**
1. Call `update_index_delta()` from G-008 with delta changes
2. Remove: old nodes, old caller/callee entries, old layer entries
3. Insert: new nodes, new edges, new layer assignments
4. Verify index consistency after update

**Files:**
- `codegraph/delta.py` (modify)

**Dependencies:** K-005, K-008, G-008

**Validation:**
- Index updated correctly
- Consistency check passes
- Equivalent to full rebuild for changed entities

---

### TASK K-010 — Implement Graph Version Increment

**Description:**
Increment the graph_version counter after a successful delta.

**Reasoning:**
graph_version tracks mutations. Every successful delta must increment it to invalidate stale references.

**Implementation Steps:**
1. Read current graph_version from `.codegraph/metadata.json`
2. Increment by 1
3. Write new version atomically
4. Record the delta commit hash alongside version

**Files:**
- `codegraph/delta.py` (modify)

**Dependencies:** A-012

**Validation:**
- Version increments by exactly 1
- Previous version recoverable from metadata
- Atomic write prevents corruption

---

### TASK K-011 — Implement Delta Result Output

**Description:**
Generate the `delta.json` output file with all change details.

**Reasoning:**
Delta results must be persisted for audit and debugging. Also consumed by the CLI for display.

**Implementation Steps:**
1. Implement `write_delta_result(result: DeltaResult, project_root)`
2. Structure:
   ```json
   {
     "graph_version": 43,
     "previous_version": 42,
     "timestamp": "...",
     "changed_files": [...],
     "added_nodes": [...],
     "removed_nodes": [...],
     "modified_nodes": [...],
     "stale_intents": [...],
     "edges_added": N,
     "edges_removed": N
   }
   ```
3. Write atomically to `.codegraph/delta/delta.json`

**Files:**
- `codegraph/delta.py` (modify)

**Dependencies:** K-001, B-012, A-013

**Validation:**
- Valid JSON written
- All change details present
- Version numbers correct

---

### TASK K-012 — Implement Delta History Log

**Description:**
Maintain a history of delta operations for trend analysis.

**Reasoning:**
Tracking delta history helps understand how the codebase evolves and whether problems are increasing or decreasing.

**Implementation Steps:**
1. Append each delta result summary to `.codegraph/delta/history.json`
2. Include: version, timestamp, file count, node counts (added/removed/modified)
3. Limit history length (configurable, default 100)
4. Support `codegraph delta --history` display

**Files:**
- `codegraph/delta.py` (modify)

**Dependencies:** K-011

**Validation:**
- History grows with each delta
- Size limit enforced
- History display works

---

### TASK K-013 — Implement Delta Dry Run

**Description:**
Support `--dry-run` for delta that shows what would change without modifying graphs.

**Reasoning:**
Preview changes before committing them to the graph.

**Implementation Steps:**
1. Add `dry_run` parameter to `run_delta()`
2. In dry run: detect all changes but don't write any files
3. Display: files changed, nodes affected, edges affected
4. Useful for CI/CD checks

**Files:**
- `codegraph/delta.py` (modify)

**Dependencies:** K-001

**Validation:**
- Dry run detects same changes as real run
- No files modified
- Output shows changes clearly

---

### TASK K-014 — Implement Delta Baseline Commit Tracking

**Description:**
Track the git commit used for each build/delta to determine the correct diff baseline.

**Reasoning:**
Each delta needs to know what commit the last build was based on. This determines the git diff range.

**Implementation Steps:**
1. Store `last_build_commit` in `.codegraph/metadata.json`
2. After build/delta: update with current HEAD commit
3. Delta reads this to determine diff range
4. Handle: no previous commit (first build), rebased history

**Files:**
- `codegraph/delta.py` (modify)

**Dependencies:** K-002, A-012

**Edge Cases:**
- Git rebase changed history → commit may not exist → fall back to full rebuild
- Shallow clone → commit may not be reachable → warn
- Detached HEAD → use HEAD as baseline

**Validation:**
- Commit tracked after build
- Correct diff range computed
- Missing commit triggers rebuild

---

### TASK K-015 — Implement File Rename Tracking

**Description:**
Track file renames to preserve node identity when files are renamed.

**Reasoning:**
When a file is renamed, all node IDs change (they include file name). Tracking renames allows preserving Graph_1 metadata.

**Implementation Steps:**
1. Parse `git diff --name-status -M` for rename detection
2. Map old file path → new file path
3. For each Graph_1 entry in renamed file:
   - Update node ID to new file path
   - Preserve intent and metadata
4. Log renamed mappings

**Files:**
- `codegraph/delta.py` (modify)

**Dependencies:** K-002, B-004

**Edge Cases:**
- File renamed and modified simultaneously → handle both
- File copied (not renamed) → treat as new file
- Partial rename detection by git → may miss some

**Validation:**
- Renamed file preserves Graph_1 metadata
- Node IDs updated correctly
- Intent metadata migrated

---

### TASK K-016 — Implement Delta Performance Optimization

**Description:**
Optimize delta for large repos where many files change simultaneously.

**Reasoning:**
After large refactors or merge commits, many files may change. Delta must handle this efficiently.

**Implementation Steps:**
1. Profile delta on batches of 10, 100, 1000 changed files
2. Parallel AST extraction for changed files
3. Batch index updates
4. Consider: if > 50% of files changed, trigger full rebuild instead
5. Target: delta of 100 changed files < 5 seconds

**Files:**
- `codegraph/delta.py` (modify)

**Dependencies:** K-001

**Validation:**
- Performance benchmark met
- Correctness unchanged
- Full rebuild triggered when appropriate

---

### TASK K-017 — Implement Delta Conflict with Pending Apply

**Description:**
Handle the case where delta runs while apply has pending changes.

**Reasoning:**
If `codegraph apply` generated code changes that haven't been committed, delta needs to include them.

**Implementation Steps:**
1. Before delta: check for `.codegraph/.pending_changes`
2. If pending: include those files in the delta set
3. Warn that changes are uncommitted
4. Process normally

**Files:**
- `codegraph/delta.py` (modify)

**Dependencies:** K-001, J-013

**Validation:**
- Pending apply changes included in delta
- Warning issued
- Graph state consistent

---

### TASK K-018 — Implement Graph_0 Snapshot Comparison

**Description:**
Compare two Graph_0 snapshots to produce a detailed diff.

**Reasoning:**
Used by `codegraph diff` and internally by delta to understand exactly what changed structurally.

**Implementation Steps:**
1. Implement `diff_graph0(old: Graph0, new: Graph0) -> Graph0Diff`
2. Compare:
   - Added nodes (in new, not in old)
   - Removed nodes (in old, not in new)
   - Modified nodes (same ID, different body_hash)
   - Unchanged nodes
3. Return structured diff

**Files:**
- `codegraph/delta.py` (modify)

**Dependencies:** B-002

**Validation:**
- All change types detected
- No false positives
- Structurally accurate

---

### TASK K-019 — Implement Delta Trigger Detection

**Description:**
Detect whether delta is needed by checking if any files have changed since last build.

**Reasoning:**
If no files changed, delta is a no-op. Quick check avoids unnecessary processing.

**Implementation Steps:**
1. Implement `needs_delta(project_root) -> bool`
2. Quick check: `git diff --stat <last_commit>..HEAD`
3. If no changes → return False
4. If changes → return True
5. Used by `codegraph status` to show "Graph is current" vs "Graph is stale"

**Files:**
- `codegraph/delta.py` (modify)

**Dependencies:** K-014

**Validation:**
- No changes → False
- File changes → True
- Fast check (< 100ms)

---

### TASK K-020 — Implement Delta Output Formatter

**Description:**
Format delta results for CLI display.

**Reasoning:**
After running delta, users need a clear summary of what changed.

**Implementation Steps:**
1. Implement `format_delta_result(result: DeltaResult) -> str`
2. Sections:
   - Files changed: added, modified, deleted, renamed
   - Nodes: added, removed, modified
   - Edges: added, removed
   - Stale intents flagged
   - New graph_version
3. Support `--json` and `--verbose`

**Files:**
- `codegraph/delta.py` (modify)

**Dependencies:** K-011

**Validation:**
- All sections present
- Counts accurate
- Both formats work

---

### TASK K-021 — Integrate CAS Pipeline into Delta Core

**Description:**
Extend `run_delta()` to invoke the CAS dependency hash pipeline after body_hash comparison: propagate invalidation, compute affected set, and narrow all subsequent steps to affected nodes only.

**Reasoning:**
This is the main delta engine integration point for the Content Addressed Graph system (Group Q). Instead of recomputing workflow edges, index entries, and stale intents for all nodes in changed files, the CAS pipeline narrows the scope to only the transitively affected node set — the exact nodes whose behavior may have changed.

**Implementation Steps:**
1. After K-006 (body hash change detection), invoke CAS invalidation propagation (Q-007)
2. Receive `affected_set: set[str]` — the minimal set of nodes needing recomputation
3. Pass `affected_set` to:
   - K-008 workflow edge recomputation (narrow to affected edges)
   - K-007 stale intent flagging (narrow to affected intents)
   - K-009 index update (narrow to affected entries)
4. Invoke Q-008 to recompute dependency_hashes for affected set
5. Save updated hash snapshot (Q-018)
6. Log CAS statistics: body_changed, affected, skipped, propagation_factor
7. Skip CAS if `--no-cas` flag is set or CAS disabled in config

**Files:**
- `codegraph/delta.py` (modify)

**Dependencies:** K-001, K-006, Q-007, Q-008, Q-018, Q-036

**Edge Cases:**
- No dependency_hashes in current graph (pre-CAS) → auto-migrate via Q-035
- CAS disabled → use existing file-level logic unchanged
- Affected set > 50% of total nodes → switch to full rebuild

**Validation:**
- Delta with CAS produces identical Graph_0 as full rebuild
- Fewer nodes processed than file-level delta
- CAS statistics appear in delta output
- `--no-cas` flag bypasses CAS correctly

---

### TASK K-022 — Add CAS Statistics to Delta Output

**Description:**
Include CAS metrics in the delta result output and CLI display: affected node count, propagation factor, nodes skipped, and cache hit rate.

**Reasoning:**
Measuring CAS effectiveness is essential for tuning and validating the system. Statistics in the delta output let developers see exactly how much work CAS saved.

**Implementation Steps:**
1. After CAS pipeline completes, populate `DeltaResult` CAS fields (B-042)
2. Add CAS section to `format_delta_result()` in K-020:
   ```
   CAS Graph:
     Body-changed nodes:  3
     Affected nodes:      12  (propagation factor: 4.0×)
     Nodes skipped:       988  (98.8%)
     Cycles detected:     0
   ```
3. Include in `--json` output
4. Omit section when CAS is disabled

**Files:**
- `codegraph/delta.py` (modify)

**Dependencies:** K-020, K-021, B-042

**Validation:**
- CAS statistics accurate and displayed
- Section omitted when CAS disabled
- JSON output includes CAS fields

---

### TASK K-023 — Implement CAS Fallback on Failure

**Description:**
If the CAS pipeline fails during delta (corrupt snapshot, hash mismatch), fall back gracefully to file-level delta without stopping the operation.

**Reasoning:**
CAS is an optimization. Its failure must never prevent a successful delta. Graceful fallback ensures robustness.

**Implementation Steps:**
1. Wrap CAS pipeline steps in try/except
2. On any CAS exception:
   a. Log warning: "CAS pipeline failed: {error}. Falling back to file-level delta."
   b. Discard CAS results
   c. Proceed with existing file-level delta logic
   d. Mark delta result: `cas_fallback: true`
3. After successful delta, consider rebuilding CAS snapshot for next run

**Files:**
- `codegraph/delta.py` (modify)

**Dependencies:** K-021, Q-040

**Edge Cases:**
- Corrupt hash snapshot → fall back, rebuild snapshot
- Out of memory during propagation → fall back
- Hash verification mismatch → fall back, log for investigation

**Validation:**
- CAS failure does not crash delta
- File-level fallback produces correct results
- Warning logged with failure details
