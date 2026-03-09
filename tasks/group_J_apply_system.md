# Group J — Apply System & Repair Actions

> Agent response parsing, code modification execution, repair action types, version validation, formatting, and Graph_1 update via `apply.py`.

---

### TASK J-001 — Implement Apply Engine Core

**Description:**
Create the core apply engine that dispatches agent response actions to specific handlers.

**Reasoning:**
The apply system receives agent responses and modifies code + graph accordingly. Each action type has a specific handler.

**Implementation Steps:**
1. Create `codegraph/apply.py`
2. Implement `apply_response(response: AgentResponse, project_root, graph0, graph1, workflow) -> ApplyResult`
3. Validate response version
4. Dispatch each action to its handler:
   - `connect_call` → `handle_connect_call()`
   - `add_import` → `handle_add_import()`
   - `remove_dead_code` → `handle_remove_dead_code()`
   - `flag_for_human_review` → `handle_flag_for_review()`
5. Collect results, continue on individual failure

**Files:**
- `codegraph/apply.py`

**Dependencies:** I-013, B-011, B-013

**Validation:**
- Valid response dispatches correctly
- Individual action failure doesn't stop batch
- Results collected for all actions

---

### TASK J-002 — Implement `connect_call` Action Handler

**Description:**
Implement the connect_call action that inserts a function call at the first executable statement of the source function.

**Reasoning:**
README: "connect_call: insert a function call at the first executable statement of the source function. If the target module is not already imported, add an import statement first."

**Implementation Steps:**
1. Implement `handle_connect_call(action, source_file, graph0) -> ActionResult`
2. Parse source file AST
3. Find the source function node
4. Identify first executable statement (skip decorators, docstrings)
5. Insert call statement: `target_function()`
6. If target module not imported → also add import
7. Rewrite file with modification

**Files:**
- `codegraph/apply.py` (modify)

**Dependencies:** J-001, C-001

**Edge Cases:**
- Source function is empty (just `pass`) → insert before `pass`
- Source function has only docstring → insert after docstring
- Target function takes arguments → use defaults or flag
- Already connected → README failure: "already connected — connect_call action references an edge that already exists. Agents must check the current workflow before proposing connect_call."
- Nested function → navigate to correct scope

**Validation:**
- Call inserted at correct location
- Import added if needed
- Already-connected case detected and rejected

---

### TASK J-003 — Implement `add_import` Action Handler

**Description:**
Implement the add_import action that appends an import statement to the import block.

**Reasoning:**
README: "add_import: append an import statement to the import block at the top of the target file."

**Implementation Steps:**
1. Implement `handle_add_import(action, target_file) -> ActionResult`
2. Parse file to find the import block
3. Determine import style (match existing: `import X` vs `from X import Y`)
4. Append new import at end of import block
5. Don't add if already imported

**Files:**
- `codegraph/apply.py` (modify)

**Dependencies:** J-001, C-016

**Edge Cases:**
- No existing imports → add at top after module docstring
- Mixed import styles → use dominant style
- Circular import → flag but proceed
- Already imported → skip with log
- Import alias → preserve alias style

**Validation:**
- Import added in correct location
- Existing import not duplicated
- File parses correctly after modification

---

### TASK J-004 — Implement `remove_dead_code` Action Handler

**Description:**
Implement the remove_dead_code action with the strict four-signal requirement.

**Reasoning:**
README: "remove_dead_code: requires confirmation of all four dead-code signals: orphan node in workflow graph, no test calls the function, body_hash unchanged since project baseline, no intent annotation."

**Implementation Steps:**
1. Implement `handle_remove_dead_code(action, node_id, graph0, graph1, workflow, index) -> ActionResult`
2. Verify all four signals:
   a. Orphan node: no callers and no callees in workflow
   b. No test calls: no test edges in tests index
   c. Body hash unchanged: compare with baseline hash
   d. No intent annotation: no entry in Graph_1
3. If ALL four → proceed with removal
4. If ANY missing → reject with details of which signals failed

**Files:**
- `codegraph/apply.py` (modify)

**Dependencies:** J-001, G-011, B-002, B-004

