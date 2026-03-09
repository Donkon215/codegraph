# Group M — Architecture Tests & Test Impact Analysis

> Architecture test generation, test_archi management, test impact analysis, backward tracing, coverage integration, and test_change_type classification via `archi_test.py` and `test_impact.py`.

---

### TASK M-001 — Implement Architecture Test Generator

**Description:**
Generate architecture test stubs that exercise real code paths without mocks.

**Reasoning:**
README: "Architecture tests are separate from project tests. They exercise real code paths, never mock, and produce runtime traces."

**Implementation Steps:**
1. Create `codegraph/archi_test.py`
2. Implement `generate_archi_tests(graph0, workflow, project_root) -> list[GeneratedTest]`
3. For each untested workflow edge:
   - Generate a minimal test that calls the source function
   - No mocks, no assertions beyond "doesn't crash"
   - Test imports the actual module
4. Write tests to `.codegraph/test_archi/`

**Files:**
- `codegraph/archi_test.py`

**Dependencies:** F-019, B-002

**Edge Cases:**
- Function requires complex setup → generate minimal fixture
- Function has side effects (DB, file I/O) → flag for manual setup
- Circular imports → careful import ordering

**Validation:**
- Tests generated run without error on basic functions
- Tests import correct modules
- Tests don't use mocks

---

### TASK M-002 — Implement Test Archi Directory Management

**Description:**
Manage the `.codegraph/test_archi/` directory structure.

**Reasoning:**
Architecture tests must be organized, not mixed with project tests.

**Implementation Steps:**
1. Create `.codegraph/test_archi/` directory on first use
2. Mirror source directory structure for test files
3. Naming convention: `test_archi_{module}_{function}.py`
4. `conftest.py` with shared fixtures
5. `__init__.py` for pytest discovery

**Files:**
- `codegraph/archi_test.py` (modify)

**Dependencies:** M-001

**Validation:**
- Directory created
- Tests discoverable by pytest
- Structure mirrors source

---

### TASK M-003 — Implement Architecture Test Runner

**Description:**
Run architecture tests via pytest and capture runtime traces.

**Reasoning:**
Architecture tests exist to produce runtime traces, not to assert behavior.

**Implementation Steps:**
1. Implement `run_archi_tests(project_root) -> ArchiTestResult`
2. Run pytest on `.codegraph/test_archi/` with coverage.py
3. Capture:
   - Pass/fail status per test
   - Runtime trace data (function-level)
   - Execution time
4. Don't fail build on test failures (they're structural probes)

**Files:**
- `codegraph/archi_test.py` (modify)

**Dependencies:** M-002, F-009

**Edge Cases:**
- Test crashes → log and continue
- Import error → log with fix suggestion
- Timeout → configurable per test

**Validation:**
- Tests run via pytest
- Trace data captured
- Failures logged but don't stop processing

---

### TASK M-004 — Implement Architecture Test Failure Handling

**Description:**
Handle architecture test failures as structural information rather than bugs.

**Reasoning:**
README failure mode: "architecture test failure — a test in test_archi/ crashes or cannot import the target module."

**Implementation Steps:**
1. When an archi test fails:
   - Log the failure with stack trace
   - Record the failure in archi_test_results.json
   - Generate a task for the agent: "Fix architecture test for {node}"
   - DON'T remove the test
2. Common failures:
   - ImportError → suggest missing dependency
   - TypeError → suggest function signature changed
   - RuntimeError → suggest environment setup

**Files:**
- `codegraph/archi_test.py` (modify)

**Dependencies:** M-003

**Validation:**
- Failures recorded
- Tasks generated for failures
- Non-failing tests unaffected

---

### TASK M-005 — Implement Architecture Test Regeneration

**Description:**
Regenerate architecture tests after delta detects function changes.

**Reasoning:**
When functions change signature or behavior, existing archi tests may break. Regeneration updates them.

**Implementation Steps:**
1. Implement `regenerate_archi_tests(delta: DeltaResult, project_root)`
2. For modified functions:
   - Check if corresponding archi test exists
   - Re-generate test with new function signature
   - Preserve custom setup if any
3. For removed functions: delete their archi tests
4. For new functions: optionally generate new archi tests

**Files:**
- `codegraph/archi_test.py` (modify)

**Dependencies:** M-001, K-001

**Validation:**
- Modified function tests regenerated
- Deleted function tests removed
- New tests generated

---

