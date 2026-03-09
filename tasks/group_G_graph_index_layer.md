# Group G — Graph Index Layer

> Index building, storage, incremental updates, query acceleration, and index rebuild via `index.py`.

---

### TASK G-001 — Design Index Storage Backend

**Description:**
Choose and implement the storage backend for graph indexes (`.db` files).

**Reasoning:**
The README specifies index files as `.db`. SQLite is the natural choice for Python — zero-dependency, fast, supports concurrent reads.

**Implementation Steps:**
1. Create `codegraph/index.py`
2. Choose SQLite as the backend (stdlib `sqlite3`)
3. Define database-per-index approach (nodes.db, callers.db, etc.)
4. Implement connection management with proper cleanup
5. Set WAL mode for concurrent read performance

**Files:**
- `codegraph/index.py`

**Dependencies:** A-005

**Research Notes:**
- SQLite WAL mode allows concurrent readers with one writer
- For 10k+ nodes and 50k+ edges, SQLite is well within performance limits
- Alternative: simple dict-based JSON cache for smaller repos

**Validation:**
- Database files created in `.codegraph/index/`
- Connections open and close properly
- WAL mode enabled

---

### TASK G-002 — Implement Nodes Index Table

**Description:**
Create the `nodes.db` index that maps `node_id → metadata`.

**Reasoning:**
Used by `explain` and `intent-missing` commands for O(1) node lookup.

**Implementation Steps:**
1. Create nodes table: `CREATE TABLE nodes (id TEXT PRIMARY KEY, file TEXT, type TEXT, line INTEGER, body_hash TEXT, layer INTEGER)`
2. Implement `build_nodes_index(graph0: Graph0, graph1: Graph1)`
3. Implement `query_node(node_id) -> dict`
4. Implement `query_nodes_by_file(file) -> list[dict]`

**Files:**
- `codegraph/index.py` (modify)

**Dependencies:** G-001, B-002, B-004

**Validation:**
- Node lookup by ID is O(1)
- All Graph_0 nodes indexed
- Layer info from Graph_1 included

---

### TASK G-003 — Implement Callers Index Table

**Description:**
Create the `callers.db` index that maps `node_id → [caller_ids]` (reverse call graph).

**Reasoning:**
Used by `callers()` query and orphan detection. Finding all callers of a node must be O(1).

**Implementation Steps:**
1. Create callers table: `CREATE TABLE callers (node_id TEXT, caller_id TEXT, edge_type TEXT, confidence TEXT)`
2. Add index on `node_id`
3. Implement `build_callers_index(workflow: Workflow)`
4. Implement `get_callers(node_id) -> list[str]`

**Files:**
- `codegraph/index.py` (modify)

**Dependencies:** G-001, B-006

**Validation:**
- Callers lookup is O(1) via index
- All incoming edges indexed
- Multiple callers returned correctly

---

### TASK G-004 — Implement Callees Index Table

**Description:**
Create the `callees.db` index that maps `node_id → [callee_ids]` (forward call graph).

**Reasoning:**
Used by `callees()` query and policy diff. Finding what a node calls must be O(1).

**Implementation Steps:**
1. Create callees table: `CREATE TABLE callees (node_id TEXT, callee_id TEXT, edge_type TEXT, confidence TEXT)`
2. Add index on `node_id`
3. Implement `build_callees_index(workflow: Workflow)`
4. Implement `get_callees(node_id) -> list[str]`

**Files:**
- `codegraph/index.py` (modify)

**Dependencies:** G-001, B-006

**Validation:**
- Callees lookup is O(1) via index
- All outgoing edges indexed

---

### TASK G-005 — Implement Layers Index Table

**Description:**
Create the `layers.db` index that maps `layer → [node_ids]`.

**Reasoning:**
Used by `layer()` query and layer violation checks.

**Implementation Steps:**
1. Create layers table: `CREATE TABLE layers (layer INTEGER, node_id TEXT)`
2. Add index on `layer`
3. Implement `build_layers_index(graph1: Graph1)`
4. Implement `get_nodes_at_layer(layer: int) -> list[str]`

**Files:**
- `codegraph/index.py` (modify)

**Dependencies:** G-001, B-004

**Validation:**
- Layer query returns correct nodes
- All layers populated

---

### TASK G-006 — Implement Tests Index Table

**Description:**
Create the `tests.db` index that maps `test_id ↔ node_id` for test impact analysis.

**Reasoning:**
Used by test impact analysis and coverage gap detection. Bidirectional lookup required.

