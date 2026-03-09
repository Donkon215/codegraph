# Group Q — Content Addressed Graph (CAS Graph)

> Dependency hashing, hash propagation, node-level invalidation, incremental recomputation, CAS-aware delta, and Bazel-style content-addressed build graph for codegraph.

**Principle:** Instead of file-level change detection, compute a `dependency_hash` per node that includes the node's own `body_hash` plus the hashes of everything it calls. When any leaf changes, invalidation propagates upward through the dependency graph — instantly identifying every affected node without AST re-traversal.

**Analogy:** This is the same principle behind **Bazel**, **Buck**, **LLVM incremental builds**, and **Nix** — content-addressed dependency graphs that only recompute what actually changed.

---

## Phase 1 — Core Hash Infrastructure

---

### TASK Q-001 — Add `dependency_hash` Field to Graph0Node

**Description:**
Extend the `Graph0Node` data model with a new `dependency_hash` field that captures the transitive content identity of a node and everything it depends on.

**Reasoning:**
`body_hash` tracks only the function's own body. `dependency_hash` = `hash(body_hash + sorted(callee_dependency_hashes))`. This single field turns the graph into a content-addressed structure where any downstream change is visible at every upstream node.

**Implementation Steps:**
1. Add `dependency_hash: Optional[str]` to `Graph0Node` dataclass in `codegraph/models/graph0.py`
2. Default to `None` (computed lazily after workflow edges are known)
3. Update `to_dict()` / `from_dict()` serialization
4. Update `Graph0` collection to support bulk dependency_hash updates
5. Update `graph0.schema.json` to include the new field
6. Ensure backward compatibility — old graph0.json files without field load with `dependency_hash = None`

**Files:**
- `codegraph/models/graph0.py` (modify)
- `codegraph/schemas/graph0.schema.json` (modify)

**Dependencies:** B-001, B-002, B-029

**Edge Cases:**
- Old graph files without `dependency_hash` → default to None, trigger recomputation
- Nodes with no callees → `dependency_hash == body_hash`
- Module nodes with no body → `dependency_hash` computed from contained nodes

**Validation:**
- Field serializes and deserializes correctly
- None value handled on load (backward compat)
- Nodes with no callees have `dependency_hash == body_hash`

---

### TASK Q-002 — Implement Dependency Hash Computation Algorithm

**Description:**
Implement the core algorithm that computes `dependency_hash` for a single node given its `body_hash` and the `dependency_hash` values of all its direct callees.

**Reasoning:**
The hash formula is: `dependency_hash = SHA256(body_hash + sort(callee_1.dependency_hash, callee_2.dependency_hash, ...))`. Sorting ensures determinism regardless of call order in source code. SHA256 provides collision resistance.

**Implementation Steps:**
1. Create `codegraph/cas.py` — the CAS (Content Addressed Store) module
2. Implement `compute_dependency_hash(body_hash: str, callee_hashes: list[str]) -> str`
3. Sort callee hashes lexicographically for determinism
4. Concatenate: `body_hash + ":" + ":".join(sorted_callee_hashes)`
5. Return `hashlib.sha256(concatenated.encode()).hexdigest()`
6. If callee_hashes is empty → return `hashlib.sha256(body_hash.encode()).hexdigest()`
7. Document the hash construction scheme for reproducibility

**Files:**
- `codegraph/cas.py`

**Dependencies:** Q-001, C-010

**Edge Cases:**
- No callees → hash of just body_hash (leaf node)
- Callee with None dependency_hash → use callee's body_hash as fallback
- Very large callee list (100+ calls) → ensure sort + hash is fast
- Unicode in hash input → encode as UTF-8

**Validation:**
- Same inputs always produce same hash (determinism)
- Different callee order produces same hash (sort invariance)
- Changing one callee's hash changes the parent's dependency_hash
- Leaf node: `compute_dependency_hash("abc123", []) == sha256("abc123")`

---

### TASK Q-003 — Implement Topological Sort for Hash Computation Order

**Description:**
Implement topological sorting of the call graph to determine the correct bottom-up computation order for dependency hashes.

**Reasoning:**
Dependency hashes must be computed bottom-up: leaves first, then their callers, then callers-of-callers. Topological sort on the reversed call graph gives this order. Nodes in cycles need special handling (see Q-004).

**Implementation Steps:**
1. Implement `topological_sort(workflow: Workflow, graph0: Graph0) -> list[str]` in `codegraph/cas.py`
2. Build adjacency list from workflow edges (caller → callee)
3. Detect cycles using Tarjan's or Kahn's algorithm
4. Return nodes in reverse topological order (leaves first)
5. Nodes in cycles → return as a single SCC (strongly connected component)
6. Handle disconnected subgraphs (multiple roots)

**Files:**
- `codegraph/cas.py` (modify)

**Dependencies:** Q-002, B-006, F-001

**Edge Cases:**
- Fully disconnected graph → each node is a leaf
- Single large cycle → all nodes in one SCC
- Diamond dependencies (A→B, A→C, B→D, C→D) → D computed first, then B and C, then A
- Dynamic edges (unresolved) → exclude from topological sort

**Validation:**
- Every node's callees appear before it in the sorted order
- Cycles detected and grouped into SCCs
- All nodes are present in the output
- DAG produces valid topological order

---

### TASK Q-004 — Handle Circular Dependencies in Hash Computation

**Description:**
Implement cycle-aware hashing for mutually recursive functions where standard bottom-up computation is impossible.

**Reasoning:**
Mutual recursion creates cycles: `A → B → A`. Neither can be computed first. The solution is to hash the entire strongly connected component (SCC) as a unit: all body_hashes in the cycle are concatenated (sorted by ID) to produce a single SCC hash, which is then used as the dependency_hash for every member.

**Implementation Steps:**
1. Implement `compute_scc_hash(scc_nodes: list[str], graph0: Graph0) -> str` in `codegraph/cas.py`
2. Collect `body_hash` for each node in the SCC
3. Sort by node_id for determinism
4. Hash: `SHA256(node_1_id + ":" + node_1_body + ":" + node_2_id + ":" + node_2_body + ...)`
5. Assign the same `dependency_hash` to all members of the SCC
6. When SCC members also call external nodes, include those external dependency_hashes too
7. Log a notice when cycles are detected — this is informational, not an error

**Files:**
- `codegraph/cas.py` (modify)

**Dependencies:** Q-003

**Edge Cases:**
- Self-recursion (A → A) → SCC of size 1, hash includes just A's body
- Large SCC (10+ nodes) → performance concern, but correct
- SCC that calls external nodes → include external dependency_hashes in SCC hash
- Nested cycles (SCC within SCC) → Tarjan handles this naturally

