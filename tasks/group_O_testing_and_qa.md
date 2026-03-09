# Group O — Testing & Quality Assurance

> Unit tests, integration tests, end-to-end tests, fixture management, coverage targets, and CI/CD configuration.

---

### TASK O-001 — Implement Test Infrastructure Setup

**Description:**
Set up the testing infrastructure: pytest configuration, fixtures directory, conftest.py, coverage config.

**Reasoning:**
A solid test foundation is required before writing individual tests.

**Implementation Steps:**
1. Configure `pyproject.toml` [tool.pytest] section
2. Create `tests/conftest.py` with shared fixtures
3. Create `tests/fixtures/` for sample project data
4. Configure coverage: `[tool.coverage]` section
5. Set minimum coverage targets

**Files:**
- `tests/conftest.py`
- `tests/fixtures/` (directory)
- `pyproject.toml` (modify)

**Dependencies:** A-002, A-016

**Validation:**
- pytest discovers tests
- Coverage tracking works
- Fixtures accessible

---

### TASK O-002 — Implement Sample Project Fixture

**Description:**
Create a small sample Python project used as test fixture for all integration tests.

**Reasoning:**
Tests need real Python files to parse, analyze, and manipulate.

**Implementation Steps:**
1. Create `tests/fixtures/sample_project/` with:
   - `main.py` — entry point calling services
   - `services/auth.py` — authentication module
   - `services/payment.py` — payment module
   - `services/db.py` — database module
   - `utils/logger.py` — logging utility
   - `tests/test_auth.py` — test for auth
   - `tests/test_payment.py` — test for payment
2. Include: function calls, imports, classes, decorators, dynamic dispatch
3. Include known orphans, known policy violations for test assertions

**Files:**
- `tests/fixtures/sample_project/` (multiple files)

**Dependencies:** O-001

**Validation:**
- Sample project parses without errors
- Has known characteristics (orphans, edges, layers)

---

### TASK O-003 — Implement Unit Tests for Node ID Generation

**Description:**
Test `file::class::function` node ID construction and edge cases.

**Reasoning:**
Node ID is the fundamental identifier. Incorrect IDs break everything.

**Implementation Steps:**
1. Test cases:
   - Simple function: `"module::_::function"`
   - Method: `"module::Class::method"`
   - Nested class: `"module::Outer.Inner::method"`
   - Module-level: `"module::_::_"`
   - Files with dots in path
   - Unicode in names

**Files:**
- `tests/test_models.py`

**Dependencies:** B-001, B-002

**Validation:**
- All node ID formats correct
- Edge cases handled

---

### TASK O-004 — Implement Unit Tests for Body Hash

**Description:**
Test body hash generation: whitespace invariance, comment invariance, logic change sensitivity.

**Reasoning:**
Body hash is critical for change detection. Must be invariant to cosmetic changes.

**Implementation Steps:**
1. Test cases:
   - Identical function → same hash
   - Added whitespace → same hash
   - Changed comments → same hash
   - Changed logic → different hash
   - Reordered statements → different hash
   - Added parameter → different hash
   - Changed variable name → different hash

**Files:**
- `tests/test_extractor.py`

**Dependencies:** C-010, C-011, C-012

**Validation:**
- All invariance cases pass
- All sensitivity cases pass

---

### TASK O-005 — Implement Unit Tests for Layer Assignment

**Description:**
Test layer detection for all five layer types.

**Reasoning:**
Incorrect layer assignment breaks safety guards and filtering.

**Implementation Steps:**
1. Test cases:
   - stdlib module (os, sys) → Layer 0
   - External package (requests) → Layer 1
   - Internal library (configured) → Layer 2
   - Project source → Layer 3
   - Test file → Layer 4
   - Ambiguous cases
   - Custom layer config

**Files:**
- `tests/test_layers.py`

**Dependencies:** D-001 through D-010

**Validation:**
- Each layer type correctly assigned
- Config overrides work

---

### TASK O-006 — Implement Unit Tests for AST Extraction

**Description:**
Test AST parsing for all Python constructs.

**Reasoning:**
The extractor must handle the full Python grammar.

**Implementation Steps:**
1. Test cases:
   - Functions, methods, static methods, class methods
   - Classes, nested classes
   - Decorators (single, chained)
   - Async functions
   - Generator functions
   - Lambda expressions
   - Nested functions
   - Global/module scope
   - Type annotations
   - Default parameters
   - *args, **kwargs
   - Syntax errors → graceful handling

**Files:**
- `tests/test_extractor.py` (modify)

**Dependencies:** C-001 through C-015