**Implementation Steps:**
1. Create tests table: `CREATE TABLE tests (test_id TEXT, node_id TEXT)`
2. Add indexes on both `test_id` and `node_id`
3. Implement `build_tests_index(workflow: Workflow, graph0: Graph0)`
4. Implement `get_tests_for_node(node_id) -> list[str]`
5. Implement `get_nodes_for_test(test_id) -> list[str]`

**Files:**
- `codegraph/index.py` (modify)

**Dependencies:** G-001, B-006, D-005

**Edge Cases:**
- Function with no test coverage → empty list
- Test calling many functions → multiple entries
- Indirect test coverage (through call chain)

**Validation:**
- Bidirectional lookup works
- Coverage gap detection uses this index

---

### TASK G-007 — Implement Full Index Build Orchestrator

**Description:**
Create the top-level function that builds all five index tables from graph data.

**Reasoning:**
After `codegraph build`, all indexes must be rebuilt from scratch.

**Implementation Steps:**
1. Implement `build_all_indexes(graph0, graph1, workflow, project_root)`
2. Drop existing index databases
3. Build each index table in sequence
4. Log timing per table
5. Create `.codegraph/index/` directory if not exists

**Files:**
- `codegraph/index.py` (modify)

**Dependencies:** G-002 through G-006

**Validation:**
- All five .db files created
- Index data matches graph data
- Build completes without error

---

### TASK G-008 — Implement Delta Index Update

**Description:**
Implement incremental index updates after `codegraph delta`, updating only affected entries.

**Reasoning:**
README states delta mode only updates affected index entries: "Remove old outgoing and incoming edges from callers.db and callees.db, insert new edges, update nodes.db."

**Implementation Steps:**
1. Implement `update_index_delta(delta: DeltaResult, graph0, graph1, workflow, project_root)`
2. For modified/removed nodes:
   - Delete entries from all index tables
   - For callers/callees: remove both directions
3. For added/modified nodes:
   - Insert new entries
4. Don't rebuild unchanged entries

**Files:**
- `codegraph/index.py` (modify)

**Dependencies:** G-007, B-012

**Edge Cases:**
- Node renamed (old removed, new added) — treat as remove+add
- Edge target changed — update both callers and callees
- Index inconsistency after partial update → rollback

**Validation:**
- Delta update produces same result as full rebuild for affected nodes
- Unchanged entries untouched
- Performance faster than full rebuild

---

### TASK G-009 — Implement Index Rebuild Command

**Description:**
Implement `codegraph index rebuild` that rebuilds the index from committed graph files without re-extraction.

**Reasoning:**
README states: "If the index becomes inconsistent (e.g. after a manual git operation), rebuild it."

**Implementation Steps:**
1. Load existing graph0.json, graph1.json, workflow.json from disk
2. Delete all existing index databases
3. Rebuild all indexes from the loaded data
4. No AST extraction — just index regeneration
5. Log timing and result

**Files:**
- `codegraph/index.py` (modify)

**Dependencies:** G-007, C-030, E-014, F-019

**Validation:**
- Rebuilt index is identical to freshly built index
- No AST extraction performed
- Works even if previous indexes are corrupt/missing

---

### TASK G-010 — Implement Index Consistency Check

**Description:**
Verify that index data matches the current graph files.

**Reasoning:**
Inconsistent indexes can cause incorrect query results and analysis. A consistency check helps diagnose issues.

**Implementation Steps:**
1. Implement `check_index_consistency(project_root) -> list[ConsistencyIssue]`
2. Load graph files and index databases
3. Compare:
   - Every Graph_0 node has a nodes.db entry
   - Every workflow edge has callers/callees entries
   - Layer assignments match
4. Report mismatches

**Files:**
- `codegraph/index.py` (modify)

**Dependencies:** G-007

**Validation:**
- Consistent indexes pass check
- Missing entries detected
- Extra entries detected

---

### TASK G-011 — Implement Index Query Interface

**Description:**
Create a high-level query interface that abstracts the underlying index tables.

**Reasoning:**
Other modules (query.py, analyzer.py, tasks.py) should not directly interact with SQLite. A clean interface isolates them from storage details.

**Implementation Steps:**
1. Implement `IndexStore` class in `codegraph/index.py`:
   - `get_node(node_id) -> dict`
   - `get_callers(node_id) -> list[str]`
   - `get_callees(node_id) -> list[str]`
   - `get_nodes_at_layer(layer) -> list[str]`
   - `get_tests_for_node(node_id) -> list[str]`
   - `get_nodes_for_test(test_id) -> list[str]`
   - `get_all_node_ids() -> list[str]`
   - `get_orphans() -> list[str]`
2. Cache connections for performance
3. Raise clear error if index doesn't exist