**Validation:**
- Mutual recursion A↔B: both get same dependency_hash
- Changing A's body changes the SCC hash for both A and B
- Self-recursive function: dependency_hash != body_hash (includes self-reference marker)
- SCC with external deps: external change propagates into SCC hash

---

### TASK Q-005 — Implement Full Graph Dependency Hash Builder

**Description:**
Implement the top-level function that computes `dependency_hash` for every node in the entire graph, used during `codegraph build`.

**Reasoning:**
After the workflow (call graph) is built, we have all the information to compute dependency hashes. This runs once during full build, then incrementally during delta.

**Implementation Steps:**
1. Implement `build_dependency_hashes(graph0: Graph0, workflow: Workflow) -> dict[str, str]` in `codegraph/cas.py`
2. Steps:
   a. Run topological sort (Q-003)
   b. Identify SCCs (Q-004)
   c. Process nodes in topological order:
      - For leaf nodes: `dep_hash = hash(body_hash)`
      - For SCC members: compute SCC hash (Q-004)
      - For regular nodes: `dep_hash = hash(body_hash + callee_dep_hashes)` (Q-002)
   d. Store computed hashes back to Graph0 nodes
3. Return mapping: `{node_id: dependency_hash}`
4. Log timing: "Computed dependency hashes for N nodes in X.Xs"

**Files:**
- `codegraph/cas.py` (modify)

**Dependencies:** Q-002, Q-003, Q-004, B-002, B-006

**Edge Cases:**
- Empty graph → empty dict
- All nodes are leaves → all dep_hashes are just hashed body_hashes
- Graph is one giant cycle → single SCC hash for all
- Node with callee not in Graph_0 (external call) → skip that callee

**Validation:**
- Every node in Graph_0 gets a dependency_hash
- Leaf nodes computed correctly
- SCC nodes computed correctly
- Timer logs show reasonable performance (< 1s for 10k nodes)

---

## Phase 2 — Invalidation & Propagation

---

### TASK Q-006 — Implement Reverse Dependency Index for CAS

**Description:**
Build a reverse dependency map (`callee → [callers]`) optimized for upward hash propagation.

**Reasoning:**
When a node's body changes, we need to find all its callers (direct and transitive) to invalidate their dependency_hashes. This is the reverse of the call graph — the "who depends on me?" lookup.

**Implementation Steps:**
1. Implement `build_reverse_dependency_map(workflow: Workflow) -> dict[str, set[str]]` in `codegraph/cas.py`
2. For each workflow edge: add `target → source` to the reverse map
3. Support transitive closure: `get_all_dependents(node_id, reverse_map) -> set[str]`
4. Use BFS with visited set for cycle safety
5. Cache the reverse map for reuse during delta

**Files:**
- `codegraph/cas.py` (modify)

**Dependencies:** Q-005, B-006

**Edge Cases:**
- Node with no dependents → empty set
- Circular dependents → BFS visited set prevents infinite loop
- Dynamic edges → include in reverse map (conservative)

**Validation:**
- `A → B → C`: reverse map has `C → {B}`, `B → {A}`
- Transitive: all_dependents(C) = {B, A}
- Circular: A↔B → dependents(A) = {B}, dependents(B) = {A}

---

### TASK Q-007 — Implement Hash Invalidation Propagation Engine

**Description:**
Given a set of nodes whose `body_hash` changed, propagate invalidation upward through the dependency graph to find all nodes whose `dependency_hash` is now stale.

**Reasoning:**
This is the core CAS advantage. Instead of re-analyzing entire files, we trace upward from changed nodes to find exactly which nodes are affected. This is O(affected_nodes) instead of O(changed_files × nodes_per_file).

**Implementation Steps:**
1. Implement `propagate_invalidation(changed_nodes: set[str], reverse_map: dict) -> set[str]` in `codegraph/cas.py`
2. Starting from `changed_nodes`, BFS upward through reverse dependency map
3. Collect all transitively affected nodes
4. Return `affected_set = changed_nodes ∪ all_transitive_dependents`
5. The affected set is the minimal set that needs recomputation
6. Log: "N changed nodes → M affected nodes (propagation factor: M/N)"

**Files:**
- `codegraph/cas.py` (modify)

**Dependencies:** Q-006

**Edge Cases:**
- Changed node has no dependents → affected set = just the changed node
- Changed leaf node → may affect entire chain up to entry points
- Multiple changed nodes with overlapping dependents → union, no duplicates
- All nodes affected → equivalent to full rebuild (logged as warning)

**Validation:**
- Single leaf change propagates to all ancestors
- Multiple changes produce union of affected sets
- Propagation factor logged for monitoring
- No duplicates in affected set

---

### TASK Q-008 — Implement Selective Dependency Hash Recomputation

**Description:**
Recompute `dependency_hash` only for affected nodes (those invalidated by propagation), leaving all unaffected hashes cached.

**Reasoning:**
After invalidation propagation identifies the affected set, only those nodes need their `dependency_hash` recomputed. Unaffected nodes retain their cached hashes. This is the "only recompute what changed" guarantee.

**Implementation Steps:**
1. Implement `recompute_affected_hashes(affected: set[str], graph0: Graph0, workflow: Workflow) -> dict[str, str]` in `codegraph/cas.py`
2. Topological sort only the affected subgraph
3. For each affected node (bottom-up):
   a. Get current body_hash from updated Graph_0
   b. Get dependency_hashes of callees (may be cached or freshly computed)
   c. Compute new dependency_hash
4. Return mapping of updated hashes
5. Log: "Recomputed M dependency hashes (out of N total nodes)"

**Files:**
- `codegraph/cas.py` (modify)

**Dependencies:** Q-007, Q-005, Q-003

**Edge Cases:**
- Affected node calls an unaffected node → use cached dependency_hash for callee
- Affected SCC → recompute entire SCC hash
- Recomputation produces same hash as before → node was affected but not actually changed (transitive false positive)
- Performance: affected set might be large after core library change

**Validation:**
- Unaffected nodes not recomputed (verify via counter)
- Recomputed hashes match what full rebuild would produce
- Performance: 100 affected nodes out of 10k total < 100ms

---

### TASK Q-009 — Implement Node-Level Change Detection (Replace File-Level)

**Description:**
Replace the current file-level change detection with precise node-level change detection using `dependency_hash` comparison.

**Reasoning:**
Current delta: "file changed → re-extract all nodes in file → compare body_hashes". CAS delta: "file changed → re-extract changed functions → compare dependency_hashes → propagate". This is strictly more precise — a whitespace change in function A of a file no longer invalidates function B in the same file.

**Implementation Steps:**
1. Implement `detect_node_changes(old_graph0: Graph0, new_graph0: Graph0) -> NodeChanges` in `codegraph/cas.py`
2. Compare by node ID:
   - `body_hash` unchanged → node definitely unchanged
   - `body_hash` changed → node body changed, dependency_hash must be recomputed
   - Node added → new node, needs full hash computation
   - Node removed → remove from graph and propagate to dependents