**Validation:**
- All construct types extracted
- No crashes on valid Python
- Syntax errors handled

---

### TASK O-007 — Implement Unit Tests for Call Site Extraction

**Description:**
Test call site detection in all Python patterns.

**Reasoning:**
Missing call sites means missing edges. Must catch all call patterns.

**Implementation Steps:**
1. Test cases:
   - Direct function call: `foo()`
   - Method call: `obj.method()`
   - Chained call: `obj.a().b()`
   - Call with argument unpacking: `f(*args, **kwargs)`
   - Map/filter: `map(func, iterable)`
   - Generator expression with call
   - Conditional call: `f() if x else g()`
   - Walrus operator with call: `(x := f())`
   - Dynamic: `getattr(obj, name)()`

**Files:**
- `tests/test_extractor.py` (modify)

**Dependencies:** C-017, C-018, C-019

**Validation:**
- All call patterns detected
- Targets resolved where possible
- Dynamic calls flagged

---

### TASK O-008 — Implement Unit Tests for Workflow Edge Building

**Description:**
Test edge construction from static analysis and merged sources.

**Reasoning:**
Workflow edges are the primary analysis artifact.

**Implementation Steps:**
1. Test cases:
   - Simple call → edge created
   - Recursive call → self-edge
   - Dynamic call → wildcard target
   - Filtered call (dunder) → no edge
   - Multi-source merge → all preserved
   - Edge deduplication → exact duplicates removed

**Files:**
- `tests/test_workflow.py`

**Dependencies:** F-001, F-013

**Validation:**
- All edge types correctly built
- Filters applied
- Merge correct

---

### TASK O-009 — Implement Unit Tests for Filter Pipeline

**Description:**
Test each filter type and the pipeline composition.

**Reasoning:**
Filters must be precise — filtering too much removes signal, too little adds noise.

**Implementation Steps:**
1. Test cases:
   - Dunder filter: `__init__` filtered, `normal_func` kept
   - Logging filter: `logging.info` filtered, `log_processing()` kept
   - Stdlib filter: `os.path.join` filtered, `pathutils.join()` kept
   - Pipeline: multiple filters compose correctly
   - Config: enable/disable individual filters

**Files:**
- `tests/test_filters.py`

**Dependencies:** F-002 through F-007

**Validation:**
- Each filter precise
- Pipeline composition correct
- Config works

---

### TASK O-010 — Implement Unit Tests for Suggested Workflow Scope Resolution

**Description:**
Test all scope types: exact, module, glob, layer, arch_layer.

**Reasoning:**
Scope resolution determines which nodes a rule applies to. Must be exact.

**Implementation Steps:**
1. Test cases per scope type:
   - Exact: only matches exact node ID
   - Module: matches all nodes in module
   - Glob: `*` and `**` patterns
   - Layer: matches correct layer
   - Arch_layer: matches annotation
   - Zero-match: no nodes match → warning
   - Overlap: multiple scopes matching same node

**Files:**
- `tests/test_suggest.py`

**Dependencies:** H-004 through H-009

**Validation:**
- Each scope type resolves correctly
- Zero-match detected
- Overlaps handled

---

### TASK O-011 — Implement Unit Tests for Policy Violation Detection

**Description:**
Test required_call and forbidden_call violation detection.

**Reasoning:**
Policy violations drive task generation. False positives waste agent time, false negatives miss issues.

**Implementation Steps:**
1. Test cases:
   - Required call present → no violation
   - Required call missing → violation
   - Forbidden call present → violation
   - Forbidden call absent → no violation
   - Scoped rule with multiple matching nodes
   - Rule contradiction detection

**Files:**
- `tests/test_suggest.py` (modify)

**Dependencies:** H-010

**Validation:**
- All violation scenarios correct
- No false positives
- No false negatives

---

### TASK O-012 — Implement Unit Tests for Task Generation

**Description:**
Test task generation from analysis findings with correct priorities and context.

**Reasoning:**
Tasks must be correctly prioritized and contain useful pre-fetched context.

**Implementation Steps:**
1. Test cases:
   - Policy violation → priority 1
   - Missing edge → priority 2
   - Orphan → priority 3
   - Missing intent → priority 4
   - Coverage gap → priority 5
   - Stale intent → priority 6
   - Context includes callers/callees
   - Deduplication works
   - graph_version included

**Files:**
- `tests/test_tasks.py`

**Dependencies:** I-007, I-008, I-009

**Validation:**
- Priorities correct
- Context populated
- Deduplication works

---

### TASK O-013 — Implement Unit Tests for Apply Actions

