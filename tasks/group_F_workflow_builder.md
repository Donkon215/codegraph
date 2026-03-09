# Group F — Workflow Builder

> Edge extraction, static call graph construction, runtime tracing integration, edge filtering, workflow graph generation, and level compression via `workflow.py`.

---

### TASK F-001 — Implement Static Call Graph Builder

**Description:**
Build the static call graph from extracted call sites and resolved targets, producing `edge_type: call, confidence: static` edges.

**Reasoning:**
Static analysis is the primary source of workflow edges. It runs without executing any code and produces medium-confidence edges.

**Implementation Steps:**
1. Implement `build_static_edges(graph0: Graph0, call_sites: dict, imports: dict) -> list[WorkflowEdge]`
2. For each function node, resolve its call sites to target node IDs
3. Create WorkflowEdge for each resolved call:
   - `source`: calling node ID
   - `target`: called node ID
   - `edge_type`: "call"
   - `confidence`: "static"
4. For unresolved calls, create dynamic edges

**Files:**
- `codegraph/workflow.py`

**Dependencies:** C-017, C-018, C-019, B-005

**Edge Cases:**
- Call to function not in Graph_0 (external) → skip or record as layer 0/1
- Recursive calls (self-reference) → valid edge
- Mutual recursion → both edges created

**Validation:**
- Known call sites produce edges
- Unresolved calls become dynamic edges
- No edges to external functions by default

---

### TASK F-002 — Implement Edge Noise Filter — Dunder Methods

**Description:**
Filter out edges involving Python dunder methods (`__init__`, `__repr__`, `__str__`, `__eq__`) from the workflow graph.

**Reasoning:**
README specifies these are filtered by default: `__init__`, `__repr__`, `__str__`, `__eq__`. They add noise without useful signal.

**Implementation Steps:**
1. Implement `DunderFilter` in `codegraph/filters.py`
2. Define default filtered dunder methods
3. Filter edges where source or target is a dunder method
4. Make the filter list configurable

**Files:**
- `codegraph/filters.py`

**Dependencies:** B-005

**Edge Cases:**
- Custom `__init__` with significant logic → still filtered by default
- User overrides to include `__init__` → configurable
- `__call__` → include or exclude? (include by default, it has semantic meaning)

**Validation:**
- `__init__` edges filtered out
- Non-dunder edges preserved
- Config override works

---

### TASK F-003 — Implement Edge Noise Filter — Logging and Print

**Description:**
Filter out edges to logging and print functions.

**Reasoning:**
README lists `logging.*`, `print`, `pprint` as filtered. These are ubiquitous calls that add no structural signal.

**Implementation Steps:**
1. Implement `LoggingFilter` in `codegraph/filters.py`
2. Filter edges targeting: `logging.*`, `print`, `pprint`
3. Match by function name pattern
4. Make configurable

**Files:**
- `codegraph/filters.py` (modify)

**Dependencies:** B-005

**Validation:**
- Logging calls filtered
- print/pprint calls filtered
- Custom logger names matched by pattern

---

### TASK F-004 — Implement Edge Noise Filter — Stdlib Utilities

**Description:**
Filter out edges to stdlib utility functions (`os.path.*`, `sys.*`, etc.).

**Reasoning:**
README lists `stdlib utilities (os.path, sys.*, etc.)` as filtered. These are infrastructure calls.

**Implementation Steps:**
1. Implement `StdlibFilter` in `codegraph/filters.py`
2. Filter edges targeting stdlib utility modules
3. Use layer detection (layer 0) as primary filter
4. Additional pattern matching for common stdlib calls

**Files:**
- `codegraph/filters.py` (modify)

**Dependencies:** B-005, D-002

**Validation:**
- `os.path.join` calls filtered
- `sys.exit` calls filtered
- Application code edges preserved

---

### TASK F-005 — Implement Edge Noise Filter — Dataclasses

**Description:**
Filter out edges involving `dataclasses.*` auto-generated methods.

**Reasoning:**
Dataclass-generated methods (`__init__`, `__repr__`, etc.) are boilerplate that clutters the graph.

