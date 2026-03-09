# Group E — Annotation System (Graph_1)

> Intent application, metadata overlay management, stale intent detection, pruning, and Graph_1 lifecycle via `annotator.py`.

---

### TASK E-001 — Implement Graph_1 Initialization from Graph_0

**Description:**
Create Graph_1 skeleton from Graph_0 node list with empty intents and auto-detected layers.

**Reasoning:**
On first build, Graph_1 must be populated with all Graph_0 node IDs (with empty intents) so the system can track which nodes need annotation.

**Implementation Steps:**
1. Implement `initialize_graph1(graph0: Graph0, layer_assignments: dict) -> Graph1`
2. For each Graph_0 node, create a Graph_1 entry with:
   - `id` matching Graph_0 node
   - `intent: ""` (empty)
   - `layer` from layer_assignments
   - `intent_version: 0`
3. Handle existing Graph_1 (merge, don't overwrite existing intents)

**Files:**
- `codegraph/annotator.py`

**Dependencies:** B-002, B-004, D-007

**Edge Cases:**
- Graph_1 already exists with some entries → merge
- New nodes in Graph_0 not in Graph_1 → add
- Nodes removed from Graph_0 → mark as stale (don't auto-remove)

**Validation:**
- All Graph_0 nodes present in Graph_1
- Existing intents preserved on merge
- Layer assignments correct

---

### TASK E-002 — Implement Intent Application (Single Node)

**Description:**
Apply an intent annotation to a single node, updating Graph_1.

**Reasoning:**
This is the core annotation operation. It must increment version, update timestamp, and validate the intent string.

**Implementation Steps:**
1. Implement `apply_intent(graph1: Graph1, node_id: str, intent: str, author: str, tags: list[str] = None)`
2. Validate node_id exists in Graph_1
3. Validate intent quality (see B-016)
4. If node exists: update intent, increment version, update timestamp
5. If node doesn't exist: raise IntentConflictError
6. Optionally set tags and arch_layer

**Files:**
- `codegraph/annotator.py` (modify)

**Dependencies:** E-001, B-016, A-007

**Edge Cases:**
- Node not in Graph_1 → error
- Empty intent → warning
- Very long intent → warning
- Intent identical to existing → still increment version per spec or skip?

**Validation:**
- Intent applied correctly
- Version incremented
- Timestamp updated
- Invalid node ID raises error

---

### TASK E-003 — Implement Batch Intent Application

**Description:**
Apply multiple intent annotations from a JSON payload in a single operation.

**Reasoning:**
Agents submit intents as a batch in `agent_response.json`. Processing must be atomic — all succeed or provide clear error reporting.

**Implementation Steps:**
1. Implement `apply_intents_batch(graph1: Graph1, intents: list[IntentProposal], author: str) -> BatchResult`
2. Process each intent individually
3. Collect successes and failures
4. Don't stop on first failure — process all and report
5. Return `BatchResult` with applied/rejected counts and reasons

**Files:**
- `codegraph/annotator.py` (modify)

**Dependencies:** E-002, B-011

**Edge Cases:**
- Some intents valid, some invalid → apply valid, report invalid
- Duplicate node in batch → apply last one
- All intents invalid → return with all errors

**Validation:**
- Valid intents applied
- Invalid intents reported with reasons
- Batch result counts are accurate

---

### TASK E-004 — Implement Intent File Loading

**Description:**
Load intent annotations from a standalone JSON file (for `codegraph intent-apply intents.json`).

**Reasoning:**
The CLI accepts a JSON file with intents. This must be parsed, validated, and applied.

**Implementation Steps:**
1. Implement `load_intent_file(file_path: Path) -> list[IntentProposal]`
2. Parse JSON file
3. Validate structure against schema
4. Return list of IntentProposal objects
5. Handle malformed JSON with clear error

**Files:**
- `codegraph/annotator.py` (modify)

**Dependencies:** B-011, A-014

**Validation:**
- Valid JSON file loaded correctly
- Malformed JSON produces clear error
- Missing required fields produce validation errors

---

### TASK E-005 — Implement Stale Intent Detection

**Description:**
Detect nodes whose `body_hash` has changed since their intent was last updated.

**Reasoning:**
When function logic changes, the existing intent may no longer be accurate. The system flags these as stale but doesn't delete them.

**Implementation Steps:**
1. Implement `detect_stale_intents(graph0: Graph0, graph1: Graph1) -> list[str]`
2. For each Graph_1 node with an intent:
   - Find corresponding Graph_0 node
   - Compare current body_hash against hash at time of intent (stored in metadata)
   - If different → mark as stale
3. Return list of stale node IDs

**Files:**
- `codegraph/annotator.py` (modify)

**Dependencies:** B-002, B-004

**Edge Cases:**
- Node with no previous body_hash record → not stale (first annotation)
- Node removed from Graph_0 → handled separately (pruning)
- Body hash unchanged → not stale

**Validation:**
- Changed body_hash flags intent as stale
- Unchanged body_hash doesn't flag
- Missing Graph_0 node handled gracefully

---

### TASK E-006 — Implement Body Hash Tracking for Stale Detection

**Description:**
Store the body_hash at the time each intent was written, enabling stale detection on future builds.

**Reasoning:**
To know if an intent is stale, we need to compare the current body_hash against the hash when the intent was written.

**Implementation Steps:**
1. Add `intent_body_hash: str` field to Graph1Node
2. Set this field when intent is applied (copy from Graph_0)
3. Stale detection compares Graph_0 current body_hash against stored intent_body_hash
4. Migrate existing Graph_1 files without this field gracefully

**Files:**
- `codegraph/models/graph1.py` (modify)
- `codegraph/annotator.py` (modify)

**Dependencies:** B-003, E-002

**Validation:**
- Body hash stored on intent application
- Stale detection works with stored hash
- Old files without field handled gracefully

---

### TASK E-007 — Implement Graph_1 Pruning

**Description:**
Implement `codegraph prune` that removes Graph_1 entries referencing nodes no longer in Graph_0.

**Reasoning:**
After code deletion or refactoring, Graph_1 may contain "ghost" entries. Pruning cleans these up.

**Implementation Steps:**
1. Implement `prune_graph1(graph0: Graph0, graph1: Graph1) -> PruneReport`
2. Find all Graph_1 nodes where ID doesn't exist in Graph_0
3. Remove stale entries
4. Return report: count removed, IDs removed
5. Log warning for each removal as specified in README

**Files:**
- `codegraph/annotator.py` (modify)

**Dependencies:** B-025, B-002, B-004

**Edge Cases:**
- No stale entries → report 0 removed
- All entries stale → report all removed (unusual)
- Graph_0 empty → prune all (user warning)

**Validation:**
- Stale entries removed
- Valid entries preserved
- Warning logged with node IDs

---

### TASK E-008 — Implement Missing Intent Reporter

**Description:**
Implement `codegraph intent-missing` that lists all nodes without intent annotations.

**Reasoning:**
This is a core CLI command that tells agents which nodes need annotation.

**Implementation Steps:**
1. Implement `get_missing_intents(graph0: Graph0, graph1: Graph1) -> list[str]`
2. Find nodes in Graph_0 that either:
   - Don't exist in Graph_1
   - Exist in Graph_1 but have empty/None intent
3. Return list of node IDs
4. Sort by file path for readability

**Files:**
- `codegraph/annotator.py` (modify)

**Dependencies:** B-002, B-004

**Validation:**
- Unannotated nodes returned
- Annotated nodes excluded
- Empty intent treated as missing

---

### TASK E-009 — Implement Intent Tags Management

**Description:**
Implement tag management for Graph_1 nodes: add, remove, list tags.

**Reasoning:**
Tags enable grouping and normalization. The README suggests they're optional but recommended for large graphs.

**Implementation Steps:**
1. Implement `add_tags(graph1, node_id, tags: list[str])`
2. Implement `remove_tags(graph1, node_id, tags: list[str])`
3. Implement `get_nodes_by_tag(graph1, tag: str) -> list[str]`
4. Tags are case-insensitive, normalized to lowercase
5. No duplicate tags per node

**Files:**
- `codegraph/annotator.py` (modify)

**Dependencies:** B-003

**Edge Cases:**
- Adding existing tag → skip silently
- Removing non-existent tag → skip silently
- Empty tag string → error

**Validation:**
- Tags added and queryable
- Deduplication works
- Case normalization works

---

### TASK E-010 — Implement Arch Layer Annotation via CLI

**Description:**
Support setting `arch_layer` on Graph_1 nodes via `codegraph annotate --node <id> --arch-layer <value>`.

**Reasoning:**
The README specifies this as a way to set architectural layer annotations that enable rich policy rules.

**Implementation Steps:**
1. Implement `set_arch_layer(graph1, node_id, arch_layer: str)`
2. Validate node exists in Graph_1
3. Store arch_layer value
4. Warn on non-standard values (not in controller/service/domain/repository/infra)
5. Allow custom values without error

**Files:**
- `codegraph/annotator.py` (modify)

**Dependencies:** B-039, B-004

**Validation:**
- Standard values accepted without warning
- Custom values accepted with warning
- Non-existent node raises error

---

### TASK E-011 — Implement Intent Version Tracking

**Description:**
Track intent version history for audit purposes.

**Reasoning:**
`intent_version` increments on each update. This enables tracking how many times an intent has been refined.

**Implementation Steps:**
1. Ensure `intent_version` starts at 1 on first annotation
2. Increments by 1 on each update
3. Never decrements
4. Include in serialized output

**Files:**
- `codegraph/annotator.py` (modify)

**Dependencies:** E-002

**Validation:**
- First annotation → version 1
- Second update → version 2
- Batch application increments per node

---

### TASK E-012 — Implement Intent Author Tracking

**Description:**
Track who wrote each intent annotation (agent name, user, or "human").

**Reasoning:**
Intent authorship helps trace the origin of annotations. Useful for audit and quality assessment.

**Implementation Steps:**
1. Accept `author` parameter in all intent operations
2. Store as `intent_author` on Graph_1 node
3. Default author from config if not specified
4. Accept: agent names, usernames, "human"

**Files:**
- `codegraph/annotator.py` (modify)

**Dependencies:** E-002

**Validation:**
- Author stored and persisted
- Default author used when not specified

---

### TASK E-013 — Implement Graph_1 Merge Strategy

**Description:**
Define and implement the merge strategy when Graph_1 is updated after a Graph_0 rebuild.

**Reasoning:**
The README states: "Graph_1 persists across rebuilds — it is not discarded on a full rebuild." The merge must handle new nodes, removed nodes, and preserved intents.

**Implementation Steps:**
1. Implement `merge_graph1(existing_graph1: Graph1, new_graph0: Graph0, layers: dict) -> Graph1`
2. For nodes in new Graph_0:
   - If exists in Graph_1: preserve intent, update layer if changed
   - If not in Graph_1: add with empty intent and detected layer
3. For nodes in Graph_1 not in new Graph_0:
   - Mark as stale (for prune to handle)
   - Don't auto-remove
4. Return merged Graph_1

**Files:**
- `codegraph/annotator.py` (modify)

**Dependencies:** E-001, D-007

**Validation:**
- Existing intents preserved
- New nodes added with empty intent
- Stale entries marked, not removed

---

### TASK E-014 — Implement Graph_1 Persistence (Save/Load)

**Description:**
Implement saving Graph_1 to `.codegraph/graphs/graph1.json` and loading it back.

**Reasoning:**
Graph_1 is committed to version control. It must serialize cleanly and handle forward/backward compatibility.

**Implementation Steps:**
1. Implement `save_graph1(graph1: Graph1, project_root: Path)`
2. Use atomic file writer
3. Format: indented JSON, sorted by node ID for clean diffs
4. Implement `load_graph1(project_root: Path) -> Graph1`
5. Handle missing file (first run)

**Files:**
- `codegraph/annotator.py` (modify)

**Dependencies:** B-004, A-013

**Edge Cases:**
- First run, no graph1.json → return empty Graph_1
- File exists but has old format → handle migration
- File has extra fields → ignore (forward compat)

**Validation:**
- Load after save produces identical Graph_1
- Missing file returns empty
- Sorted output for clean git diffs

---

### TASK E-015 — Implement Intent Conflict Resolution

**Description:**
Handle the case where an agent submits intent for a node that no longer exists in Graph_0.

**Reasoning:**
Per the failure modes table: "Agent submits intent for a node that no longer exists in Graph_0 → CLI rejects the entry and reports mismatched IDs."

**Implementation Steps:**
1. During intent application, validate node exists in current Graph_0
2. If node not in Graph_0: reject with `IntentConflictError`
3. Include the missing node ID in the error message
4. Continue processing other intents in the batch

**Files:**
- `codegraph/annotator.py` (modify)

**Dependencies:** E-002, E-003, A-007

**Validation:**
- Non-existent node rejected
- Error message includes node ID
- Other intents in batch still processed

---

### TASK E-016 — Implement Module and Class Intent Support

**Description:**
Ensure intent annotation works for module and class nodes, not just functions.

**Reasoning:**
The README explicitly states: "Intent is not limited to functions. Graph_1 can annotate modules and classes."

**Implementation Steps:**
1. Verify module nodes (type: module) accept intent annotations
2. Verify class nodes (type: class) accept intent annotations
3. Ensure intent quality validation works for module/class descriptions
4. Module intents describe the module's purpose
5. Class intents describe the class's responsibility

**Files:**
- `codegraph/annotator.py` (modify)

**Dependencies:** E-002, B-040

**Validation:**
- Module intent applied and persisted
- Class intent applied and persisted
- Quality validation appropriate for each type

---

### TASK E-017 — Implement Intent Normalization

**Description:**
Normalize intent strings for consistency: trim whitespace, normalize case, ensure consistent formatting.

**Reasoning:**
Intents from different agents or humans may have inconsistent formatting. Normalization improves readability and comparison.

**Implementation Steps:**
1. Implement `normalize_intent(intent: str) -> str`
2. Strip leading/trailing whitespace
3. Collapse multiple spaces to single
4. Lowercase first character (intents are descriptions, not titles)
5. Remove trailing period if present

**Files:**
- `codegraph/annotator.py` (modify)

**Dependencies:** E-002

**Validation:**
- "  Fetch  data  " → "fetch data"
- "Utility function." → "utility function"
- Already normalized intent unchanged

---

### TASK E-018 — Implement Intent Consistency Checker

**Description:**
Check for inconsistent intents across nodes that share tags or similar names.

**Reasoning:**
The README mentions future tooling for normalization candidates. A basic consistency checker is a first step.

**Implementation Steps:**
1. Implement `check_intent_consistency(graph1: Graph1) -> list[ConsistencyWarning]`
2. Group nodes by tags
3. Within each group, check for:
   - Very different intents for similar functions
   - Duplicate intent text across functions (copy-paste)
4. Report as warnings

**Files:**
- `codegraph/annotator.py` (modify)

**Dependencies:** B-004, E-009

**Edge Cases:**
- No tags → skip grouping
- Single node in group → skip
- Identical intents for different functions → warning

**Validation:**
- Inconsistent intents within tag group detected
- Duplicate intents flagged

---

### TASK E-019 — Implement Graph_1 Export for Review

**Description:**
Export Graph_1 annotations in a human-readable format for review outside the system.

**Reasoning:**
Teams may want to review intent annotations in a spreadsheet or document format before committing.

**Implementation Steps:**
1. Implement `export_graph1(graph1: Graph1, format: str) -> str`
2. Support formats: JSON (default), CSV, Markdown table
3. Include: node_id, intent, layer, arch_layer, tags
4. Sort by file path

**Files:**
- `codegraph/annotator.py` (modify)

**Dependencies:** B-004

**Validation:**
- CSV export is valid CSV
- Markdown table renders correctly
- All nodes included

---

### TASK E-020 — Implement Graph_1 Import from External Sources

**Description:**
Import intent annotations from external sources (e.g., CSV, previously exported data).

**Reasoning:**
Teams may maintain intent annotations externally or want to bulk-import from a review process.

**Implementation Steps:**
1. Implement `import_intents(file_path: Path, format: str) -> list[IntentProposal]`
2. Support CSV and JSON formats
3. Validate imported data against schema
4. Convert to IntentProposal list for standard application flow

**Files:**
- `codegraph/annotator.py` (modify)

**Dependencies:** E-004

**Validation:**
- CSV import works
- JSON import works
- Invalid data produces clear errors

---

### TASK E-021 — Implement Stale Intent Warning in Build Output

**Description:**
When `codegraph build` detects stale Graph_1 entries, emit the warning format specified in the README.

**Reasoning:**
The README shows a specific warning format. This must be implemented exactly as shown.

**Implementation Steps:**
1. After Graph_0 rebuild, run alignment check
2. For each stale entry, emit warning:
   ```
   WARNING: stale intent entries detected
     src/old_module.py::deprecated_fn → no matching node in graph0
   Run `codegraph prune` to remove stale entries.
   ```
3. Also warn about body_hash-changed nodes

**Files:**
- `codegraph/annotator.py` (modify)

**Dependencies:** E-005, B-025

**Validation:**
- Warning format matches README exactly
- Prune suggestion included
- Both types of staleness reported

---

### TASK E-022 — Implement Graph_1 Diff for Review

**Description:**
Show what changed in Graph_1 since last commit or specified version.

**Reasoning:**
Before committing Graph_1 changes, reviewers may want to see what intents were added, modified, or removed.

**Implementation Steps:**
1. Implement `diff_graph1(old: Graph1, new: Graph1) -> Graph1Diff`
2. Detect: new entries, removed entries, modified intents
3. For modified: show old intent vs new intent
4. Format for CLI output

**Files:**
- `codegraph/annotator.py` (modify)

**Dependencies:** B-004

**Validation:**
- New intents detected
- Modified intents show old→new
- Removed intents detected

---

### TASK E-023 — Implement Bulk Arch Layer Assignment

**Description:**
Allow batch assignment of `arch_layer` to nodes matching a pattern.

**Reasoning:**
Setting arch_layer one node at a time is tedious. Batch assignment by directory, file pattern, or tag is practical.

**Implementation Steps:**
1. Implement `batch_set_arch_layer(graph1, pattern: str, arch_layer: str)`
2. Pattern can be: file path prefix, glob, tag match
3. Apply arch_layer to all matching nodes
4. Report count of affected nodes

**Files:**
- `codegraph/annotator.py` (modify)

**Dependencies:** E-010, B-032

**Validation:**
- Pattern matching works with glob
- Correct nodes updated
- Count reported

---

### TASK E-024 — Implement Graph_1 Statistics

**Description:**
Generate statistics about Graph_1 annotation coverage and quality.

**Reasoning:**
Status reporting needs annotation coverage metrics. This feeds into `codegraph status`.

**Implementation Steps:**
1. Implement `graph1_statistics(graph0, graph1) -> AnnotationStats`
2. Compute:
   - Total nodes
   - Nodes with intent
   - Nodes missing intent
   - Average intent length
   - Nodes with tags
   - Nodes with arch_layer
   - Stale intent count
3. Return structured statistics

**Files:**
- `codegraph/annotator.py` (modify)

**Dependencies:** B-002, B-004, E-005

**Validation:**
- All statistics computed correctly
- Coverage percentage = nodes_with_intent / total_nodes

---

### TASK E-025 — Implement Intent History Tracking

**Description:**
Optionally track the history of intent changes per node.

**Reasoning:**
Auditing intent evolution helps understand how understanding of a function changed over time, especially when multiple agents contribute.

**Implementation Steps:**
1. Add optional `intent_history: list[dict]` to Graph1Node
2. Each entry: `{version, intent, author, timestamp}`
3. On intent update, append to history before replacing
4. Limit history to last 10 entries to prevent bloat
5. Make history tracking configurable (off by default)

**Files:**
- `codegraph/models/graph1.py` (modify)
- `codegraph/annotator.py` (modify)
- `codegraph/config.py` (modify)

**Dependencies:** E-002, E-011

**Edge Cases:**
- History disabled → no overhead
- History limit reached → oldest entries dropped
- First annotation → no history entry (nothing to replace)

**Validation:**
- History records previous intents
- Limit respected
- Disabled by default