**Description:**
Test each repair action type: connect_call, add_import, remove_dead_code, flag_for_review.

**Reasoning:**
Apply actions modify code. Incorrect modifications break the codebase.

**Implementation Steps:**
1. Test cases:
   - connect_call: inserts at first executable statement
   - connect_call: adds import if needed
   - connect_call: already connected → rejection
   - add_import: appends to import block
   - add_import: duplicate import → skip
   - remove_dead_code: all 4 signals → removal
   - remove_dead_code: < 4 signals → rejection
   - flag_for_review: records flag, no code change

**Files:**
- `tests/test_apply.py`

**Dependencies:** J-002 through J-005

**Validation:**
- Each action type tested with success and failure cases
- Code modifications are correct

---

### TASK O-014 — Implement Unit Tests for Delta Engine

**Description:**
Test incremental change detection, body hash comparison, and graph merging.

**Reasoning:**
Delta must correctly identify what changed and update only affected elements.

**Implementation Steps:**
1. Test cases:
   - File added → new nodes detected
   - File deleted → nodes removed
   - File modified (whitespace only) → no logic change
   - File modified (code change) → logic change detected
   - Function renamed → old removed, new added
   - Intent flagged stale on body_hash change
   - Graph_0 merge correct
   - graph_version incremented

**Files:**
- `tests/test_delta.py`

**Dependencies:** K-001 through K-010

**Validation:**
- All change scenarios handled
- Incremental update matches full rebuild result

---

### TASK O-015 — Implement Unit Tests for Query System

**Description:**
Test all query functions with known graph data.

**Reasoning:**
Queries must return correct results for analysis and agent context.

**Implementation Steps:**
1. Test cases:
   - callers(): returns correct callers
   - callees(): returns correct callees
   - dependencies(): transitive, handles cycles
   - dependents(): transitive in reverse
   - path(): shortest path found
   - path(): no path → empty
   - orphans(): correct identification
   - layer(): correct filtering
   - depth and limit parameters

**Files:**
- `tests/test_query.py`

**Dependencies:** L-001 through L-013

**Validation:**
- All query functions return correct results
- Edge cases (cycles, no results) handled

---

### TASK O-016 — Implement Unit Tests for Index

**Description:**
Test index build, query, delta update, and consistency check.

**Reasoning:**
Index must provide correct O(1) lookups.

**Implementation Steps:**
1. Test cases:
   - Build all indexes from graph data
   - Query each index type
   - Delta update adds/removes entries correctly
   - Rebuild produces same result as fresh build
   - Consistency check passes on good data
   - Consistency check fails on corrupted data

**Files:**
- `tests/test_index.py`

**Dependencies:** G-001 through G-010

**Validation:**
- All index operations correct
- Delta update equivalent to rebuild

---

### TASK O-017 — Implement Unit Tests for Convergence Tracking

**Description:**
Test the repair loop convergence criteria.

**Reasoning:**
Convergence determines when to stop the repair loop. Must be accurate.

**Implementation Steps:**
1. Test cases:
   - Orphan count stable 3 iterations → converged
   - Edge count within ±5% → converged
   - Max iterations → converged
   - All human review → converged
   - Active changes → not converged

**Files:**
- `tests/test_analyzer.py`

**Dependencies:** I-018

**Validation:**
- Each convergence criterion works independently
- Combined check works

---

### TASK O-018 — Implement Unit Tests for Version Staleness

**Description:**
Test graph_version validation for agent responses.

**Reasoning:**
Version mismatch is a critical safety check.

**Implementation Steps:**
1. Test cases:
   - Matching versions → accepted
   - Response version < current → rejected
   - Response version > current → rejected (impossible but handle)
   - Missing version → rejected

**Files:**
- `tests/test_tasks.py` (modify)

**Dependencies:** I-014

**Validation:**
- Only matching version accepted
- Clear error on mismatch

---

### TASK O-019 — Implement Unit Tests for All 17+ Failure Modes

**Description:**
Create specific tests for each failure mode listed in the README.

**Reasoning:**
README enumerates 17+ failure modes. Each must be tested to ensure correct handling.

**Implementation Steps:**
1. Test each failure mode:
   - AST parse error → skip file, continue
   - Module import error → log, continue
   - Intent conflict → resolution strategy applied
   - Node ID collision → detected and handled
   - Body hash changed → stale intent flagged
   - Test crash → logged, analysis continues
   - Graph drift → detected in validate
   - Dangling rules → detected in validate
   - Wildcard zero matches → warning
   - Delta uncommitted → warning + process
   - Apply conflict → rejected with message
   - Version mismatch → rejected
   - Already connected → rejected
   - Insufficient dead code signals → rejected
   - Cycle mismatch → detected
   - Index inconsistency → detected, rebuild suggested
   - Architecture test failure → logged, task generated