### TASK M-006 — Implement Architecture Test Template System

**Description:**
Create templates for different function types (standalone, method, async, generator).

**Reasoning:**
Different function types need different test patterns. Templates ensure correct test structure.

**Implementation Steps:**
1. Templates for:
   - Standalone function: `def test_archi_funcname(): funcname()`
   - Instance method: create instance, call method
   - Class method: `ClassName.method()`
   - Async function: `asyncio.run(funcname())`
   - Generator: `list(funcname())`
2. Template selection based on node type from Graph_0

**Files:**
- `codegraph/archi_test.py` (modify)

**Dependencies:** M-001, B-002

**Validation:**
- Correct template selected per function type
- Generated tests are syntactically valid
- Async tests use asyncio correctly

---

### TASK M-007 — Implement Test Impact Analysis Core

**Description:**
Determine which tests are affected by code changes.

**Reasoning:**
README: "Test impact analysis traces backwards from modified nodes through the call graph to find all Layer 4 test functions that transitively depend on the changed code."

**Implementation Steps:**
1. Create `codegraph/test_impact.py`
2. Implement `analyze_test_impact(changed_nodes: set[str], index: IndexStore) -> TestImpactResult`
3. For each changed node:
   - Trace backwards through callers (reverse call graph)
   - Collect all reachable Layer 4 (test) nodes
   - Include depth of chain for each test
4. Return unique set of affected test functions

**Files:**
- `codegraph/test_impact.py`

**Dependencies:** G-003, G-006, D-005

**Validation:**
- Direct test callers found
- Transitive test dependencies found
- Layer 4 filtering correct

---

### TASK M-008 — Implement Backward Call Graph Tracing

**Description:**
Implement efficient backward tracing through the call graph for test impact analysis.

**Reasoning:**
Test impact requires traversing the call graph in reverse (callers) until reaching test nodes.

