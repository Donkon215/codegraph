# Group L — Query System

> Query parser, graph traversal functions, output formatting, depth/limit controls, and CLI integration via `query.py`.

---

### TASK L-001 — Implement Query Parser

**Description:**
Parse the query string syntax: `callers("node_id")`, `callees("node_id")`, etc.

**Reasoning:**
The query system accepts a mini-language. A parser must tokenize and validate query strings.

**Implementation Steps:**
1. Create `codegraph/query.py`
2. Implement `parse_query(query_string: str) -> ParsedQuery`
3. Grammar:
   - `function_name(argument)` where function_name is a query function
   - Arguments are quoted node IDs: `"file::class::function"`
   - Support optional parameters: `callers("node", depth=2)`
4. Return structured ParsedQuery with function name, arguments, and options

**Files:**
- `codegraph/query.py`

**Dependencies:** B-001

**Edge Cases:**
- Unquoted node ID → error with guidance
- Unknown function name → error with list of valid functions
- Nested quotes → handle escaping
- Node ID with special characters → preserve exactly

**Validation:**
- Valid queries parse correctly
- Invalid queries produce helpful errors
- All query functions recognized

---

### TASK L-002 — Implement `callers()` Query Function

**Description:**
Return all nodes that call the target node.

**Reasoning:**
Fundamental query: "who calls this function?" Uses the callers index for O(1) lookup.

**Implementation Steps:**
1. Implement `query_callers(node_id: str, index: IndexStore, depth=1, limit=None) -> QueryResult`
2. For depth=1: direct callers from callers index
3. For depth>1: recursively follow callers up to depth
4. Apply limit to result count
5. Return ordered list of caller node IDs

**Files:**
- `codegraph/query.py` (modify)

**Dependencies:** L-001, G-003

**Edge Cases:**
- No callers (orphan) → empty list
- Recursive call (self-caller) → include
- `depth=0` → invalid, error

**Validation:**
- Direct callers returned for depth=1
- Transitive callers returned for depth>1
- Limit respected

---

### TASK L-003 — Implement `callees()` Query Function

**Description:**
Return all nodes that the target node calls.

**Reasoning:**
Fundamental query: "what does this function call?" Uses the callees index.

**Implementation Steps:**
1. Implement `query_callees(node_id: str, index: IndexStore, depth=1, limit=None) -> QueryResult`
2. For depth=1: direct callees from callees index
3. For depth>1: recursively follow callees
4. Apply limit
5. Return ordered list

**Files:**
- `codegraph/query.py` (modify)

**Dependencies:** L-001, G-004

**Validation:**
- Direct callees returned
- Recursive callees for depth>1
- Limit respected

---

### TASK L-004 — Implement `dependencies()` Query Function

**Description:**
Return all transitive dependencies (callees-of-callees) of a node.

**Reasoning:**
Shows the full dependency tree of a function — everything it transitively depends on.

**Implementation Steps:**
1. Implement `query_dependencies(node_id: str, index: IndexStore, depth=None, limit=None) -> QueryResult`
2. Recursively follow callees index (BFS)
3. Cycle detection to prevent infinite loops
4. Default depth: unlimited (follow until no more callees)
5. Return all reachable nodes

**Files:**
- `codegraph/query.py` (modify)

**Dependencies:** L-001, G-013

**Validation:**
- All transitive dependencies found
- Cycles handled
- Depth limit works

---

### TASK L-005 — Implement `dependents()` Query Function

**Description:**
Return all transitive dependents (callers-of-callers) of a node.

**Reasoning:**
Shows everything that depends on a function — useful for impact analysis.

**Implementation Steps:**
1. Implement `query_dependents(node_id: str, index: IndexStore, depth=None, limit=None) -> QueryResult`
2. Recursively follow callers index (BFS)
3. Cycle detection
4. Default depth: unlimited
5. Return all nodes that transitively depend on the target

**Files:**
- `codegraph/query.py` (modify)

**Dependencies:** L-001, G-013

**Validation:**
- All transitive dependents found
- Cycles handled
- Depth limit works

---

### TASK L-006 — Implement `path()` Query Function