**Edge Cases:**
- README failure mode: "insufficient dead code signals — remove_dead_code action submitted but fewer than 4 signals confirmed. System rejects."
- Function used via dynamic dispatch → appears orphan but isn't
- Function with stale/missing intent but still called → not dead

**Validation:**
- All 4 signals present → code removed
- Any signal missing → rejection with details
- Removed code no longer in file

---

### TASK J-005 — Implement `flag_for_human_review` Action Handler

**Description:**
Implement the flag action that records an issue without modifying code.

**Reasoning:**
README: "flag_for_human_review: record the flag in delta.json without modifying source files."

**Implementation Steps:**
1. Implement `handle_flag_for_review(action, node_id) -> ActionResult`
2. Create review flag entry with:
   - Node ID
   - Reason (from agent)
   - Timestamp
   - Task ID that triggered it
3. Append to review log at `.codegraph/reviews/pending.json`
4. No code modification

**Files:**
- `codegraph/apply.py` (modify)

**Dependencies:** J-001

**Validation:**
- Flag recorded in review log
- No source files modified
- Review entry includes all metadata

---

### TASK J-006 — Implement Workflow Suggestion Handling

**Description:**
Process workflow suggestions from agent responses, adding them to suggested_workflow.json as proposed rules.

**Reasoning:**
README states agents can include workflow_suggestions in their response, which get promoted to permanent rules.

**Implementation Steps:**
1. Extract `workflow_suggestions` from agent response
2. For each suggestion:
   - Validate format (rule_type, source, target, scope)
   - Add to suggested_workflow.json as "proposed" status
   - Log the addition
3. Optionally auto-promote (configurable)

**Files:**
- `codegraph/apply.py` (modify)

**Dependencies:** J-001, H-022, B-011

**Validation:**
- Suggestions added to suggested_workflow.json
- Proposed status set
- Invalid suggestions rejected

---

### TASK J-007 — Implement Graph_1 Update After Apply

**Description:**
Update Graph_1 metadata after code modifications: update body_hash, mark intents as stale.

**Reasoning:**
After apply modifies source code, the affected nodes' body hashes change. Graph_1 must reflect this.

**Implementation Steps:**
1. Implement `update_graph1_after_apply(applied_actions, graph0, graph1) -> Graph1`
2. For each modified function:
   - Re-calculate body_hash from new source
   - Update Graph_1 body_hash
   - If body_hash changed → mark intent as stale
3. For removed functions → remove from Graph_1
4. Save updated Graph_1

**Files:**
- `codegraph/apply.py` (modify)

**Dependencies:** J-001, C-010, E-005

**Validation:**
- Body hashes updated after modification
- Stale intents marked
- Removed nodes cleaned from Graph_1

---

### TASK J-008 — Implement Code Formatter Integration (Black)

**Description:**
Run Black formatter on modified files after code changes.

**Reasoning:**
README states: "After modifying code, the apply system runs black (or configured formatter) on the affected file."

**Implementation Steps:**
1. After each file modification, run `black --quiet <file>`
2. Handle black not being installed → warning, skip formatting
3. Support configurable formatter (black by default)
4. Preserve non-formatting changes

**Files:**
- `codegraph/apply.py` (modify)

**Dependencies:** J-001, A-003

**Edge Cases:**
- Black not installed → warning, proceed without formatting
- Black changes line numbers → re-extract after formatting
- Black configuration conflict → use project's pyproject.toml settings

**Validation:**
- Modified files formatted
- Formatting doesn't break inserted code
- Missing formatter doesn't crash

---

### TASK J-009 — Implement Apply Transaction Management

**Description:**
Implement transactional apply: all changes succeed or all are rolled back.

**Reasoning:**
If one action fails after others have modified files, the codebase is in an inconsistent state. Transaction management ensures atomicity.

**Implementation Steps:**
1. Before apply: backup all files that will be modified
2. Apply all actions sequentially
3. If any action fails: restore all backups
4. If all succeed: delete backups
5. Backup stored in `.codegraph/backups/`

**Files:**
- `codegraph/apply.py` (modify)