**Files:**
- `tests/test_failure_modes.py`

**Dependencies:** Various (one per failure mode)

**Validation:**
- Every failure mode has at least one test
- Correct behavior for each

---

### TASK O-020 — Implement Integration Test: Full Build Pipeline

**Description:**
End-to-end test: codegraph build on sample project, verifying all artifacts.

**Reasoning:**
The full pipeline must work end-to-end.

**Implementation Steps:**
1. Run `codegraph build` on sample project
2. Verify:
   - `.codegraph/graph/graph0.json` exists and valid
   - `.codegraph/graph/graph1.json` exists and valid
   - `.codegraph/workflow/workflow.json` exists and valid
   - `.codegraph/index/` contains all .db files
   - Node count matches expected
   - Edge count > 0

**Files:**
- `tests/test_integration.py`

**Dependencies:** O-002, N-002

**Validation:**
- Full pipeline succeeds
- All artifacts valid

---

### TASK O-021 — Implement Integration Test: Build-Analyze-Tasks Pipeline

**Description:**
End-to-end test: build → analyze → verify tasks generated.

**Reasoning:**
The primary workflow must produce correct results.

**Implementation Steps:**
1. Build on sample project (with known issues)
2. Run analyze
3. Verify tasks match known issues:
   - Known orphan → orphan task
   - Known missing call → policy violation task
   - Known untested function → coverage gap task
4. Verify task priorities and context

**Files:**
- `tests/test_integration.py` (modify)

**Dependencies:** O-020, N-017

**Validation:**
- Known issues detected
- Correct task types generated
- No false positives

---

### TASK O-022 — Implement Integration Test: Delta Pipeline

**Description:**
End-to-end test: build → modify file → delta → verify incremental update.

**Reasoning:**
Delta must correctly detect and process changes.

**Implementation Steps:**
1. Build on sample project
2. Modify a function in sample project
3. Run delta
4. Verify:
   - Changed file detected
   - Node body_hash updated
   - Stale intent flagged (if intent exists)
   - graph_version incremented
   - Workflow edges updated

**Files:**
- `tests/test_integration.py` (modify)

**Dependencies:** O-020, N-009

**Validation:**
- Delta detects modification
- Graph updated correctly
- Version incremented

---

### TASK O-023 — Implement Integration Test: Apply Pipeline

**Description:**
End-to-end test: build → analyze → generate mock agent response → apply → verify changes.

**Reasoning:**
The apply system is the most dangerous — it modifies code. Must work perfectly.

**Implementation Steps:**
1. Build and analyze sample project
2. Create valid agent_response.json with connect_call action
3. Run apply
4. Verify:
   - Call inserted in correct location
   - Import added if needed
   - File still parses
   - Graph_1 updated
5. Run `codegraph validate` → no issues

**Files:**
- `tests/test_integration.py` (modify)

**Dependencies:** O-020, N-008

**Validation:**
- Apply modifies code correctly
- File remains valid Python
- Validate passes after apply

---

### TASK O-024 — Implement Integration Test: Query System

**Description:**
End-to-end test for all query types on built graph.

**Reasoning:**
Queries must return correct results on real graph data.

**Implementation Steps:**
1. Build sample project
2. Test each query:
   - `callers("known_function")` → known callers
   - `callees("known_function")` → known callees
   - `path("A", "B")` → known path
   - `orphans()` → known orphans
   - `layer(4)` → known test functions

**Files:**
- `tests/test_integration.py` (modify)

**Dependencies:** O-020, N-006

**Validation:**
- All queries return correct results
- Results match known characteristics

---

### TASK O-025 — Implement Performance Benchmark Suite

**Description:**
Create performance benchmarks for critical operations.

**Reasoning:**
Performance regressions must be detected early.

**Implementation Steps:**
1. Generate synthetic projects: 100, 1000, 10000 functions
2. Benchmark:
   - Build time
   - Delta time (10% changed)
   - Query time (callers, path)
   - Index build time
   - Analyze time
3. Set regression thresholds

**Files:**
- `benchmarks/` (directory)
- `benchmarks/benchmark_build.py`
- `benchmarks/benchmark_query.py`

**Dependencies:** O-020

**Validation:**
- Benchmarks run without error
- Results within expected bounds
- Regression detection works

---