**Description:**
Find the shortest path between two nodes in the call graph.

**Reasoning:**
Shows how two functions are connected — useful for understanding control flow.

**Implementation Steps:**
1. Implement `query_path(source: str, target: str, index: IndexStore, depth=None) -> QueryResult`
2. Use BFS from source through callees
3. Return ordered path of node IDs
4. If no path exists → return empty with message
5. Support depth limit for search bounds

**Files:**
- `codegraph/query.py` (modify)

**Dependencies:** L-001, G-014

**Edge Cases:**
- No path between nodes → clear message
- Source == target → single-node path
- Multiple shortest paths → return any one
- Very long path → depth limit prevents unbounded search

**Validation:**
- Path found between connected nodes
- No path → clear message
- Correct ordering

---

### TASK L-007 — Implement `orphans()` Query Function

**Description:**
Return all orphan nodes (no callers and no callees).

**Reasoning:**
Quick access to orphan nodes for cleanup and analysis.

**Implementation Steps:**
1. Implement `query_orphans(index: IndexStore, layer=None, limit=None) -> QueryResult`
2. Find all nodes with no entries in callers and callees index
3. Optionally filter by layer
4. Apply limit
5. Sort by file path for consistent output

**Files:**
- `codegraph/query.py` (modify)

**Dependencies:** L-001, G-011

**Validation:**
- True orphans returned
- Non-orphans excluded
- Layer filter works

---

### TASK L-008 — Implement `layer()` Query Function

**Description:**
Return all nodes at a specific layer.

**Reasoning:**
Filter nodes by layer for focused analysis.

**Implementation Steps:**
1. Implement `query_layer(layer: int, index: IndexStore, limit=None) -> QueryResult`
2. Query layers index for all nodes at specified layer
3. Apply limit
4. Sort by file path

**Files:**
- `codegraph/query.py` (modify)

**Dependencies:** L-001, G-005

**Validation:**
- Correct nodes returned for each layer
- Invalid layer → error
- Limit respected

---

### TASK L-009 — Implement Query Depth Control

**Description:**
Implement `--depth` flag that limits recursive query traversal depth.

**Reasoning:**
Without depth limits, recursive queries on large graphs can be very expensive.

**Implementation Steps:**
1. Add `depth` parameter to all recursive queries
2. Track traversal depth in BFS/DFS
3. Stop at max depth
4. Default: depth=1 for callers/callees, unlimited for dependencies/dependents
5. CLI flag: `--depth N`

**Files:**
- `codegraph/query.py` (modify)

**Dependencies:** L-002 through L-008

**Validation:**
- Depth=1 returns only direct connections
- Depth=2 returns 2 hops
- Default depths appropriate

---

### TASK L-010 — Implement Query Result Limit

**Description:**
Implement `--limit` flag that caps the number of results returned.

**Reasoning:**
Large queries may return thousands of nodes. Limit keeps output manageable.

**Implementation Steps:**
1. Add `limit` parameter to all query functions
2. After collecting results, truncate to limit
3. Include "N more results not shown" message
4. Default: no limit (show all)

**Files:**
- `codegraph/query.py` (modify)

**Dependencies:** L-002 through L-008

**Validation:**
- Limit caps results
- Truncation message shown
- No limit shows all

---

### TASK L-011 — Implement Query Result Formatter

**Description:**
Format query results for CLI display with multiple output modes.

**Reasoning:**
Query output should be readable for humans and parseable for tools.

**Implementation Steps:**
1. Implement `format_query_result(result: QueryResult, format="text") -> str`
2. Formats:
   - `text`: one node per line, with file path and line number
   - `json`: machine-readable JSON array
   - `tree`: hierarchical tree view (for path/dependency queries)
   - `count`: just the count
3. Include metadata (depth, limit, total count)

**Files:**
- `codegraph/query.py` (modify)

**Dependencies:** L-001

**Validation:**
- Text format readable
- JSON format valid
- Tree format shows hierarchy
- Count format shows single number

---

### TASK L-012 — Implement Node ID Quoting Rules

**Description:**
Implement proper node ID quoting/escaping for the query language.