**Implementation Steps:**
1. Implement `DataclassFilter` in `codegraph/filters.py`
2. Detect dataclass-decorated classes
3. Filter edges involving auto-generated methods of dataclasses
4. Preserve edges to user-defined methods on dataclasses

**Files:**
- `codegraph/filters.py` (modify)

**Dependencies:** B-005, C-013

**Validation:**
- Dataclass auto-methods filtered
- User-defined methods preserved

---

### TASK F-006 — Implement Edge Noise Filter — Test Harness Internals

**Description:**
Filter out edges to test harness internal functions (pytest fixtures, setup/teardown).

**Reasoning:**
README lists "test harness internals" as filtered. These are framework machinery, not application logic.

**Implementation Steps:**
1. Implement `TestHarnessFilter` in `codegraph/filters.py`
2. Filter: pytest fixture functions, conftest, setup/teardown methods
3. Pattern matching for common test framework patterns
4. Preserve actual test functions (test_*) and their calls

**Files:**
- `codegraph/filters.py` (modify)

**Dependencies:** B-005

**Validation:**
- Setup/teardown filtered
- conftest helpers filtered
- test_* functions preserved

---

### TASK F-007 — Implement Configurable Filter Pipeline

**Description:**
Create a filter pipeline that chains multiple filters and supports configuration.

**Reasoning:**
Users need to customize which edges are filtered. A pipeline architecture makes filters composable and configurable.

**Implementation Steps:**
1. Implement `FilterPipeline` class in `codegraph/filters.py`
2. Accept list of filter instances
3. `apply(edges: list[WorkflowEdge]) -> list[WorkflowEdge]`
4. Log filtered edges count per filter
5. Load filter config from config.yaml
6. Support `codegraph workflow --help` to list available filters

**Files:**
- `codegraph/filters.py` (modify)

**Dependencies:** F-002 through F-006, A-009

**Validation:**
- Multiple filters chain correctly
- Config enables/disables filters
- Filtered count logged per filter

---

### TASK F-008 — Implement Runtime Trace Layer Filter

**Description:**
Implement the layer-based filter for runtime traces that only includes Layer 3 (project source) and Layer 4 (test) nodes.

**Reasoning:**
README states: "runtime tracing ignores all nodes at Layer 0, 1, and 2. Only Layer 3 and 4 nodes are included in trace edges." Without this, 80-90% of traced edges are library calls.

**Implementation Steps:**
1. Implement `RuntimeTraceLayerFilter` in `codegraph/filters.py`
2. During trace processing, filter edges where either source or target is layer 0, 1, or 2
3. This is a mandatory filter for trace mode, not user-configurable

**Files:**
- `codegraph/filters.py` (modify)

**Dependencies:** D-007, B-005

**Validation:**
- Layer 0/1/2 edges from traces filtered
- Layer 3/4 trace edges preserved
- Filter applied after trace data collected

---

### TASK F-009 — Implement Coverage.py Integration for Runtime Tracing

**Description:**
Integrate with coverage.py to capture function-level execution traces during test runs.

**Reasoning:**
The README specifies coverage.py for runtime tracing (not sys.settrace due to 10-50x performance penalty). Traces are captured via pytest plugin hook.

**Implementation Steps:**
1. Implement `run_trace(project_root: Path, test_dir: str = "tests") -> list[TraceEdge]`
2. Configure coverage.py for function-level tracing (not line-level)
3. Run pytest with coverage plugin
4. Parse coverage data to extract function call sequences
5. Convert to WorkflowEdge list with `confidence: runtime`

**Files:**
- `codegraph/workflow.py` (modify)

**Dependencies:** A-003 (coverage dependency)

**Edge Cases:**
- No tests found → warning, fall back to static only
- Test run fails → warning, fall back to static only
- Tests timeout → configurable timeout
- Coverage data too large → filter by layer before processing

**Validation:**
- Trace edges captured from test execution
- Confidence set to "runtime"
- Fallback works on test failure

---

### TASK F-010 — Implement Trace Data Parser

**Description:**
Parse coverage.py output to extract function-level call edges.

**Reasoning:**
Coverage.py outputs line-level data. This must be converted to function-level call relationships by mapping line numbers to Graph_0 nodes.