**Files:**
- `codegraph/index.py` (modify)

**Dependencies:** G-002 through G-006

**Validation:**
- All query methods return correct data
- Missing index raises clear error
- Connection pooling works

---

### TASK G-012 — Implement Index Node Search

**Description:**
Support searching for nodes by partial name, file, or pattern.

**Reasoning:**
Users and agents need to find nodes by partial identifiers. The index should support pattern matching.

**Implementation Steps:**
1. Add `search_nodes(pattern: str) -> list[str]` to IndexStore
2. Support: exact match, prefix match, glob pattern, file path match
3. Use SQLite LIKE for pattern matching
4. Limit results with configurable cap

**Files:**
- `codegraph/index.py` (modify)

**Dependencies:** G-011

**Edge Cases:**
- Pattern matches thousands of nodes → limit
- No matches → empty list
- Regex-like patterns → use glob, not regex

**Validation:**
- Exact match returns single result
- Prefix match returns multiple results
- Results limited when too many

---

### TASK G-013 — Implement Recursive Dependency Query via Index

**Description:**
Support recursive traversal queries (dependencies, dependents) using the index.

**Reasoning:**
`dependencies(node_id)` must recursively follow all callees. This must be efficient with cycle detection.

**Implementation Steps:**
1. Implement `get_dependencies_recursive(node_id, max_depth=None) -> list[str]`
2. BFS/DFS through callees index
3. Track visited nodes to handle cycles
4. Support depth limiting
5. Return all reachable nodes

**Files:**
- `codegraph/index.py` (modify)

**Dependencies:** G-011

**Edge Cases:**
- Circular dependencies → cycle detection prevents infinite loop
- Very deep dependency tree → depth limit
- Disconnected subgraphs

**Validation:**
- Recursive traversal finds all transitive dependencies
- Cycles handled without infinite loop
- Depth limit respected

---

### TASK G-014 — Implement Shortest Path Query via Index

**Description:**
Implement `path(node_a, node_b)` using BFS on the index.

**Reasoning:**
Finding the shortest path between two nodes is a core query. Must work on the index for O(N) performance.

**Implementation Steps:**
1. Implement `shortest_path(source, target) -> list[str]`
2. BFS from source using callees index
3. Return ordered list of node IDs forming the path
4. Return empty list if no path exists
5. Support `--depth` limit to bound search

**Files:**
- `codegraph/index.py` (modify)

**Dependencies:** G-011

**Edge Cases:**
- No path exists → empty list
- Source == target → return [source]
- Very long path → depth limit
- Multiple shortest paths → return any one

**Validation:**
- Shortest path found between connected nodes
- No path returns empty list
- Depth limit respected

---

### TASK G-015 — Implement Index Performance Benchmarks

**Description:**
Create benchmarks for index operations to ensure they meet O(1) and O(log N) targets.

**Reasoning:**
The index exists specifically for performance. Benchmarks ensure the system meets its performance claims.

**Implementation Steps:**
1. Create `benchmarks/index_benchmark.py`
2. Generate synthetic graphs: 1k, 10k, 100k nodes
3. Benchmark: node lookup, callers query, path query
4. Assert O(1) for direct lookups
5. Assert O(log N) or better for complex queries

**Files:**
- `benchmarks/index_benchmark.py`

**Dependencies:** G-011

**Validation:**
- Direct lookups < 1ms at 100k nodes
- Path queries < 100ms at 10k nodes
- Memory usage < 500MB at 100k nodes

---

### TASK G-016 — Implement Index Database Migrations

**Description:**
Support schema evolution for index databases as the system evolves.

**Reasoning:**
Index schemas may need additional columns or tables. Migrations ensure smooth upgrades without manual index rebuilds.

**Implementation Steps:**
1. Add schema version table to each database
2. Implement migration framework: version check → run migration if needed
3. For now, only migration 0→1 (initial schema)
4. If version mismatch and no migration → full rebuild

**Files:**
- `codegraph/index.py` (modify)

**Dependencies:** G-001

**Validation:**
- Version check works on existing databases
- Missing version table triggers rebuild
- Migration framework runs correctly

---

### TASK G-017 — Implement Index Locking for Concurrent Access

**Description:**
Handle concurrent access to index databases (e.g., running `codegraph status` while `codegraph build` is running).

**Reasoning:**
In development workflows, multiple CLI commands may run simultaneously. SQLite handles this well but needs proper configuration.

**Implementation Steps:**
1. Use SQLite WAL mode (already in G-001)
2. Set proper busy timeout for write operations
3. Read operations should never block
4. Document concurrent access behavior

**Files:**
- `codegraph/index.py` (modify)