**Dependencies:** J-001

**Edge Cases:**
- Power failure during apply → backups remain for manual recovery
- Large number of files → ensure backup doesn't exceed disk space
- Concurrent apply attempts → lock file

**Validation:**
- Successful apply cleans backups
- Failed apply restores all files
- Backup files are correct copies

---

### TASK J-010 — Implement Apply Lock File

**Description:**
Prevent concurrent apply operations with a lock file.

**Reasoning:**
Two parallel apply operations would corrupt the codebase.

**Implementation Steps:**
1. Create lock file `.codegraph/.apply.lock` at start
2. Check for existing lock → error with PID and message
3. Remove lock on completion (even on failure)
4. Include PID and timestamp in lock
5. Stale lock detection (PID no longer running)

**Files:**
- `codegraph/apply.py` (modify)

**Dependencies:** J-001

**Validation:**
- Lock prevents concurrent apply
- Lock cleaned up on success and failure
- Stale lock detected and cleared

---

### TASK J-011 — Implement Apply Dry Run Mode

**Description:**
Support `--dry-run` that shows what changes would be made without modifying files.

**Reasoning:**
Users and agents need to preview changes before applying them.

**Implementation Steps:**
1. Add `dry_run` parameter to apply functions
2. In dry run: generate diffs for each action without writing files
3. Display planned changes in unified diff format
4. Include file path, line numbers, operation type

**Files:**
- `codegraph/apply.py` (modify)

**Dependencies:** J-001

**Validation:**
- Dry run produces readable diff
- No files modified
- Diff matches actual changes

---

### TASK J-012 — Implement Already-Connected Detection

**Description:**
Detect when a `connect_call` action targets an edge that already exists.

**Reasoning:**
README failure mode: "already connected — connect_call action references an edge that already exists."

**Implementation Steps:**
1. Before executing connect_call:
   - Check workflow for existing edge from source to target
   - Check source file AST for existing call to target
2. If edge exists → reject with clear message
3. If call exists in code but not in workflow → suggest delta rebuild

**Files:**
- `codegraph/apply.py` (modify)

**Dependencies:** J-002, F-019

**Validation:**
- Already-connected case detected
- Clear error message
- Suggestion to rebuild if inconsistent

---

### TASK J-013 — Implement Apply Conflict Detection

**Description:**
Detect when an apply action conflicts with uncommitted changes.

**Reasoning:**
README failure mode: "apply conflict — codegraph apply would modify a file that has uncommitted, non-codegraph edits."

**Implementation Steps:**
1. Before modifying a file:
   - Run `git status` to check for uncommitted changes
   - If file has uncommitted changes → check if they're codegraph-generated
   - If non-codegraph changes → reject with message to commit first
2. Track codegraph modifications via `.codegraph/.pending_changes`

**Files:**
- `codegraph/apply.py` (modify)

**Dependencies:** J-001, A-017

**Edge Cases:**
- Untracked file → warn but proceed
- File in .gitignore → proceed (not under git control)
- Merge conflict state → always reject

**Validation:**
- Uncommitted changes detected
- Codegraph changes distinguished
- Conflict rejected with helpful message

---

### TASK J-014 — Implement Dead Code Baseline Hash Store

**Description:**
Store and manage body_hash baselines for the dead code signal check.

**Reasoning:**
The dead code check requires "body_hash unchanged since project baseline." The baseline must be established at some point.

**Implementation Steps:**
1. Create baseline store at `.codegraph/baselines/hashes.json`
2. Initialize baseline on first `codegraph build`
3. Update baseline via `codegraph baseline update`
4. Compare current body_hash against baseline for dead code check

**Files:**
- `codegraph/apply.py` (modify)

**Dependencies:** J-004, C-010

**Validation:**
- Baseline created on first build
- Changed functions have different hash than baseline
- Unchanged functions match baseline

---

### TASK J-015 — Implement Apply Result Reporter

**Description:**
Generate a structured report of all apply actions and their outcomes.

**Reasoning:**
After apply, users/agents need to know what happened: successes, failures, skips.