**Implementation Steps:**
1. Implement `parse_trace_data(coverage_data, graph0: Graph0) -> list[WorkflowEdge]`
2. Map covered lines to functions using Graph_0 line numbers
3. Infer call relationships: if A's lines are covered followed by B's lines in same test → A calls B
4. Assign `edge_type: trace`, `confidence: runtime`

**Files:**
- `codegraph/workflow.py` (modify)

**Dependencies:** F-009, B-002

**Edge Cases:**
- Line not in any known function → skip
- Same function called multiple times → single edge
- Concurrent execution → order ambiguity

**Validation:**
- Trace edges match actual execution paths
- Line-to-function mapping is accurate

---

### TASK F-011 — Implement Test-Execution Edge Builder

**Description:**
Build edges from test functions to the functions they test, with `confidence: test`.

**Reasoning:**
Test execution produces `edge_type: test, confidence: test` edges. These are high-confidence edges that show which functions are actually tested.

**Implementation Steps:**
1. Implement `build_test_edges(test_results, graph0: Graph0) -> list[WorkflowEdge]`
2. For each test function, determine which production functions it called
3. Create edges from test node to production node
4. Assign `edge_type: test`, `confidence: test`

**Files:**
- `codegraph/workflow.py` (modify)

**Dependencies:** F-009, B-005

**Validation:**
- Test-to-production edges created
- Confidence is "test"
- Multiple test functions create separate edges

---

### TASK F-012 — Implement Dynamic Edge Builder

**Description:**
Build dynamic edges with wildcard targets for calls that cannot be statically resolved.

**Reasoning:**
Dynamic dispatch patterns (registry lookup, getattr, etc.) produce edges with `target: "scope::*"`.

**Implementation Steps:**
1. Implement `build_dynamic_edges(dynamic_calls: list[DynamicCall]) -> list[WorkflowEdge]`
2. For each unresolved call:
   - Determine scope from context (module, class, registry name)
   - Create edge with `target: "scope::*"`
   - Set `edge_type: dynamic`, `confidence: static`
3. Group similar dynamic calls

**Files:**
- `codegraph/workflow.py` (modify)

**Dependencies:** C-019, B-005

**Edge Cases:**
- Scope cannot be determined → use module name
- Multiple dynamic calls to same scope → deduplicate

**Validation:**
- Dynamic edges have wildcard targets
- Scope is reasonable
- No exact target resolution attempted

---

### TASK F-013 — Implement Edge Merging from Multiple Sources

**Description:**
Merge edges from all sources (static, trace, test, dynamic) into a single workflow graph, preserving all edges.

**Reasoning:**
The README states: "When the same logical edge is observed from multiple sources, all edges are preserved." No deduplication by source type.

**Implementation Steps:**
1. Implement `merge_edges(static: list, trace: list, test: list, dynamic: list) -> list[WorkflowEdge]`
2. Concatenate all edge lists
3. Deduplicate exact matches only (same source+target+type+confidence)
4. Sort by source node ID for deterministic output
5. Apply filter pipeline

**Files:**
- `codegraph/workflow.py` (modify)

**Dependencies:** F-001, F-009, F-011, F-012, B-026

**Validation:**
- All sources included
- Same edge from static and runtime both preserved (different confidence)
- Exact duplicates removed

---

### TASK F-014 — Implement Workflow Graph Writer

**Description:**
Assemble and write the complete `workflow.json` file.

**Reasoning:**
The workflow graph is the central behavior representation. It must be written in the correct format with metadata.

**Implementation Steps:**
1. Implement `write_workflow(edges: list[WorkflowEdge], project_root: Path, level: str = "function")`
2. Create Workflow collection with metadata (timestamp, level)
3. Serialize to JSON
4. Write to `.codegraph/workflow/workflow.json` atomically

**Files:**
- `codegraph/workflow.py` (modify)

**Dependencies:** F-013, B-006, A-013

**Validation:**
- Valid JSON written
- All edges included
- Metadata present

---

### TASK F-015 — Implement Module-Level Workflow Compression

**Description:**
Implement `--level module` compression that aggregates function-level edges to module-level.

**Reasoning:**
Module-level view reduces graph complexity for high-level planning. A single edge per module pair with counts.