**Dependencies:** G-001

**Validation:**
- Concurrent reads succeed
- Write during read works with WAL
- Proper timeout on write contention

---

### TASK G-018 — Implement Index Statistics

**Description:**
Report index size and health statistics.

**Reasoning:**
For debugging and monitoring, users should see index sizes and integrity.

**Implementation Steps:**
1. Implement `index_statistics(project_root) -> IndexStats`
2. Report: file sizes, row counts per table, last build time
3. Include in `codegraph status --verbose` output

**Files:**
- `codegraph/index.py` (modify)

**Dependencies:** G-011

**Validation:**
- Row counts match graph data
- File sizes reported accurately

---

### TASK G-019 — Implement Arch Layer Index

**Description:**
Add index support for `arch_layer` annotations to enable fast arch_layer-scoped rule evaluation.

**Reasoning:**
Suggested workflow rules can scope by arch_layer. Without an index, this requires scanning all Graph_1 nodes.

**Implementation Steps:**
1. Add arch_layer column to nodes table in nodes.db
2. Implement `get_nodes_by_arch_layer(arch_layer: str) -> list[str]`
3. Update build and delta update to include arch_layer

**Files:**
- `codegraph/index.py` (modify)

**Dependencies:** G-002, B-039

**Validation:**
- Arch layer query returns correct nodes
- Works with delta updates

---

### TASK G-020 — Implement Index Export for Debugging

**Description:**
Export index contents as JSON for debugging and inspection.

**Reasoning:**
When indexes seem incorrect, being able to dump their contents helps diagnose issues without SQLite tools.

**Implementation Steps:**
1. Implement `export_index(project_root, table_name=None) -> dict`
2. Dump entire table or all tables as JSON
3. Format for human readability
4. Support CLI command: `codegraph index dump [table]`

**Files:**
- `codegraph/index.py` (modify)

**Dependencies:** G-011

**Validation:**
- Export matches actual database contents
- All tables exportable
- Output is valid JSON

---

### TASK G-021 — Implement Dependency Hash Index Table (CAS Integration)

**Description:**
Add a `dependency_hashes` table to the SQLite index for O(1) dependency_hash lookups, supporting the Content Addressed Graph system.

**Reasoning:**
During CAS delta, the system needs previous dependency_hash values to compare with newly computed hashes. A dedicated index table avoids loading the full Graph_0 JSON. This is the index-layer integration point for Group Q.

**Implementation Steps:**
1. Add table: `CREATE TABLE dependency_hashes (node_id TEXT PRIMARY KEY, dependency_hash TEXT, body_hash TEXT, computed_at TEXT)`
2. Implement `build_dependency_hash_index(cas_results: dict[str, str])` — full build
3. Implement `get_dependency_hash(node_id) -> Optional[str]` — single lookup
4. Implement `get_all_dependency_hashes() -> dict[str, str]` — bulk load for CAS cache pre-population
5. Implement `update_dependency_hashes(changes: dict[str, str])` — delta update for affected nodes only
6. Include in full index build orchestrator (G-007)
7. Include in delta index update (G-008)

**Files:**
- `codegraph/index.py` (modify)

**Dependencies:** G-001, G-007, G-008, Q-005

**Edge Cases:**
- Pre-CAS index (no dependency_hashes table) → create table on first use via migration (G-016)
- Node not in index → return None (new node)
- Bulk load performance for 100k nodes → use efficient SQL batch

**Validation:**
- O(1) single lookup time
- All nodes indexed after build
- Delta update modifies only affected nodes
- Index matches Graph_0 dependency_hash values

---

### TASK G-022 — Add Dependency Hash to Nodes Index Table (CAS Integration)

**Description:**
Add `dependency_hash` column to the existing `nodes` table in `nodes.db` so node queries can return CAS data alongside structural data.

**Reasoning:**
The `explain` command and analysis passes need the dependency_hash alongside other node metadata. Adding it to the existing nodes table avoids a join and keeps queries simple.

**Implementation Steps:**
1. Add column: `ALTER TABLE nodes ADD COLUMN dependency_hash TEXT`
2. Update `build_nodes_index()` to include dependency_hash
3. Update `query_node()` return dict to include dependency_hash
4. Handle migration: if column doesn't exist, add it (G-016)
5. Populate from Graph_0 during build

**Files:**
- `codegraph/index.py` (modify)

**Dependencies:** G-002, G-016, Q-001

**Edge Cases:**
- Pre-CAS index without column → migration adds it
- Node without dependency_hash → NULL in column

**Validation:**
- Node query returns dependency_hash
- Migration adds column without data loss
- Full rebuild populates all values