3. Return `NodeChanges(added, removed, body_changed, unchanged)`
4. This replaces the coarse "all nodes in changed file" approach

**Files:**
- `codegraph/cas.py` (modify)

**Dependencies:** Q-001, K-004, K-006

**Edge Cases:**
- File modified but no body_hash changes (comment/whitespace only) → zero changed nodes
- Function signature changed but body unchanged → body_hash unchanged, no CAS impact
- New function added to existing file → only new node, existing nodes unaffected

**Validation:**
- Comment-only change → 0 changed nodes
- Single function change in 100-function file → 1 changed node
- Results match manual inspection

---

## Phase 3 — Delta Engine Integration

---

### TASK Q-010 — Integrate CAS with Delta Engine Core

**Description:**
Upgrade the delta engine (`delta.py`) to use CAS-based node-level change detection and hash propagation instead of file-level change detection.

**Reasoning:**
This is the main integration point. The delta engine currently recomputes everything in changed files. With CAS, it recomputes only the minimal affected node set.

**Implementation Steps:**
1. Modify `run_delta()` in `codegraph/delta.py` to add CAS pipeline:
   ```
   git diff → changed files
   → re-extract AST for changed files (existing)
   → detect node-level changes via body_hash comparison (Q-009)
   → propagate invalidation upward (Q-007)
   → recompute dependency_hashes for affected set only (Q-008)
   → recompute workflow edges only for affected nodes (existing K-008, narrowed)
   → update index only for affected nodes
   → flag stale intents only for affected nodes
   ```
2. Add `--no-cas` flag to fall back to file-level delta for debugging
3. Log CAS statistics: changed_nodes, affected_nodes, propagation_factor, nodes_skipped
4. Store new dependency_hashes in Graph_0

**Files:**
- `codegraph/delta.py` (modify)

**Dependencies:** Q-007, Q-008, Q-009, K-001, K-002, K-004

**Edge Cases:**
- First delta after upgrade (no dependency_hashes in graph) → fall back to full recomputation
- CAS disabled via flag → use existing file-level logic
- Very large affected set (>50% of nodes) → switch to full rebuild

**Validation:**
- Delta with CAS produces identical Graph_0 as full rebuild
- Delta with CAS skips more nodes than file-level delta
- Performance improvement measurable on 1k+ node projects
- `--no-cas` flag bypasses CAS correctly

---

### TASK Q-011 — Implement CAS-Aware Workflow Edge Recomputation

**Description:**
Narrow workflow edge recomputation from "all edges in changed files" to "only edges involving affected nodes".

**Reasoning:**
Current K-008 recomputes edges for all functions in changed files. CAS narrows this to only the affected node set from propagation. If a file has 50 functions but only 1 changed, only that 1 function's edges are recomputed.