**Implementation Steps:**
1. Implement `compress_to_module(edges: list[WorkflowEdge]) -> list[WorkflowEdge]`
2. For each edge, extract module from source and target node IDs
3. Create module-level edges, deduplicating
4. Optionally include edge count as metadata

**Files:**
- `codegraph/workflow.py` (modify)

**Dependencies:** F-013, B-036

**Edge Cases:**
- Self-module edges (function calling another function in same module) → include or exclude
- Very large modules → still single node

**Validation:**
- Module-level graph is smaller than function-level
- All module pairs with connections represented
- No function-level detail leaked

---

### TASK F-016 — Implement Class-Level Workflow Compression

**Description:**
Implement `--level class` compression that aggregates method-level edges to class-level.

**Reasoning:**
Class-level view shows OOP structure relationships between classes.

**Implementation Steps:**
1. Implement `compress_to_class(edges: list[WorkflowEdge]) -> list[WorkflowEdge]`
2. For each edge, extract class from source and target node IDs
3. Functions not in a class → use module as "class"
4. Create class-level edges, deduplicating

**Files:**
- `codegraph/workflow.py` (modify)

**Dependencies:** F-013, B-036

**Validation:**
- Class-level graph between function and module in size
- Method-to-method edges compressed to class-to-class

---

### TASK F-017 — Implement Import Edge Builder (Optional Mode)

**Description:**
Build import-level edges when `--include-imports` flag is used.

**Reasoning:**
README states import edges are NOT included by default but available via `--include-imports`. Import edges show module dependencies.

**Implementation Steps:**
1. Implement `build_import_edges(imports: dict, graph0: Graph0) -> list[WorkflowEdge]`
2. For each import statement, create an edge from importing module to imported module
3. Do NOT include in default workflow
4. Only add when `--include-imports` flag is passed

**Files:**
- `codegraph/workflow.py` (modify)

**Dependencies:** C-016, B-005

**Edge Cases:**
- Relative imports → resolve to absolute
- Circular imports → both edges valid
- Import of specific names → edge to module, not to individual names

**Validation:**
- Import edges excluded by default
- `--include-imports` adds them
- Module-level edges for imports

---

### TASK F-018 — Implement Workflow Build Orchestrator

**Description:**
Create the top-level workflow build function that orchestrates all edge sources and produces the final graph.

**Reasoning:**
This is the main function called by `codegraph workflow`. It must coordinate static analysis, optional tracing, filtering, and output.

**Implementation Steps:**
1. Implement `build_workflow(project_root, config, trace=False, archi=False, trace_all=False, include_imports=False, level="function") -> Workflow`
2. Steps:
   a. Load Graph_0
   b. Run static call graph analysis
   c. If trace: run coverage.py against tests
   d. If archi: run coverage.py against test_archi/
   e. If trace_all: run both
   f. Build all edge types
   g. Merge edges
   h. Apply filters
   i. Compress if level != function
   j. Write workflow.json
3. Return Workflow object

**Files:**
- `codegraph/workflow.py` (modify)

**Dependencies:** F-001, F-007, F-009, F-013, F-014, F-015, F-016, F-017

**Validation:**
- Static-only build works
- Trace build works
- Level compression works
- All flags handled correctly

---

### TASK F-019 — Implement Workflow Loading

**Description:**
Implement loading of existing `workflow.json` for queries and analysis.

**Reasoning:**
Many commands (analyze, tasks, explain, query) need to read the existing workflow graph.

**Implementation Steps:**
1. Implement `load_workflow(project_root: Path) -> Workflow`
2. Parse JSON file
3. Validate structure
4. Build internal indexes (source_map, target_map) on load
5. Handle missing file gracefully

**Files:**
- `codegraph/workflow.py` (modify)

**Dependencies:** B-006

**Validation:**
- Load produces functional Workflow object
- Indexes built on load
- Missing file returns empty workflow

---

### TASK F-020 — Implement Workflow Validation

**Description:**
Implement `codegraph validate` that checks workflow graph integrity.

**Reasoning:**
After manual edits or repairs, the workflow graph may be inconsistent. Validation catches issues.