**Reasoning:**
README states: "Node IDs containing special characters must be quoted with double quotes in queries."

**Implementation Steps:**
1. Define special characters requiring quoting: spaces, colons, dots, etc.
2. In parser: handle quoted `"file::class::function"` and unquoted `simple_name`
3. In output: always show full node ID with proper quoting
4. Escape double quotes within node IDs

**Files:**
- `codegraph/query.py` (modify)

**Dependencies:** L-001

**Validation:**
- Quoted node IDs parsed correctly
- Unquoted simple names work
- Special characters handled

---

### TASK L-013 — Implement Query Execution Engine

**Description:**
Create the unified query execution engine that dispatches parsed queries to the correct function.

**Reasoning:**
Single entry point for all query types, handling common logic (limit, depth, output format).

**Implementation Steps:**
1. Implement `execute_query(query: ParsedQuery, index: IndexStore, options: QueryOptions) -> QueryResult`
2. Dispatch table: function_name → handler
3. Apply common options: depth, limit, output format
4. Time the query for performance reporting
5. Handle errors gracefully

**Files:**
- `codegraph/query.py` (modify)

**Dependencies:** L-001, L-002 through L-008

**Validation:**
- All query types dispatch correctly
- Options applied uniformly
- Timing reported

---

### TASK L-014 — Implement Query Auto-Complete Suggestions

**Description:**
When a query has a typo or partial node ID, suggest the closest matching nodes.

**Reasoning:**
Typing full node IDs is error-prone. Suggestions help users find the right node.

**Implementation Steps:**
1. When a node ID is not found in the index:
   - Search for similar node IDs (Levenshtein distance or prefix match)
   - Return top 5 suggestions
   - Display: "Did you mean: ..."
2. Use index search function from G-012

**Files:**
- `codegraph/query.py` (modify)

**Dependencies:** L-013, G-012

**Validation:**
- Close matches suggested
- Exact matches not triggered
- Suggestions are relevant

---

### TASK L-015 — Implement Boolean Query Composition (Planned)

**Description:**
Implement boolean operators for combining queries: `callers("A") AND callees("B")`.

**Reasoning:**
README mentions this as a planned feature: "boolean composition of queries."

**Implementation Steps:**
1. Extend parser to support: `AND`, `OR`, `NOT`
2. `AND`: intersection of two query results
3. `OR`: union of two query results
4. `NOT`: exclusion
5. Precedence: NOT > AND > OR (or use parentheses)
6. Example: `callers("auth::validate") AND layer(3)`

**Files:**
- `codegraph/query.py` (modify)

**Dependencies:** L-013

**Edge Cases:**
- Empty result in AND → empty
- Nested boolean → parentheses required
- NOT with no positive query → error

**Validation:**
- AND produces intersection
- OR produces union
- NOT excludes correctly

---

### TASK L-016 — Implement `explain` Query Command

**Description:**
Implement `codegraph explain "node_id"` that shows comprehensive information about a node.

**Reasoning:**
README describes explain as showing: source file, line, intent, callers, callees, layer, tests.

**Implementation Steps:**
1. Implement `explain_node(node_id: str, graph0, graph1, index) -> ExplainResult`
2. Gather:
   - File path, line number, node type
   - Intent (from Graph_1)
   - Layer (from Graph_1)
   - Tags (from Graph_1)
   - Callers (from index, first 10)
   - Callees (from index, first 10)
   - Tests (from tests index)
   - Body hash
   - Stale intent flag
3. Format for display

**Files:**
- `codegraph/query.py` (modify)

**Dependencies:** L-013, G-011, B-013

**Validation:**
- All information gathered
- Missing data shown as "none" not error
- Formatted readably

---

### TASK L-017 — Implement Query Caching

**Description:**
Cache query results for repeated identical queries within a session.

**Reasoning:**
Nested queries and batch operations may invoke the same query multiple times. Caching avoids redundant work.

**Implementation Steps:**
1. Implement LRU cache for query results
2. Key: (query_function, node_id, depth, limit)
3. Invalidate on graph_version change
4. Configurable cache size