**Implementation Steps:**
1. Implement `format_apply_result(result: ApplyResult) -> str`
2. For each action: status (success/failed/skipped), details, file modified
3. Summary: total actions, succeeded, failed, skipped
4. Support `--json` output

**Files:**
- `codegraph/apply.py` (modify)

**Dependencies:** J-001

**Validation:**
- All actions reported
- Status accurate
- JSON output parseable

---

### TASK J-016 — Implement AST-Safe Code Insertion

**Description:**
Implement safe code insertion that maintains valid Python AST after modification.

**Reasoning:**
Simply inserting text into a file can break indentation, scope, or syntax. AST-aware insertion prevents this.

**Implementation Steps:**
1. Use `ast` module to understand insertion context
2. Determine correct indentation level for insertion point
3. For function calls: match surrounding code style
4. For imports: match import block style
5. After insertion: re-parse AST to verify validity

**Files:**
- `codegraph/apply.py` (modify)

**Dependencies:** J-002, C-001

**Edge Cases:**
- Tab vs space indentation → match file style
- Mixed indentation → use dominant style
- Multiline insertions → maintain consistent indent

**Validation:**
- Inserted code is syntactically valid
- Indentation matches context
- File parses after modification

---

### TASK J-017 — Implement Function Body Removal for Dead Code

**Description:**
Safely remove a complete function/class from source code.

**Reasoning:**
remove_dead_code must remove the entire function definition while preserving surrounding code.

**Implementation Steps:**
1. Identify function start and end lines from AST
2. Include decorators in removal range
3. Remove blank lines between this function and next code
4. Handle edge cases: only function in file, function at end of file
5. Preserve comments that are NOT part of the function

**Files:**
- `codegraph/apply.py` (modify)

**Dependencies:** J-004, C-001

**Edge Cases:**
- Function is only content in file → leave empty file or delete file?
- Class method → remove only method, not class
- Nested function → only remove inner function
- Code after function on same line (impossible in Python, but edge case)

**Validation:**
- Function completely removed
- Surrounding code intact
- File still parses

---

### TASK J-018 — Implement Import Cleanup After Dead Code Removal

**Description:**
After removing dead code, clean up imports that are no longer needed.

**Reasoning:**
Removing a function may orphan imports that were only used by that function.

**Implementation Steps:**
1. After removing code:
   - Re-parse the file's AST
   - Find all name references in remaining code
   - Identify imports that are no longer referenced
   - Remove unused imports
2. Use conservative approach: only remove if definitely unused

**Files:**
- `codegraph/apply.py` (modify)

**Dependencies:** J-017

**Edge Cases:**
- Import used by other functions in same file → keep
- Star imports → can't determine, keep
- Import used only in type annotations → keep
- `__all__` references → keep

**Validation:**
- Unused imports removed
- Used imports preserved
- File still valid after cleanup

---

### TASK J-019 — Implement Apply Undo Support

**Description:**
Support undoing the last apply operation.

**Reasoning:**
If an apply produces bad results, users need to quickly revert.

**Implementation Steps:**
1. Save undo information before apply: files before, files after, actions
2. Store at `.codegraph/undo/last_apply.json` + file backups
3. Implement `undo_last_apply(project_root)`
4. Restore files from backups
5. Revert Graph_1 changes

**Files:**
- `codegraph/apply.py` (modify)

**Dependencies:** J-009

**Validation:**
- Undo restores files exactly
- Graph_1 reverted
- Only last apply undoable

---

### TASK J-020 — Implement Apply Validation Post-Check

**Description:**
After applying changes, run validation to ensure the codebase is still consistent.

**Reasoning:**
After apply, files must still parse, tests should still pass, and the graph should be consistent.

**Implementation Steps:**
1. After successful apply:
   - Re-parse all modified files (AST check)
   - Run quick syntax validation
   - Optionally run affected tests
   - Log validation results
2. Warn if any validation fails (don't auto-revert)

**Files:**
- `codegraph/apply.py` (modify)

**Dependencies:** J-001, C-001

**Validation:**
- Syntax errors caught
- Valid modifications pass
- Warning issued on validation failure