**Implementation Steps:**
1. Implement `trace_backward(start_nodes: set[str], index: IndexStore, stop_layer=4) -> dict[str, list[str]]`
2. BFS from each start node through callers index
3. Stop traversal at Layer 4 nodes (don't go beyond tests)
4. Track the path from each start node to each reached test
5. Handle cycles

**Files:**
- `codegraph/test_impact.py` (modify)

**Dependencies:** M-007, G-003

**Edge Cases:**
- Node with no callers → no test impact
- Very deep call chains → depth limit (configurable)
- Circular dependencies → visited set

**Validation:**
- Backward trace finds correct tests
- Cycles don't cause infinite loops
- Depth limit respected

---

### TASK M-009 — Implement Affected Test Aggregation

**Description:**
Aggregate test impact results across all changed nodes into a unified report.

**Reasoning:**
Multiple changed nodes may affect overlapping test sets. Aggregation deduplicates and prioritizes.

**Implementation Steps:**
1. Implement `aggregate_impact(per_node_results: dict) -> AggregatedImpact`
2. Union of all affected tests
3. For each test:
   - How many changed nodes affect it (impact score)
   - Shortest distance to any changed node
   - Changed node that triggered it
4. Sort by impact score (most affected first)

**Files:**
- `codegraph/test_impact.py` (modify)

**Dependencies:** M-008

**Validation:**
- Tests deduplicated
- Impact scores calculated
- Sorted by impact

---

### TASK M-010 — Implement `test_change_type` Classification

**Description:**
Classify how each affected test relates to the change.

**Reasoning:**
README mentions test_change_type: different types of changes affect tests differently.

**Implementation Steps:**
1. Implement `classify_test_change(test_id, changed_nodes, workflow) -> TestChangeType`
2. Types:
   - `direct`: test directly calls a changed function
   - `transitive`: test calls something that calls the changed function
   - `fixture`: test uses a fixture that depends on changed code
   - `import`: test imports a changed module
   - `structural`: test exists in a changed file (but may not call changed functions)
3. Multiple types possible per test

**Files:**
- `codegraph/test_impact.py` (modify)

**Dependencies:** M-009, B-022

**Validation:**
- Each classification correct
- Multiple types assigned when appropriate

---

### TASK M-011 — Implement Coverage Gap Detection

**Description:**
Find production functions that have no test coverage at all.

**Reasoning:**
Functions with no test path (neither direct nor transitive) are coverage gaps.

**Implementation Steps:**
1. Implement `find_coverage_gaps(graph0, graph1, index) -> list[CoverageGap]`
2. For each Layer 3 function:
   - Check tests index for any test association
   - If no test → coverage gap
3. Classify gaps:
   - `no_test`: no test function found
   - `no_trace`: test exists but no runtime trace confirms execution
   - `indirect_only`: only reached through multi-hop chain

**Files:**
- `codegraph/test_impact.py` (modify)

**Dependencies:** M-007, G-006

**Validation:**
- Untested functions found
- Classification correct
- Tested functions excluded

---

### TASK M-012 — Implement Test Impact Command Output

**Description:**
Format test impact results for CLI display.

**Reasoning:**
Users need a clear view of which tests to run after changes.

**Implementation Steps:**
1. Implement `format_test_impact(result: TestImpactResult) -> str`
2. Sections:
   - Summary: N tests affected by M changed nodes
   - High-impact tests (direct callers)
   - Low-impact tests (transitive only)
   - Coverage gaps (if any)
3. Support `--json` for machine-readable output
4. Support `--test-runner pytest` for copy-paste test commands

**Files:**
- `codegraph/test_impact.py` (modify)

**Dependencies:** M-009

**Validation:**
- All sections present
- Counts accurate
- Test runner output works

---

### TASK M-013 — Implement Test Impact Integration with Delta

**Description:**
Automatically run test impact analysis after delta to show affected tests.

**Reasoning:**
After detecting changes, immediately knowing which tests to run is valuable.

**Implementation Steps:**
1. After delta completes:
   - Extract set of modified node IDs
   - Run test impact analysis
   - Include affected tests in delta result
2. Display in delta output: "Run these N tests to verify changes"
3. Optionally auto-run affected tests

**Files:**
- `codegraph/test_impact.py` (modify)
- `codegraph/delta.py` (modify)

**Dependencies:** M-007, K-001

**Validation:**
- Affected tests shown after delta
- Correct tests identified
- Auto-run option works

---

### TASK M-014 — Implement Architecture Test Coverage Report

**Description:**
Report which workflow edges are covered by architecture tests vs. project tests vs. uncovered.

**Reasoning:**
Architecture tests exist specifically to cover edges that project tests miss. This report shows the coverage status.

**Implementation Steps:**
1. Implement `archi_test_coverage(workflow, archi_results, test_results) -> CoverageReport`
2. For each workflow edge:
   - Covered by project test? (from test edges)
   - Covered by architecture test? (from archi trace)
   - Uncovered?
3. Report percentages and lists

**Files:**
- `codegraph/archi_test.py` (modify)

**Dependencies:** M-003, F-019

**Validation:**
- Coverage percentages calculated
- Covered/uncovered edges listed
- Report accurate

---

### TASK M-015 — Implement Archi Test Cleanup

**Description:**
Remove architecture tests for functions that no longer exist.

**Reasoning:**
After code refactoring, old archi tests may reference deleted functions.

**Implementation Steps:**
1. Implement `cleanup_archi_tests(graph0, project_root) -> CleanupResult`
2. Scan `.codegraph/test_archi/`
3. For each test file:
   - Extract target function from test name/content
   - Check if function still exists in Graph_0
   - If not → delete test file
4. Report cleaned up tests

**Files:**
- `codegraph/archi_test.py` (modify)

**Dependencies:** M-002, B-002

**Validation:**
- Orphaned tests removed
- Valid tests preserved
- Report shows what was cleaned

---

### TASK M-016 — Implement Test Prioritization

**Description:**
Prioritize affected tests by likelihood of failure.

**Reasoning:**
When many tests are affected, running the most likely to fail first saves time.

**Implementation Steps:**
1. Implement `prioritize_tests(affected: list[AffectedTest]) -> list[AffectedTest]`
2. Priority factors:
   - Direct callers > transitive
   - Tests that previously failed > always-pass
   - Tests covering more changed nodes > fewer
   - Shorter tests > longer tests (faster feedback)
3. Return ordered list

**Files:**
- `codegraph/test_impact.py` (modify)

**Dependencies:** M-009

**Validation:**
- Direct callers ranked higher
- Ranking is stable
- All tests included

---

### TASK M-017 — Implement Archi Test Argument Generator

**Description:**
Generate minimal arguments for architecture test function calls.

**Reasoning:**
Functions requiring arguments can't be called with no args. Generating minimal valid arguments makes tests runnable.

**Implementation Steps:**
1. Implement `generate_minimal_args(function_node, graph0) -> dict`
2. For each parameter:
   - Type annotation exists → use type default (int→0, str→"", list→[], etc.)
   - No annotation → use None
   - Complex types → flag for manual setup
3. Handle *args, **kwargs, defaults

**Files:**
- `codegraph/archi_test.py` (modify)

**Dependencies:** M-001, C-013

**Edge Cases:**
- Custom class parameter → can't auto-generate, flag
- File/DB parameters → mock-free = can't test, skip
- Optional parameters → use default

**Validation:**
- Type-annotated params get correct default
- Unannotated params get None
- Complex params flagged

---

### TASK M-018 — Implement Test Impact Performance Optimization

**Description:**
Optimize backward tracing for large codebases with deep call graphs.

**Reasoning:**
With 10k+ nodes and deep call chains, backward tracing can be expensive.

**Implementation Steps:**
1. Use BFS with early termination (stop at Layer 4 nodes)
2. Batch index lookups rather than individual queries
3. Cache intermediate results for overlapping traces
4. Profile and optimize for 10k node graphs

**Files:**
- `codegraph/test_impact.py` (modify)

**Dependencies:** M-008

**Validation:**
- Performance < 1 second for 10k nodes
- Results unchanged from unoptimized
- Memory bounded

---

### TASK M-019 — Implement Architecture Test Fixture Generator

**Description:**
Generate shared fixtures for architecture tests that need common setup.

**Reasoning:**
Many archi tests may need similar setup (database connection, config file, etc.). Shared fixtures reduce duplication.

**Implementation Steps:**
1. Implement `generate_shared_fixtures(tests: list[GeneratedTest]) -> str`
2. Identify common patterns:
   - Config loading → shared fixture
   - Database connection → shared fixture
   - File paths → shared fixture
3. Write to `.codegraph/test_archi/conftest.py`

**Files:**
- `codegraph/archi_test.py` (modify)

**Dependencies:** M-001

**Validation:**
- Common fixtures extracted
- Tests use shared fixtures
- conftest.py is valid

---

### TASK M-020 — Implement Test Impact Diff View

**Description:**
Show test impact changes between two versions (before and after delta).

**Reasoning:**
Understanding how test coverage changed after a delta helps track progress.

**Implementation Steps:**
1. Implement `diff_test_impact(old_impact, new_impact) -> ImpactDiff`
2. Show:
   - New tests affected (weren't before)
   - Tests no longer affected (were before)
   - Tests with changed impact type
3. Useful for CI reporting

**Files:**
- `codegraph/test_impact.py` (modify)

**Dependencies:** M-009

**Validation:**
- Diff shows changes correctly
- All three categories populated

---

### TASK M-021 — Implement CAS-Aware Test Impact Analysis (CAS Integration)

**Description:**
Use the CAS affected set to instantly determine affected tests instead of backward call graph tracing.

**Reasoning:**
Current test impact (M-007) traces backward through the call graph from changed nodes to find test functions. With CAS, any Layer 4 test node in the `affected_set` from propagation (Q-007) is an affected test — no graph traversal needed. This is O(|affected_set|) instead of O(|changed_nodes| × graph_depth).

**Implementation Steps:**
1. Add `test_impact_cas(affected_nodes: set[str], graph0, graph1) -> TestImpactResult` in `codegraph/test_impact.py`
2. Filter `affected_nodes` to only Layer 4 (test) nodes → these are the affected tests
3. For each affected test:
   - Classify as `direct` (calls a body-changed function) or `transitive` (dependency_hash changed via propagation)
   - Find shortest propagation path to a body-changed node
4. Return structured `TestImpactResult` compatible with existing M-007 format
5. Prefer CAS method when dependency_hashes are available; fall back to M-007 backward trace otherwise

**Files:**
- `codegraph/test_impact.py` (modify)

**Dependencies:** M-007, Q-007, D-005

**Edge Cases:**
- No tests in affected set → no test impact
- All tests affected (core library change) → equivalent to "run all tests"
- CAS not available (pre-CAS graph) → fall back to backward trace
- Test calls changed function through 10 levels of indirection → CAS catches it instantly

**Validation:**
- CAS test impact matches backward-trace test impact (same affected tests)
- CAS test impact is faster (benchmark: ≥5× speedup on 10k node graph)
- Deep transitive dependencies caught
- Backward trace fallback works when CAS unavailable