**Files:**
- `codegraph/query.py` (modify)

**Dependencies:** L-013

**Validation:**
- Cached results returned for repeated queries
- Version change invalidates cache
- Cache size bounded

---

### TASK L-018 — Implement Import Dependency Query

**Description:**
Implement `dependencies()` for module-level import dependencies (separate from call graph).

**Reasoning:**
README states: "Import-level dependencies are stored separately." This query accesses that separate store.

**Implementation Steps:**
1. Implement `query_import_dependencies(module: str, imports_graph) -> QueryResult`
2. Load imports.json from F-031
3. Follow import edges recursively
4. Return list of module dependencies

**Files:**
- `codegraph/query.py` (modify)

**Dependencies:** L-001, F-031

**Validation:**
- Module imports returned
- Transitive imports included
- Circular imports handled

---

### TASK L-019 — Implement Query Performance Monitoring

**Description:**
Track and report query execution times for performance optimization.

**Reasoning:**
Slow queries on large graphs need to be identified and optimized.

**Implementation Steps:**
1. Time all query executions
2. Log queries exceeding threshold (default 100ms)
3. Include timing in `--verbose` output
4. Collect statistics for `codegraph status --verbose`

**Files:**
- `codegraph/query.py` (modify)

**Dependencies:** L-013

**Validation:**
- Timings accurate
- Slow queries logged
- Statistics collected

---

### TASK L-020 — Implement Batch Query Support

**Description:**
Support running multiple queries in a single command for efficiency.

**Reasoning:**
Agents often need to query multiple nodes. Batch support reduces overhead.

**Implementation Steps:**
1. Accept multiple queries: `codegraph query "callers(A)" "callees(B)"`
2. Execute each query
3. Format results with clear separation between queries
4. Share index connection across queries

**Files:**
- `codegraph/query.py` (modify)

**Dependencies:** L-013

**Validation:**
- Multiple queries execute
- Results clearly separated
- Shared connection works
---

### TASK L-021 — Implement Semantic Query Functions

**Description:**
Add semantic query types to the query parser and executor: `effects()`, `actions()`, `guards()`, `domain()`, `pure()`, `unguarded()`, `risky()` — powered by Graph_2 semantic index.

**Reasoning:**
Users and agents need to query behavioral properties. "Which functions write to the database?" and "Which mutations have no guard?" are impossible with structural queries alone. This integrates R-027 query functions into the existing query infrastructure.

**Implementation Steps:**
1. Register semantic query functions in query parser (L-001):
   - `effects("DATABASE_WRITE")`, `actions("AUTHENTICATE")`, `guards("validation")`
   - `domain("payment")`, `pure()`, `unguarded("MUTATE")`, `risky()`
2. Implement execution against semantic index tables (R-028)
3. Support composition: `effects("DATABASE_WRITE") & domain("payment")` — intersect results
4. Include semantic context in output: show actions/effects alongside node IDs

**Files:**
- `codegraph/query.py` (modify)

**Dependencies:** R-027, R-028, L-001, L-013

**Validation:**
- `effects("DATABASE_WRITE")` returns DB-writing functions
- `pure()` returns side-effect-free functions
- Composition works (AND/OR)
- Error when Graph_2 not available: helpful message

---

### TASK L-022 — Add Semantic Depth Queries

**Description:**
Support transitive semantic queries: `effects("DATABASE_WRITE", depth=2)` returns nodes that write to DB directly AND their callers up to depth 2.

**Reasoning:**
A function that calls a DB-writing function is transitively affected by that side effect. Depth queries let agents trace semantic properties through the call graph.

**Implementation Steps:**
1. Add optional `depth` parameter to semantic query functions
2. Execute base query on semantic index
3. For each result, traverse workflow graph `depth` levels up (callers)
4. Union results
5. Tag direct vs transitive matches in output

**Files:**
- `codegraph/query.py` (modify)

**Dependencies:** L-021, L-009, R-028

**Validation:**
- depth=0 → only direct matches
- depth=1 → direct + immediate callers
- Transitive results tagged correctly
- Performance acceptable for depth ≤ 3