**Implementation Steps:**
1. Modify `recompute_edges()` in `codegraph/delta.py`
2. Accept `affected_nodes: set[str]` parameter from CAS propagation
3. Only remove and re-extract edges where source ∈ affected_nodes
4. Edges between two unaffected nodes are untouched
5. Edges from unaffected → affected: keep (the callee changed, not the caller's code)
6. Edges from affected → anything: recompute (the caller's code changed)

**Files:**
- `codegraph/delta.py` (modify)

**Dependencies:** Q-010, K-008, F-001

**Edge Cases:**
- Affected node gained new callee → new edge added
- Affected node lost a callee → old edge removed
- Unaffected node calls affected node → edge preserved (caller's code didn't change)
- Both sides of an edge affected → recompute

**Validation:**
- Fewer edges recomputed than file-level approach
- Result matches full rebuild for affected edges
- Unaffected edges are byte-identical

---

### TASK Q-012 — Implement CAS-Aware Index Update

**Description:**
Narrow index updates from "all nodes in changed files" to "only affected nodes from CAS propagation".

**Reasoning:**
Index updates (G-008) currently process all nodes from changed files. CAS narrows this to the affected set, reducing index write operations.

**Implementation Steps:**
1. Modify `update_index_delta()` (or create `update_index_cas()`) in `codegraph/index.py`
2. Accept `affected_nodes: set[str]` from CAS propagation
3. Only update index entries for nodes in the affected set
4. Update body_hash and dependency_hash columns in nodes.db
5. Update caller/callee entries only for affected nodes
6. Leave all unaffected index entries untouched

**Files:**
- `codegraph/index.py` (modify)

**Dependencies:** Q-010, G-008

**Edge Cases:**
- Affected node added → insert into all index tables
- Affected node removed → delete from all index tables
- Affected node modified → update in place
- Index consistency: affected set may include nodes whose dependency_hash changed but body_hash didn't

**Validation:**
- Index after CAS update matches result of full index rebuild
- Fewer SQL operations than file-level update
- Index consistency check (G-010) passes after CAS update

---

### TASK Q-013 — Implement CAS-Aware Stale Intent Detection

**Description:**
Use CAS propagation to detect both directly stale and transitively stale intents.

**Reasoning:**
Current stale detection only catches nodes whose `body_hash` changed. CAS adds a new category: **transitively stale** — nodes whose body is unchanged but whose dependencies changed, meaning the node's behavior may have changed even though its code didn't.

**Implementation Steps:**
1. Implement `detect_stale_intents_cas(affected_nodes: set[str], body_changed_nodes: set[str], graph1: Graph1) -> StaleIntentReport` in `codegraph/cas.py`
2. Classify affected nodes:
   - `directly_stale`: body_hash changed AND has intent → intent may be wrong
   - `transitively_stale`: body_hash unchanged BUT dependency_hash changed AND has intent → callee behavior changed, intent may still be valid but should be reviewed
3. Return both categories separately with different severity levels
4. Transitively stale = lower priority than directly stale

**Files:**
- `codegraph/cas.py` (modify)

**Dependencies:** Q-007, K-007, E-005

**Edge Cases:**
- Node is transitively stale but intent explicitly mentions "delegates to X" → intent is actually stale
- Node with no intent → skip (nothing to stale)
- Transitively stale but callee change was cosmetic (reformat) → false positive, but safe

**Validation:**
- Direct body change → directly_stale
- Callee body change, caller unchanged → transitively_stale
- No change → not stale
- Both categories reported with different severity

---

## Phase 4 — CAS-Aware Analysis & Agent Integration

---

### TASK Q-014 — Implement CAS-Aware Task Generation

**Description:**
Use the CAS affected set to generate tasks only for nodes that are actually impacted by changes, instead of all nodes in changed files.

**Reasoning:**
Task generation currently processes all findings. With CAS, the analyzer can scope its work to only the affected node set, producing fewer, more precise tasks. An agent receiving a task knows the exact propagation chain that triggered it.

**Implementation Steps:**
1. Modify `analyze()` in `codegraph/analyzer.py` to accept `affected_nodes: Optional[set[str]]`
2. When affected_nodes is provided:
   - Only check orphan status for affected nodes
   - Only check policy violations involving affected nodes
   - Only check stale intents for affected nodes (both direct and transitive)
   - Only check coverage gaps for affected nodes
3. Include `propagation_chain` in task context: "This task was triggered because node X changed, which propagated through Y to reach Z"
4. Tag affected tasks with `cas_triggered: true`

**Files:**
- `codegraph/analyzer.py` (modify)

**Dependencies:** Q-013, I-001, I-002, I-003

**Edge Cases:**
- Affected set is None (full analysis mode) → no CAS filtering, run all checks
- Affected set is empty → no tasks generated
- Policy rule involves one affected and one unaffected node → still check (conservative)

**Validation:**
- Fewer tasks generated with CAS than without (on partial changes)
- All CAS-generated tasks have propagation_chain context
- Full analysis mode produces same results as before (backward compat)

---

### TASK Q-015 — Implement CAS-Aware Test Impact Analysis

**Description:**
Use CAS hash propagation to instantly determine affected tests instead of backward graph tracing.

**Reasoning:**
Current test impact (M-007) traces backward through the call graph from changed nodes to find test functions. CAS provides this for free: any test node in the `affected_set` is an affected test. No graph traversal needed.

**Implementation Steps:**
1. Implement `test_impact_cas(affected_nodes: set[str], graph0: Graph0, graph1: Graph1) -> TestImpactResult` in `codegraph/cas.py`
2. Filter affected_nodes to only Layer 4 (test) nodes
3. For each affected test node:
   a. Find which changed production node triggered it (shortest path from body_changed → test)
   b. Classify: direct (test's dependency_hash changed because it calls changed function) vs transitive
4. Return structured result compatible with existing TestImpactResult model
5. Performance: O(|affected_set|) instead of O(|changed_nodes| × graph_depth)

**Files:**
- `codegraph/cas.py` (modify)

**Dependencies:** Q-007, M-007, D-005

**Edge Cases:**
- No tests in affected set → no test impact
- All tests affected (core library change) → equivalent to "run all tests"
- Test calls changed function through 10 levels of indirection → CAS catches it, backward trace might miss with depth limit

**Validation:**
- CAS test impact matches backward-trace test impact (same affected tests)
- CAS test impact is faster (benchmark)
- Deep transitive dependencies caught

---

### TASK Q-016 — Implement CAS-Aware Policy Rule Evaluation

**Description:**
Only evaluate policy rules (suggested workflow) that involve nodes in the CAS affected set.

**Reasoning:**
If a rule says "A must call B" but neither A nor B is in the affected set, there's no need to re-evaluate that rule. CAS scoping makes policy evaluation O(affected_rules) instead of O(all_rules × nodes).

**Implementation Steps:**
1. Implement `filter_affected_rules(rules: list[Rule], affected_nodes: set[str], graph0: Graph0) -> list[Rule]` in `codegraph/cas.py`
2. A rule is affected if:
   - Its source or target (after scope expansion) includes any affected node
   - Its source or target uses a layer/arch_layer that contains affected nodes
3. Only evaluate affected rules during delta analysis
4. Log: "Evaluated M of N policy rules (CAS filtering)"

**Files:**
- `codegraph/cas.py` (modify)

**Dependencies:** Q-007, H-001, H-010, B-032

**Edge Cases:**
- Glob rule matching many nodes → affected if any matched node is in affected set
- Layer-scoped rule → affected if any node at that layer is in affected set
- Rule with both source and target affected → definitely evaluate
- Rule with neither affected → skip

**Validation:**
- Affected rules evaluated correctly
- Unaffected rules skipped
- Results match full evaluation for affected rules

---

## Phase 5 — Storage & Index

---

### TASK Q-017 — Implement Dependency Hash Index Table

**Description:**
Add a `dependency_hashes` table to the SQLite index for O(1) dependency_hash lookups.

**Reasoning:**
During delta, we need to quickly look up the previous `dependency_hash` for any node to compare with the newly computed one. A dedicated index table avoids loading the entire Graph_0 JSON.

**Implementation Steps:**
1. Add table to index: `CREATE TABLE dependency_hashes (node_id TEXT PRIMARY KEY, dependency_hash TEXT, body_hash TEXT, computed_at TEXT)`
2. Implement `build_dependency_hash_index(cas_results: dict)` in `codegraph/index.py`
3. Implement `get_dependency_hash(node_id) -> Optional[str]`
4. Implement `get_all_dependency_hashes() -> dict[str, str]` for bulk loading
5. Implement delta update: `update_dependency_hashes(changes: dict[str, str])`
6. Include in full index build (G-007) and delta index update (G-008)

**Files:**
- `codegraph/index.py` (modify)

**Dependencies:** Q-005, G-001, G-007

**Edge Cases:**
- Node not in index → return None (new node)
- Index empty (first build with CAS) → build from scratch
- Migration from pre-CAS index → add table, populate on next build

**Validation:**
- O(1) lookup time
- All nodes indexed after build
- Delta update modifies only affected nodes
- Index consistent with Graph_0 dependency_hash values

---

### TASK Q-018 — Implement Previous Hash Snapshot for Delta Comparison

**Description:**
Store a snapshot of all `dependency_hash` values at the end of each build/delta for comparison during the next delta.

**Reasoning:**
Delta needs to compare "old dependency_hash" vs "new dependency_hash" to determine what actually changed. The snapshot provides the "old" values.

**Implementation Steps:**
1. Implement `save_hash_snapshot(hashes: dict[str, str], project_root)` in `codegraph/cas.py`
2. Write to `.codegraph/cas/hash_snapshot.json`
3. Include metadata: graph_version, timestamp, node_count
4. Implement `load_hash_snapshot(project_root) -> Optional[dict[str, str]]`
5. Missing snapshot → return None (trigger full recomputation)
6. Snapshot is updated atomically at end of successful build/delta

**Files:**
- `codegraph/cas.py` (modify)

**Dependencies:** Q-005, A-013

**Edge Cases:**
- First build → no previous snapshot → compute all from scratch
- Snapshot corrupt → log warning, fall back to full recomputation
- Snapshot version mismatch → discard and recompute

**Validation:**
- Snapshot round-trips correctly
- Missing snapshot triggers full computation
- Snapshot updated after successful delta

---

### TASK Q-019 — Implement CAS Hash Cache for Build Performance

**Description:**
Cache computed `dependency_hash` values in memory during build to avoid redundant hash computations.

**Reasoning:**
During topological traversal, a node's hash is computed once and then used by all its callers. An in-memory cache ensures each hash is computed exactly once, even for nodes with many dependents.

**Implementation Steps:**
1. Implement `CASCache` class in `codegraph/cas.py`
2. Dictionary-based cache: `{node_id: dependency_hash}`
3. `get(node_id) -> Optional[str]` — return cached hash
4. `set(node_id, hash)` — store computed hash
5. `invalidate(node_id)` — remove from cache (used during delta)
6. `invalidate_set(node_ids)` — bulk invalidation
7. Pre-populate from snapshot for delta runs

**Files:**
- `codegraph/cas.py` (modify)

**Dependencies:** Q-005, Q-018

**Edge Cases:**
- Cache miss → compute and store
- Cache invalidation during delta → remove affected nodes, keep unaffected
- Memory for 100k nodes → ~50MB (acceptable)

**Validation:**
- Each hash computed exactly once during full build (counter)
- Cache pre-populated from snapshot reduces delta computation
- Memory usage bounded

---

## Phase 6 — Verification & Debugging

---

### TASK Q-020 — Implement CAS Consistency Verification

**Description:**
Verify that all stored `dependency_hash` values are correct by full recomputation and comparison.

**Reasoning:**
CAS correctness is critical — incorrect hashes lead to missed invalidations. A verification tool recomputes all hashes from scratch and compares with stored values.

**Implementation Steps:**
1. Implement `verify_cas_integrity(graph0: Graph0, workflow: Workflow) -> CASVerificationResult` in `codegraph/cas.py`
2. Recompute all dependency_hashes from scratch (ignore stored values)
3. Compare each recomputed hash with stored hash
4. Report mismatches: `{node_id: (stored_hash, computed_hash)}`
5. Add CLI command: `codegraph validate --cas`
6. Return pass/fail status

**Files:**
- `codegraph/cas.py` (modify)

**Dependencies:** Q-005, Q-001

**Edge Cases:**
- All hashes match → pass
- Single mismatch → fail with details
- Missing dependency_hash (None) → report as "not computed"
- Graph_0 modified manually → mismatches expected

**Validation:**
- Clean build passes verification
- Manually corrupted hash detected
- Performance < 5s for 10k nodes

---

### TASK Q-021 — Implement CAS Explain Enhancement

**Description:**
Enhance the `codegraph explain` command to show CAS-specific information for a node: its dependency_hash, the dependency chain, and what would be invalidated if it changed.

**Reasoning:**
Developers and agents need to understand the dependency hash structure to reason about change impact. The explain command is the natural place for this.

**Implementation Steps:**
1. Add CAS section to `ExplainResult` model:
   - `dependency_hash: str`
   - `dependency_chain: list[str]` — callees contributing to the hash
   - `dependent_count: int` — how many nodes depend on this one transitively
   - `would_invalidate: list[str]` — top N nodes that would be affected if this changes
2. Implement `explain_cas(node_id, graph0, workflow, reverse_map) -> CASExplainSection`
3. Show in explain output under "## Content Address" section

**Files:**
- `codegraph/cas.py` (modify)
- `codegraph/models/explain.py` (modify)

**Dependencies:** Q-006, Q-001, B-014

**Edge Cases:**
- Node with no callees → dependency_chain is empty
- Node with no dependents → would_invalidate is empty
- Very large invalidation set → show top 20 + count

**Validation:**
- Explain shows correct dependency_hash
- Dependency chain lists all direct callees
- Would_invalidate count matches propagation result

---

### TASK Q-022 — Implement CAS Delta Statistics Reporter

**Description:**
Add CAS-specific statistics to the delta output: propagation factor, nodes skipped, hash recomputations, cache hit rate.

**Reasoning:**
CAS effectiveness should be measurable. Statistics show how much work CAS saved compared to file-level delta.

**Implementation Steps:**
1. Define `CASStatistics` dataclass:
   - `body_changed_nodes: int`
   - `affected_nodes: int` (after propagation)
   - `propagation_factor: float` (affected / changed)
   - `nodes_skipped: int` (total - affected)
   - `skip_percentage: float` (skipped / total × 100)
   - `hash_recomputations: int`
   - `cache_hits: int`
   - `cache_hit_rate: float`
   - `scc_count: int` (number of cycles found)
2. Collect statistics during CAS delta pipeline
3. Include in DeltaResult output
4. Display in delta CLI output

**Files:**
- `codegraph/cas.py` (modify)
- `codegraph/models/delta.py` (modify)

**Dependencies:** Q-010, K-011, K-020

**Edge Cases:**
- Zero changes → all statistics are 0
- All nodes affected → skip_percentage = 0%, propagation_factor = high
- No cycles → scc_count = 0

**Validation:**
- Statistics are accurate (manually verified on sample project)
- Propagation factor matches manual count
- Display is readable

---

### TASK Q-023 — Implement CAS Hash Export for External Tools

**Description:**
Export the full CAS hash tree as JSON for consumption by external build systems, CI pipelines, or visualization tools.

**Reasoning:**
External tools (Bazel, custom CI) may want to consume codegraph's dependency hashes for their own invalidation logic. A clean export format enables integration.

**Implementation Steps:**
1. Implement `export_cas_tree(graph0: Graph0, workflow: Workflow) -> dict` in `codegraph/cas.py`
2. Output format:
   ```json
   {
     "format": "codegraph_cas_v1",
     "graph_version": 42,
     "nodes": {
       "node_id": {
         "body_hash": "abc...",
         "dependency_hash": "def...",
         "callees": ["callee_1", "callee_2"],
         "dependent_count": 15
       }
     }
   }
   ```
3. Add CLI command: `codegraph cas export [--format json|dot]`
4. Optional DOT format for Graphviz visualization of the hash tree

**Files:**
- `codegraph/cas.py` (modify)

**Dependencies:** Q-005, Q-006

**Edge Cases:**
- Very large graph → stream JSON if needed
- DOT format with 10k nodes → warn about visualization limits
- External tool integration → document format versioning

**Validation:**
- Export is valid JSON
- All nodes and their hashes included
- DOT output renders in Graphviz

---

## Phase 7 — Testing & Validation

---

### TASK Q-024 — Implement Unit Tests for Dependency Hash Computation

**Description:**
Comprehensive unit tests for the core hash computation algorithm.

**Reasoning:**
The hash computation is the foundation of CAS. Correctness must be verified exhaustively.

**Implementation Steps:**
1. Create `tests/test_cas.py`
2. Test cases:
   - Leaf node: `dep_hash == hash(body_hash)`
   - Single callee: `dep_hash == hash(body_hash + callee_dep_hash)`
   - Multiple callees: order-independent (sorted)
   - Empty callee list → same as leaf
   - None callee hash → fallback to body_hash
   - Determinism: same inputs → same output (100 iterations)
3. Property-based tests:
   - Changing body_hash always changes dependency_hash
   - Changing any callee hash always changes dependency_hash
   - Hash is a fixed-length hex string

**Files:**
- `tests/test_cas.py`

**Dependencies:** Q-002

**Validation:**
- All test cases pass
- Property-based tests pass (100+ samples)
- 100% branch coverage of hash computation function

---

### TASK Q-025 — Implement Unit Tests for Topological Sort and SCC Detection

**Description:**
Test topological sort and cycle detection on various graph shapes.

**Reasoning:**
Correct topological ordering is essential for bottom-up hash computation. Wrong order = wrong hashes.

**Implementation Steps:**
1. Test cases in `tests/test_cas.py`:
   - Linear chain: A→B→C → order: [C, B, A]
   - Diamond: A→B, A→C, B→D, C→D → order starts with D
   - Self-loop: A→A → SCC of {A}
   - Mutual recursion: A↔B → SCC of {A, B}
   - Large cycle: A→B→C→D→A → SCC of {A, B, C, D}
   - Disconnected: {A→B} and {C→D} → two independent chains
   - Empty graph → empty sort
   - Single node → [node]

**Files:**
- `tests/test_cas.py` (modify)

**Dependencies:** Q-003, Q-004

**Validation:**
- All graph shapes produce correct topological order
- SCCs correctly identified
- All nodes present in output

---

### TASK Q-026 — Implement Unit Tests for Hash Invalidation Propagation

**Description:**
Test that invalidation propagation correctly identifies all affected nodes.

**Reasoning:**
Over-propagation wastes work; under-propagation misses changes. Both must be caught by tests.

**Implementation Steps:**
1. Test cases in `tests/test_cas.py`:
   - Linear chain A→B→C, C changes → affected = {A, B, C}
   - Diamond A→B, A→C, B→D, C→D, D changes → affected = {A, B, C, D}
   - Isolated change: A and B→C, A changes → affected = {A} only
   - Deep chain (10 levels), leaf changes → all 10 affected
   - Two independent changes → union of affected sets
   - Change in cycle member → all SCC members + their callers affected
2. Verify no false negatives (missed nodes)
3. Verify minimal false positives (extra nodes)

**Files:**
- `tests/test_cas.py` (modify)

**Dependencies:** Q-007

**Validation:**
- All test cases pass
- No under-propagation (missed affected nodes)
- Propagation is precise (no unnecessary nodes)

---

### TASK Q-027 — Implement Integration Tests for CAS-Enhanced Delta

**Description:**
End-to-end tests that verify the full CAS delta pipeline produces identical results to full rebuild.

**Reasoning:**
The critical correctness property: `full_rebuild(after_change) == delta_with_cas(before, after_change)`. If this invariant holds, CAS is correct.

**Implementation Steps:**
1. Create `tests/test_cas_integration.py`
2. Test scenario:
   a. Build full graph on sample project (get all dependency_hashes)
   b. Modify one function (change body)
   c. Run CAS delta
   d. Run full rebuild
   e. Assert: all dependency_hashes match between CAS delta and full rebuild
3. Test scenarios:
   - Leaf function change
   - Mid-chain function change
   - Entry point function change
   - New function added
   - Function deleted
   - Function renamed (file rename)
   - Multiple simultaneous changes
   - Change in cyclic dependency

**Files:**
- `tests/test_cas_integration.py`

**Dependencies:** Q-010, O-002

**Edge Cases:**
- All scenarios must verify hash-for-hash equality with full rebuild

**Validation:**
- All integration tests pass
- CAS delta == full rebuild for every scenario
- No regressions in existing delta tests

---

### TASK Q-028 — Implement CAS Performance Benchmarks

**Description:**
Benchmark CAS delta vs file-level delta to measure the speedup and validate the "10× more precise" claim.

**Reasoning:**
CAS's value proposition is precision and speed. Benchmarks prove it quantitatively.

**Implementation Steps:**
1. Create `benchmarks/cas_benchmark.py`
2. Generate synthetic graphs: 1k, 5k, 10k, 50k nodes
3. Benchmark scenarios:
   - Single leaf change: CAS delta vs file-level delta
   - 10% of nodes changed: CAS vs file-level
   - Core library function change (wide propagation)
   - Change in file with 100 functions (CAS only re-hashes changed function)
4. Measure: wall time, nodes processed, edges recomputed, index updates
5. Report speedup factor: `file_level_time / cas_time`
6. Report precision factor: `file_level_affected / cas_affected`

**Files:**
- `benchmarks/cas_benchmark.py`

**Dependencies:** Q-010, K-001, O-002

**Validation:**
- CAS is faster for single-node changes (target: ≥3× speedup at 10k nodes)
- CAS processes fewer nodes (target: ≥5× fewer at 10k nodes)
- CAS results are correct (match full rebuild)

---

### TASK Q-029 — Implement CAS Hash Stability Across Python Versions

**Description:**
Ensure dependency_hash computation produces identical results across Python 3.9, 3.10, 3.11, 3.12, and 3.13.

**Reasoning:**
If hash computation differs across Python versions, graphs built on one version would be invalidated entirely when opened on another. This breaks CI workflows using different Python versions.

**Implementation Steps:**
1. Add cross-version hash test to `tests/test_cas.py`
2. Hardcode expected hash values for known inputs
3. Verify `hashlib.sha256` produces same output (this should always be true)
4. Verify `ast.dump` normalization (body_hash) is stable across versions
5. If Python AST representation changes between versions → document and handle
6. Add CI matrix testing for Python 3.9-3.13

**Files:**
- `tests/test_cas.py` (modify)

**Dependencies:** Q-002, C-010

**Edge Cases:**
- ast.dump output differs slightly between 3.9 and 3.12 → body_hash may differ
- hashlib is stable (SHA256 is SHA256)
- Sort order for callee hashes is locale-independent (lexicographic on hex strings)

**Validation:**
- Hardcoded hash values match across all supported Python versions
- CI matrix with 3.9, 3.10, 3.11, 3.12, 3.13

---

## Phase 8 — Advanced Features

---

### TASK Q-030 — Implement Partial Graph Rehash Optimization

**Description:**
Optimize CAS for the common case where only a few nodes change, avoiding full topological sort of the entire graph.

**Reasoning:**
Full topological sort is O(V+E). For delta with 1-5 changed nodes, we only need to sort the affected subgraph. This reduces overhead for the most common case.

**Implementation Steps:**
1. Implement `partial_topological_sort(affected: set[str], workflow: Workflow) -> list[str]` in `codegraph/cas.py`
2. Build subgraph containing only affected nodes and their internal edges
3. Topological sort the subgraph only
4. Use cached hashes for callees outside the affected set
5. Threshold: if affected > 30% of total, fall back to full sort

**Files:**
- `codegraph/cas.py` (modify)

**Dependencies:** Q-003, Q-008

**Edge Cases:**
- All affected nodes are leaves → no sorting needed, compute in any order
- Affected subgraph contains cycle → SCC within subgraph
- Threshold exceeded → fall back to full topological sort

**Validation:**
- Partial sort produces same hashes as full sort for affected nodes
- Performance: faster than full sort for small affected sets
- Threshold fallback works correctly

---

### TASK Q-031 — Implement CAS Diff Between Versions

**Description:**
Compare dependency_hash snapshots between two graph versions to show exactly what changed structurally.

**Reasoning:**
`codegraph diff` currently shows node additions/removals. With CAS, it can also show "which nodes' transitive dependencies changed" — a much richer diff.

**Implementation Steps:**
1. Implement `diff_cas_snapshots(old: dict[str, str], new: dict[str, str]) -> CASDiff` in `codegraph/cas.py`
2. Categories:
   - `body_and_dep_changed`: both body_hash and dependency_hash changed (direct edit)
   - `dep_only_changed`: body_hash unchanged but dependency_hash changed (transitive impact)
   - `unchanged`: neither hash changed
   - `added`: new node
   - `removed`: deleted node
3. Add to `codegraph diff` output as "CAS Change Summary" section

**Files:**
- `codegraph/cas.py` (modify)
- `codegraph/models/diff.py` (modify)

**Dependencies:** Q-018, B-015

**Edge Cases:**
- No changes → all unchanged
- First build → all "added"
- Snapshot missing → can't diff, show warning

**Validation:**
- All categories correctly classified
- Counts match manual inspection
- Integrates with existing diff output

---

### TASK Q-032 — Implement CAS-Aware Agent Context Minimization

**Description:**
Use CAS affected set to minimize the context sent to agents, including only the subgraph relevant to the change.

**Reasoning:**
Agents work better with focused context. Instead of sending the entire graph, send only the CAS-affected subgraph: the changed nodes, their callers, their callees, and the propagation chain.

**Implementation Steps:**
1. Implement `extract_agent_context(affected: set[str], graph0, graph1, workflow) -> AgentContext` in `codegraph/cas.py`
2. Include in context:
   - All affected nodes with body, intent, layer
   - Edges between affected nodes
   - Boundary nodes: unaffected nodes that are direct callers/callees of affected nodes (with their intents, but not bodies)
   - Propagation chain: which node triggered which
3. Exclude: all unaffected nodes and edges
4. Format as minimal JSON document for agent consumption
5. Include in tasks.json `pre_fetched_context` when CAS is available

**Files:**
- `codegraph/cas.py` (modify)

**Dependencies:** Q-007, I-008

**Edge Cases:**
- Very large affected set → include all (don't truncate)
- Affected set is empty → no context
- Boundary context gives agent enough info without full graph

**Validation:**
- Context includes all affected nodes
- Context excludes unaffected nodes
- Agent can resolve all task references from context alone

---

### TASK Q-033 — Implement CAS Graph Visualization

**Description:**
Generate a visual representation of the CAS dependency tree showing hash propagation paths.

**Reasoning:**
Visualization helps developers understand the CAS structure and diagnose unexpected propagation. A DOT or Mermaid diagram shows which nodes would be affected by any given change.

**Implementation Steps:**
1. Implement `visualize_cas(graph0, workflow, highlight_nodes=None) -> str` in `codegraph/cas.py`
2. Output formats:
   - DOT (Graphviz): nodes colored by hash age, edges showing hash flow
   - Mermaid: browser-renderable diagram
   - ASCII: simplified tree view for terminal
3. Color coding:
   - Green: recently computed (fresh)
   - Yellow: transitively affected (stale)
   - Red: body changed (directly stale)
4. Highlight mode: given a set of changed nodes, color the propagation path

**Files:**
- `codegraph/cas.py` (modify)

**Dependencies:** Q-006, Q-007

**Edge Cases:**
- Very large graph → only show subgraph around highlighted nodes
- Cycles → show as grouped cluster
- Disconnected subgraphs → separate diagrams

**Validation:**
- DOT output renders in Graphviz
- Mermaid output renders in GitHub markdown
- Highlight correctly shows propagation path

---

### TASK Q-034 — Implement CAS-Aware Convergence Tracking

**Description:**
Enhance convergence tracking to use CAS metrics: track the affected set size across repair iterations instead of just orphan/edge counts.

**Reasoning:**
CAS provides a more precise convergence signal. If the affected set shrinks each iteration, the system is converging. If it grows or stays the same, something is wrong.

**Implementation Steps:**
1. Add CAS fields to `ConvergenceState` model:
   - `affected_set_history: list[int]` — affected set size per iteration
   - `propagation_factor_history: list[float]`
   - `unique_body_changes_history: list[int]`
2. New stopping condition: affected_set_size ≤ 0 for 2 consecutive iterations
3. New warning: propagation_factor increasing across iterations (cascading damage)
4. Integrate into repair loop orchestrator (I-028)

**Files:**
- `codegraph/models/convergence.py` (modify)
- `codegraph/cas.py` (modify)

**Dependencies:** Q-022, B-031, I-028

**Edge Cases:**
- First iteration → no history, don't stop
- Affected set oscillates → warn but don't stop
- Propagation factor > 10 → warn "cascade detected"

**Validation:**
- Convergence detected when affected set reaches 0
- Warning triggered on increasing propagation factor
- History tracked accurately

---

### TASK Q-035 — Implement CAS Migration from Pre-CAS Graphs

**Description:**
Handle upgrading existing codegraph projects that were built before CAS was added.

**Reasoning:**
Existing projects will have Graph_0 files without `dependency_hash` fields. The system must detect this and compute hashes on first CAS-aware build or delta.

**Implementation Steps:**
1. Implement `migrate_to_cas(graph0: Graph0, workflow: Workflow) -> Graph0` in `codegraph/cas.py`
2. Detect: if any node has `dependency_hash == None` → migration needed
3. Compute all dependency_hashes from scratch (full build)
4. Save updated Graph_0 with dependency_hashes
5. Create initial hash snapshot
6. Log: "Migrated N nodes to content-addressed graph"
7. Migration is automatic — no user action needed

**Files:**
- `codegraph/cas.py` (modify)

**Dependencies:** Q-005, Q-018

**Edge Cases:**
- Partial migration (some nodes have hashes, some don't) → recompute all
- Very large pre-CAS graph (50k nodes) → migration may take 10+ seconds, show progress
- Migration during delta → compute hashes, then proceed with normal delta

**Validation:**
- Pre-CAS graph0.json → loads correctly with None dependency_hashes
- Migration computes all hashes
- Post-migration delta works correctly
- Graph_0 file updated with dependency_hashes

---

### TASK Q-036 — Implement CAS Configuration Options

**Description:**
Add configuration options for CAS behavior: enable/disable, hash algorithm selection, propagation depth limit, and fallback threshold.

**Reasoning:**
Projects may want to tune CAS behavior or disable it for debugging. Configuration keeps the system flexible.

**Implementation Steps:**
1. Add CAS section to `config.yaml`:
   ```yaml
   cas:
     enabled: true
     hash_algorithm: sha256  # sha256, blake2b, xxhash
     max_propagation_depth: null  # null = unlimited
     full_rebuild_threshold: 0.5  # switch to full rebuild if >50% affected
     cache_snapshot: true
     verify_on_build: false  # run verification after build
   ```
2. Parse in config loader (A-009)
3. Pass CAS config to all CAS functions
4. Respect `enabled: false` to completely bypass CAS
5. Alternative hash algorithms for performance (blake2b is 2× faster than SHA256)

**Files:**
- `codegraph/cas.py` (modify)
- `codegraph/config.py` (modify if exists)

**Dependencies:** Q-005, A-009

**Edge Cases:**
- CAS disabled → fall back to file-level delta (existing behavior)
- Unknown hash algorithm → error with list of valid options
- Threshold = 0 → always full rebuild (CAS disabled effectively)
- Threshold = 1.0 → never fall back

**Validation:**
- Config parsed correctly
- `enabled: false` bypasses all CAS logic
- Hash algorithm selection works
- Threshold trigger tested

---

### TASK Q-037 — Implement CAS-Aware `codegraph build` Integration

**Description:**
Integrate CAS dependency hash computation into the full `codegraph build` command pipeline.

**Reasoning:**
After `codegraph build` creates Graph_0, workflow, and index, it must also compute and store all dependency_hashes. This establishes the CAS baseline for future deltas.

**Implementation Steps:**
1. Add CAS step to `codegraph build` pipeline (after workflow build, before index):
   a. Compute all dependency_hashes (Q-005)
   b. Store hashes in Graph_0 nodes (Q-001)
   c. Build dependency_hash index table (Q-017)
   d. Save hash snapshot (Q-018)
2. Display CAS statistics in build summary:
   - "Computed dependency hashes for N nodes"
   - "Found M strongly connected components"
   - Build time for CAS step
3. Skip if CAS disabled in config

**Files:**
- `codegraph/cli.py` (modify)
- `codegraph/delta.py` (modify)

**Dependencies:** Q-005, Q-017, Q-018, Q-036, N-002

**Edge Cases:**
- Build with `--no-cas` flag → skip CAS computation
- Very large graph (50k nodes) → show progress bar for CAS step
- CAS computation fails → log error, continue without CAS (non-fatal)

**Validation:**
- Build command completes with CAS step
- All nodes have dependency_hash after build
- Hash snapshot saved
- CAS statistics displayed

---

### TASK Q-038 — Implement CAS CLI Command: `codegraph cas`

**Description:**
Add a `codegraph cas` command group with subcommands for CAS management: verify, export, stats, explain.

**Reasoning:**
CAS is a significant subsystem that deserves its own command group for inspection and debugging.

**Implementation Steps:**
1. Add `@cli.group() cas` to `codegraph/cli.py`
2. Subcommands:
   - `codegraph cas verify` — run CAS consistency verification (Q-020)
   - `codegraph cas export [--format json|dot]` — export CAS tree (Q-023)
   - `codegraph cas stats` — show CAS statistics (Q-022)
   - `codegraph cas diff <version1> <version2>` — diff CAS snapshots (Q-031)
   - `codegraph cas impact <node_id>` — show what would be affected if node changes (Q-021)
3. All subcommands support `--json` output

**Files:**
- `codegraph/cli.py` (modify)

**Dependencies:** Q-020, Q-021, Q-022, Q-023, Q-031, N-001

**Edge Cases:**
- CAS not yet computed (no dependency_hashes) → helpful error: "Run `codegraph build` first"
- CAS disabled in config → error: "CAS is disabled in config.yaml"

**Validation:**
- All subcommands work
- `--json` output valid
- Help text describes CAS purpose

---

### TASK Q-039 — Write CAS Documentation

**Description:**
Document the Content Addressed Graph system: concept, usage, configuration, and integration with existing commands.

**Reasoning:**
CAS is a novel concept for most users. Clear documentation explains the mental model and helps users leverage CAS effectively.

**Implementation Steps:**
1. Create `docs/cas-graph.md` with sections:
   - **Concept**: What is content addressing? How does it work?
   - **How It Works**: Hash computation, propagation, invalidation
   - **Benefits**: Faster delta, precise test impact, minimal agent context
   - **Configuration**: config.yaml options
   - **CLI Commands**: codegraph cas subcommands
   - **Comparison**: Before CAS vs After CAS (with diagrams)
   - **FAQ**: Common questions and misconceptions
2. Include diagrams (Mermaid) showing hash propagation
3. Include a worked example: single function change → propagation → affected set

**Files:**
- `docs/cas-graph.md`

**Dependencies:** Q-036, Q-038

**Validation:**
- Documentation is accurate and matches implementation
- Diagrams render correctly
- Example matches actual behavior

---

### TASK Q-040 — Implement CAS Failure Mode Handling

**Description:**
Define and handle all CAS-specific failure modes gracefully.

**Reasoning:**
CAS adds new failure modes to the system. Each must be handled without breaking the existing pipeline.

**Implementation Steps:**
1. Define failure modes and their handlers:
   - **cas_hash_mismatch**: Stored dependency_hash doesn't match recomputed → log warning, recompute
   - **cas_snapshot_corrupt**: Hash snapshot file is corrupt → discard, full recomputation
   - **cas_cycle_explosion**: SCC larger than configurable threshold (default 100) → log warning, use body_hash only for SCC members
   - **cas_propagation_overflow**: Affected set > threshold → fall back to full rebuild
   - **cas_migration_needed**: Pre-CAS graph detected → auto-migrate
   - **cas_disabled_but_requested**: CAS command used but CAS disabled → helpful error
2. Log all failure modes with structured logging
3. None of these failures should stop the build/delta

**Files:**
- `codegraph/cas.py` (modify)

**Dependencies:** Q-020, Q-035, Q-036

**Edge Cases:**
- Multiple failure modes triggered simultaneously → handle each independently
- Failure during delta → fall back to file-level delta, log CAS failure

**Validation:**
- Each failure mode handled gracefully (no crash)
- Fallback to non-CAS behavior works
- Structured logging captures failure details