**Implementation Steps:**
1. Implement `validate_workflow(workflow: Workflow, graph0: Graph0) -> list[ValidationIssue]`
2. Checks:
   - All edge sources exist in Graph_0
   - All edge targets exist in Graph_0 (or are dynamic wildcards)
   - No exact duplicate edges
   - Edge types are valid
   - Confidence values are valid
3. Return list of issues

**Files:**
- `codegraph/workflow.py` (modify)

**Dependencies:** F-019, B-002

**Validation:**
- Invalid source node detected
- Invalid edge type detected
- Valid graph passes

---

### TASK F-021 — Implement Orphan Node Detection

**Description:**
Find nodes with no incoming or outgoing edges in the workflow graph.

**Reasoning:**
Orphan detection is a core analysis function. Orphan nodes may be dead code or disconnected entry points.

**Implementation Steps:**
1. Implement `find_orphans(workflow: Workflow, graph0: Graph0) -> list[str]`
2. Build set of all nodes that appear as source or target in any edge
3. Find Graph_0 nodes not in this set
4. Exclude module-level nodes (they may not have edges)
5. Filter by layer (only report layer 3/4 orphans)

**Files:**
- `codegraph/workflow.py` (modify)

**Dependencies:** F-019, B-002, D-007

**Edge Cases:**
- Module with no functions → not an orphan
- Class with only `__init__` → filtered, so appears orphan
- Entry points (CLI, main) → may appear orphan

**Validation:**
- True orphans detected
- Entry points not falsely flagged
- Module nodes excluded

---

### TASK F-022 — Implement Workflow Edge Counting

**Description:**
Count edges by type and confidence for status reporting.

**Reasoning:**
`codegraph status` needs edge counts. Detailed breakdowns by type help assess analysis quality.

**Implementation Steps:**
1. Implement `edge_statistics(workflow: Workflow) -> EdgeStats`
2. Count: total edges, by edge_type, by confidence
3. Count: dynamic edges, resolved edges
4. Include in status report

**Files:**
- `codegraph/workflow.py` (modify)

**Dependencies:** F-019

**Validation:**
- Counts match actual edge data
- All types and confidences accounted for

---

### TASK F-023 — Implement Workflow Incremental Update

**Description:**
Update the workflow graph incrementally for changed files only (used by delta engine).

**Reasoning:**
After delta detects changed files, only their edges need re-extraction. This is much faster than full rebuild.

**Implementation Steps:**
1. Implement `update_workflow_incremental(workflow: Workflow, changed_files: list[str], graph0: Graph0) -> Workflow`
2. Remove all edges where source or target is in a changed file
3. Re-extract call sites from changed files
4. Build new edges for changed files
5. Merge with existing edges

**Files:**
- `codegraph/workflow.py` (modify)

**Dependencies:** F-001, F-019

**Validation:**
- Edges from changed files updated
- Edges from unchanged files preserved
- Result equivalent to full rebuild for changed portions

---

### TASK F-024 — Implement Self-Call Detection

**Description:**
Detect and handle recursive function calls (function calling itself).

**Reasoning:**
Recursive calls produce self-reference edges. These are valid workflow edges and should be preserved.

**Implementation Steps:**
1. During edge building, don't filter edges where source == target
2. Tag self-referencing edges as `recursive: true` in metadata
3. Include in workflow graph normally

**Files:**
- `codegraph/workflow.py` (modify)

**Dependencies:** F-001

**Validation:**
- Recursive function produces self-referencing edge
- Edge appears in workflow graph
- Not filtered by any default filter

---

### TASK F-025 — Implement Coverage.py Pytest Plugin Hook

**Description:**
Create or configure the pytest plugin hook that runs coverage.py during `codegraph workflow --trace`.

**Reasoning:**
The README states traces are captured via pytest plugin hook with coverage.py instrumentation.