### TASK O-026 — Implement Test Coverage Reporting

**Description:**
Configure coverage reporting to track test coverage of codegraph itself.

**Reasoning:**
Practice what we preach: codegraph should have high test coverage.

**Implementation Steps:**
1. Configure coverage.py in pyproject.toml
2. Set minimum coverage: 80% line, 70% branch
3. Generate HTML coverage report
4. Fail CI if below threshold
5. Exclude test files and benchmarks from coverage

**Files:**
- `pyproject.toml` (modify)

**Dependencies:** O-001

**Validation:**
- Coverage report generated
- Thresholds enforced
- HTML report viewable

---

### TASK O-027 — Implement CI/CD Configuration

**Description:**
Set up GitHub Actions CI workflow for automated testing.

**Reasoning:**
Every PR should be automatically tested.

**Implementation Steps:**
1. Create `.github/workflows/test.yml`
2. Matrix: Python 3.9, 3.10, 3.11, 3.12
3. Steps: install deps, lint, type check, test, coverage
4. Fail on: test failure, coverage below threshold, lint errors
5. Cache pip dependencies

**Files:**
- `.github/workflows/test.yml`

**Dependencies:** O-001, O-026

**Validation:**
- CI runs on push and PR
- All matrix versions tested
- Failures reported clearly

---

### TASK O-028 — Implement Linting Configuration

**Description:**
Configure code quality tools: ruff, mypy, black.

**Reasoning:**
Consistent code quality across the codebase.

**Implementation Steps:**
1. Configure ruff in `pyproject.toml`
2. Configure mypy in `pyproject.toml` (strict mode)
3. Configure black in `pyproject.toml`
4. Add pre-commit hooks
5. Fix all initial linting issues

**Files:**
- `pyproject.toml` (modify)
- `.pre-commit-config.yaml`

**Dependencies:** A-002

**Validation:**
- No ruff errors
- No mypy errors
- Black formatted

---

### TASK O-029 — Implement Property-Based Tests for Core Models

**Description:**
Use hypothesis to generate random inputs for model validation.

**Reasoning:**
Property-based testing finds edge cases that hand-written tests miss.

**Implementation Steps:**
1. Install hypothesis
2. Test properties:
   - Node ID roundtrip: parse → serialize → parse = identity
   - Body hash determinism: same input → same hash
   - Edge merging: merge is commutative and associative
   - Filter pipeline: filtered edges ⊂ input edges
3. Custom strategies for generating valid model data

**Files:**
- `tests/test_properties.py`

**Dependencies:** B-001, C-010, F-013

**Validation:**
- No property violations found
- Strategies generate diverse inputs

---

### TASK O-030 — Implement Snapshot Tests for JSON Output

**Description:**
Use snapshot testing to verify JSON output stability.

**Reasoning:**
JSON schemas consumed by agents must be stable. Any unintended change breaks agent compatibility.

**Implementation Steps:**
1. Install pytest-snapshot or syrupy
2. Create snapshots for:
   - graph0.json structure
   - graph1.json structure
   - workflow.json structure
   - tasks.json structure
   - agent_response.json structure
3. Update snapshots intentionally when format changes

**Files:**
- `tests/test_snapshots.py`
- `tests/snapshots/` (directory)

**Dependencies:** O-002

**Validation:**
- Snapshot tests pass
- Format changes detected
- Intentional updates documented

---

### TASK O-031 — Implement Mutation Testing Analysis

**Description:**
Run mutation testing to verify test quality.

**Reasoning:**
Tests that pass on mutated code aren't actually testing anything.

**Implementation Steps:**
1. Install mutmut
2. Run mutation testing on core modules
3. Analyze surviving mutants
4. Add tests to kill high-value surviving mutants
5. Target: > 70% mutation score on core modules

**Files:**
- `pyproject.toml` (modify for mutmut config)

**Dependencies:** O-004 through O-018

**Validation:**
- Mutation testing runs
- Score above threshold
- Key mutants killed

---

### TASK O-032 — Implement Fuzz Testing for Parser Inputs

**Description:**
Fuzz test the query parser and JSON loaders with random/malformed input.

**Reasoning:**
Parsers must handle arbitrary input without crashing.

**Implementation Steps:**
1. Fuzz test query parser with random strings
2. Fuzz test JSON loaders with malformed JSON
3. Fuzz test node ID parser with Unicode/special characters
4. Ensure: no crashes, clear error messages

**Files:**
- `tests/test_fuzz.py`

**Dependencies:** L-001

**Validation:**
- No crashes on random input
- Error messages for invalid input