**Implementation Steps:**
1. Create `codegraph/pytest_plugin.py` (or use coverage.py's pytest plugin directly)
2. Configure coverage to record function entry only
3. Hook into pytest collection to run codegraph-specific post-processing
4. Output trace data to `.codegraph/` temp directory
5. Clean up trace data after processing

**Files:**
- `codegraph/pytest_plugin.py`

**Dependencies:** F-009

**Edge Cases:**
- pytest not installed → error with install instructions
- coverage.py not available → error with install instructions
- Conflicting coverage configuration → warn and continue

**Validation:**
- Plugin loads correctly with pytest
- Coverage data captured during test run
- Cleanup works

---

### TASK F-026 — Implement Trace Fallback on Failure

**Description:**
Implement graceful fallback to static-only edges when runtime tracing fails.

**Reasoning:**
README specifies: "If no tests are found or the test run fails, codegraph falls back to static edges only and logs a warning."

**Implementation Steps:**
1. Catch all trace-related exceptions in workflow builder
2. Log detailed warning about the failure
3. Continue with static edges only
4. Mark workflow metadata to indicate trace was attempted but failed

**Files:**
- `codegraph/workflow.py` (modify)

**Dependencies:** F-009, F-018

**Validation:**
- Failed trace produces warning, not error
- Static edges still generated
- Metadata indicates trace failure

---

### TASK F-027 — Implement Architecture Test Trace Mode

**Description:**
Support `--archi` flag that runs traces against `.codegraph/test_archi/` instead of `tests/`.

**Reasoning:**
Architecture tests are separate from project tests. The `--archi` flag switches the test directory for tracing.

**Implementation Steps:**
1. Add `archi` parameter to `run_trace()`
2. Point test discovery to `.codegraph/test_archi/`
3. Merge results with `confidence: runtime`
4. Support `--trace-all` to run both

**Files:**
- `codegraph/workflow.py` (modify)

**Dependencies:** F-009, F-025

**Validation:**
- `--archi` traces from test_archi/ directory
- `--trace-all` combines both directories
- Edges merged correctly

---

### TASK F-028 — Implement Edge Source Tracking Metadata

**Description:**
Track which source (static analysis, which test file, which trace run) produced each edge.

**Reasoning:**
For debugging and audit, knowing exactly where an edge came from helps resolve conflicts and assess reliability.

**Implementation Steps:**
1. Add optional `source_detail` field to WorkflowEdge metadata
2. For static: name of analysis pass
3. For trace: test file that triggered the execution
4. For test: specific test function
5. Include in serialized output

**Files:**
- `codegraph/models/workflow.py` (modify)
- `codegraph/workflow.py` (modify)

**Dependencies:** B-005, F-013

**Validation:**
- Source detail populated for all edge sources
- Detail included in JSON output

---

### TASK F-029 — Implement Workflow Graph Statistics Summary

**Description:**
Generate a comprehensive summary of the workflow graph for CLI display.

**Reasoning:**
After building the workflow, users need a quick summary of what was generated: edge counts by type, coverage, orphans.

**Implementation Steps:**
1. Implement `workflow_summary(workflow: Workflow, graph0: Graph0) -> str`
2. Include:
   - Total edges and nodes
   - Edges by type (call, test, trace, dynamic)
   - Edges by confidence
   - Orphan node count
   - Dynamic (unresolved) edge count
3. Format for CLI output

**Files:**
- `codegraph/workflow.py` (modify)

**Dependencies:** F-022, F-021

**Validation:**
- Summary text includes all metrics
- Counts are accurate

---

### TASK F-030 — Implement Workflow Diff for Delta Verification

**Description:**
Compare two workflow graphs and report differences.

**Reasoning:**
After `codegraph delta`, the user needs to know what edges changed. This is also used by `codegraph diff`.

**Implementation Steps:**
1. Implement `diff_workflows(old: Workflow, new: Workflow) -> WorkflowDiff`
2. Detect: new edges, removed edges, changed edges (same source/target but different type/confidence)
3. Return structured diff
4. Format for CLI output

**Files:**
- `codegraph/workflow.py` (modify)

**Dependencies:** F-019

**Validation:**
- New edges detected
- Removed edges detected
- Changed edges reported

---

### TASK F-031 — Implement Import Dependency Tracker (Separate from Workflow)

**Description:**
Build and store import-level dependencies separate from the workflow graph, accessible via `codegraph query "dependencies(module)"`.

**Reasoning:**
README states: "Import-level dependencies are stored separately and accessible via query." This is not part of the default workflow.

**Implementation Steps:**
1. Implement `build_import_dependencies(graph0, imports) -> ImportGraph`
2. Store at `.codegraph/workflow/imports.json`
3. Module-to-module import relationships
4. Used only by the query system, not by the workflow graph

**Files:**
- `codegraph/workflow.py` (modify)

**Dependencies:** C-016

**Validation:**
- Import graph separate from workflow
- Accessible via query
- Not in default workflow edges

---

### TASK F-032 — Implement Workflow Build Performance Optimization

**Description:**
Optimize the workflow build for large repos (10k+ functions, 50k+ edges).

**Reasoning:**
README mentions scaling concerns. Workflow building must be efficient for large codebases.

**Implementation Steps:**
1. Profile workflow build on large repos
2. Use set-based operations for edge merging
3. Batch filter applications
4. Consider parallel edge building per file
5. Target: build 50k edges in < 5 seconds

**Files:**
- `codegraph/workflow.py` (modify)

**Dependencies:** F-018

**Validation:**
- Performance benchmark meets targets
- Correctness unchanged
- Memory usage reasonable

---

### TASK F-033 — Implement Conditional Edge Detection

**Description:**
Detect calls that only happen under certain conditions (if/else branches, try/except).

**Reasoning:**
Conditional calls may or may not execute. While they're still valid edges, metadata about conditionality helps agents reason about coverage.

**Implementation Steps:**
1. During call site extraction, detect if a call is inside:
   - if/elif/else branch
   - try/except block
   - loop body
   - with statement
2. Add optional `conditional: bool` metadata to edge
3. Include in WorkflowEdge serialization

**Files:**
- `codegraph/workflow.py` (modify)
- `codegraph/extractor.py` (modify)

**Dependencies:** C-017

**Edge Cases:**
- Call in both branches → not conditional
- Call after all branches merge → not conditional

**Validation:**
- Conditional calls marked
- Unconditional calls not marked
- Metadata serialized

---

### TASK F-034 — Implement Workflow Level Validation

**Description:**
Validate the `--level` flag and ensure correct compression is applied.

**Reasoning:**
Invalid level values should produce clear errors. The three valid levels must produce correctly compressed graphs.

**Implementation Steps:**
1. Validate level parameter: "function", "class", "module"
2. Invalid value → error with valid options listed
3. Ensure compression doesn't lose critical information
4. Default to "function" if not specified

**Files:**
- `codegraph/workflow.py` (modify)

**Dependencies:** B-036

**Validation:**
- Invalid level produces clear error
- Default is "function"
- All three levels produce valid workflow graphs

---

### TASK F-035 — Implement Workflow Metadata Header

**Description:**
Add metadata header to workflow.json including build parameters and statistics.

**Reasoning:**
Knowing how a workflow was built (static only? traced? filtered?) helps interpret the data.

**Implementation Steps:**
1. Add header to workflow.json:
   ```json
   {
     "metadata": {
       "built_at": "...",
       "level": "function",
       "trace_mode": "static_only",
       "filters_applied": ["dunder", "logging", "stdlib"],
       "edge_count": 4320,
       "node_count": 1240
     },
     "edges": [...]
   }
   ```
2. Populate from build parameters

**Files:**
- `codegraph/workflow.py` (modify)
- `codegraph/models/workflow.py` (modify)

**Dependencies:** F-014

**Validation:**
- Metadata present in output
- Build parameters reflected

---

### TASK F-036 — Implement Workflow Edge Export (Graphviz/Mermaid)

**Description:**
Export the workflow graph in visualization formats for human review.

**Reasoning:**
Engineers may want to visualize the call graph. Dot (Graphviz) and Mermaid are common formats.

**Implementation Steps:**
1. Implement `export_workflow(workflow, format="dot") -> str`
2. Support: Graphviz DOT, Mermaid, plain adjacency list
3. Apply node coloring by layer
4. Limit output to configurable depth/size

**Files:**
- `codegraph/workflow.py` (modify)

**Dependencies:** F-019

**Edge Cases:**
- Very large graph → limit or cluster
- Dynamic edges → show with dashed lines

**Validation:**
- DOT output renders in Graphviz
- Mermaid output renders in Mermaid-compatible tools
