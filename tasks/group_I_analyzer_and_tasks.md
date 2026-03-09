# Group I — Analyzer & Task System

> Orphan analysis, policy diff integration, task generation, priority ordering, task batching, convergence tracking, and repair loop via `analyzer.py` and `tasks.py`.

---

### TASK I-001 — Implement Analyzer Core Engine

**Description:**
Create the core analyzer that compares Graph_0, Graph_1, workflow, and suggested_workflow to produce actionable findings.

**Reasoning:**
The analyzer is the brain of codegraph. It detects all structural issues and policy violations that need attention.

**Implementation Steps:**
1. Create `codegraph/analyzer.py`
2. Implement `analyze(project_root, graph0, graph1, workflow, suggested_workflow, index) -> AnalysisResult`
3. Orchestrate: orphan detection, policy diff, stale intent detection, coverage gap detection
4. Return structured AnalysisResult with all findings

**Files:**
- `codegraph/analyzer.py`

**Dependencies:** F-021, H-010, E-005, G-011

**Validation:**
- All finding types produced
- No false positives on clean codebase
- Findings match manual inspection

**CAS Integration Note:**
When CAS is available, analyzer accepts an optional `affected_nodes: set[str]` parameter from CAS propagation (Q-007). When provided, analysis is scoped to only the affected node set — orphan checks, policy violations, stale intents, and coverage gaps are evaluated only for affected nodes. This dramatically reduces analysis time for incremental deltas. See Q-014 for full details.

---

### TASK I-002 — Implement Orphan Node Analysis

**Description:**
Analyze orphan nodes (no edges) and classify them by type and likely cause.

**Reasoning:**
Orphans may be dead code, new code, or entry points. Classification helps agents prioritize.

**Implementation Steps:**
1. Implement `classify_orphans(orphans: list[str], graph0, graph1) -> list[ClassifiedOrphan]`
2. Classification:
   - `entry_point`: has `__main__`, CLI decorator, test prefix → not a problem
   - `dead_code`: no callers, no tests, not an entry point → likely delete candidate
   - `new_code`: recently added (body_hash new) → needs integration
   - `disconnected`: has intent but no edges → needs workflow attention

**Files:**
- `codegraph/analyzer.py` (modify)

**Dependencies:** I-001, F-021

**Edge Cases:**
- Factory functions called dynamically → appear orphan but aren't
- Callback functions → need dynamic edge to not be orphan
- Module-level code → not a function, different classification

**Validation:**
- Entry points correctly classified
- Dead code candidates identified
- New code without edges flagged

---

### TASK I-003 — Implement Stale Intent Detection

**Description:**
Find nodes where body_hash has changed since the intent was applied, meaning the intent may be outdated.

**Reasoning:**
When code changes but intent stays the same, the intent may no longer accurately describe the function. This is the "stale intent" detection described in the README.

**Implementation Steps:**
1. Implement `find_stale_intents(graph0, graph1) -> list[StaleIntent]`
2. For each Graph_1 node with an intent:
   - Compare Graph_1's stored body_hash with Graph_0's current body_hash
   - If different → stale
3. Return list with node_id, old_hash, new_hash, current_intent

**Files:**
- `codegraph/analyzer.py` (modify)

**Dependencies:** I-001, E-005

**Validation:**
- Changed function with old intent → stale detected
- Unchanged function → not stale
- No intent set → not checked

---

### TASK I-004 — Implement Coverage Gap Detection

**Description:**
Find production functions (Layer 3) that have no test coverage.

**Reasoning:**
Uncovered functions are a testing gap that should be reported as tasks for the agent.

**Implementation Steps:**
1. Implement `find_coverage_gaps(graph0, graph1, workflow, index) -> list[CoverageGap]`
2. For each Layer 3 function:
   - Check if any Layer 4 test function has an edge to it
   - Check tests index for test associations
3. Functions with no test coverage → coverage gap

**Files:**
- `codegraph/analyzer.py` (modify)

**Dependencies:** I-001, G-006, D-007

**Edge Cases:**
- Internal utility functions → may not need individual tests
- Entry points tested via integration → partial coverage
- Dynamic dispatch → hard to detect test coverage

**Validation:**
- Untested functions detected
- Tested functions not flagged

---

### TASK I-005 — Implement Missing Intent Detection

**Description:**
Find nodes that exist in Graph_0 but have no intent in Graph_1.

**Reasoning:**
README's `intent-missing` command lists nodes without intent annotations. These need documentation.

**Implementation Steps:**
1. Implement `find_missing_intents(graph0, graph1) -> list[str]`
2. Compare Graph_0 node IDs with Graph_1 node IDs
3. Nodes in Graph_0 but not in Graph_1 → missing
4. Filter by layer (only report Layer 3+4)

**Files:**
- `codegraph/analyzer.py` (modify)

**Dependencies:** I-001, B-002, B-004

**Validation:**
- Unannotated nodes detected
- Annotated nodes not flagged
- Layer 0/1/2 nodes excluded

---

### TASK I-006 — Implement Policy Violation Integration

**Description:**
Integrate the suggested workflow policy diff into the analyzer.

**Reasoning:**
Policy violations from suggested_workflow.json are a primary task source.

**Implementation Steps:**
1. Call `policy_diff()` from H-020 within analyzer
2. Convert violations to analysis findings
3. Include violation details: which rule, which nodes, which missing/forbidden edges
4. Add rule severity to finding priority

**Files:**
- `codegraph/analyzer.py` (modify)

**Dependencies:** I-001, H-020

**Validation:**
- All violations from policy diff appear in analysis
- Severity levels preserved

---

### TASK I-007 — Implement Task Generation Engine

**Description:**
Convert analysis findings into structured task items for the agent queue.

**Reasoning:**
This is the core function of `tasks.py`. Each finding becomes a prioritized, actionable task.

**Implementation Steps:**
1. Create `codegraph/tasks.py`
2. Implement `generate_tasks(analysis: AnalysisResult, graph0, graph1, workflow) -> TaskBatch`
3. For each finding:
   - Create TaskItem with unique task_id
   - Assign priority based on finding type
   - Generate suggested_fix hint
   - Include pre-fetched context
4. Return TaskBatch with graph_version

**Files:**
- `codegraph/tasks.py`

**Dependencies:** I-001, B-010

**Validation:**
- Every finding produces a task
- Tasks have correct priorities
- TaskBatch has graph_version

---

### TASK I-008 — Implement Task Priority Assignment

**Description:**
Assign priorities to tasks using the README's priority scheme.

**Reasoning:**
README defines: `policy_violation=1`, `missing_edge=2`, `orphan_code=3`, `missing_intent=4`, `coverage_gap=5`, `stale_intent=6`.

**Implementation Steps:**
1. Implement `assign_priority(finding_type: str) -> int`
2. Priority mapping:
   - 1: policy_violation
   - 2: missing_edge
   - 3: orphan_code
   - 4: missing_intent
   - 5: coverage_gap
   - 6: stale_intent
3. Unknown types → priority 99

**Files:**
- `codegraph/tasks.py` (modify)

**Dependencies:** I-007

**Validation:**
- Each type maps to correct priority
- Tasks sorted by priority in output

---

### TASK I-009 — Implement Task Pre-Fetched Context

**Description:**
Populate each task with pre-fetched graph context so agent doesn't need separate queries.

**Reasoning:**
README states tasks include pre-fetched context: callers, callees, current intent, layer, relevant code.

**Implementation Steps:**
1. Implement `fetch_task_context(task: TaskItem, index, graph0, graph1) -> TaskContext`
2. For each task's target node(s):
   - Fetch callers (from index)
   - Fetch callees (from index)
   - Fetch current intent (from Graph_1)
   - Fetch layer
   - Fetch body hash
   - Fetch source code snippet (first/last few lines)

**Files:**
- `codegraph/tasks.py` (modify)

**Dependencies:** I-007, G-011

**Validation:**
- Context populated for each task
- Missing data handled gracefully
- Context matches graph state

---

### TASK I-010 — Implement Suggested Fix Generator

**Description:**
Generate code-level fix suggestions for each task type.

**Reasoning:**
README mentions `suggested_fix` hints. These are code-level suggestions (e.g., "add `audit_log.log_access(user)` as first statement").

**Implementation Steps:**
1. Implement `generate_suggested_fix(task: TaskItem, context: TaskContext) -> str`
2. By task type:
   - policy_violation (required_call): "Add call to {target} at first executable statement of {source}"
   - policy_violation (forbidden_call): "Remove call to {target} from {source}"
   - orphan_code: "Connect to callers or mark as dead code"
   - missing_intent: "Add intent annotation describing purpose"
   - coverage_gap: "Create test function testing {node}"
   - stale_intent: "Review and update intent to match current behavior"

**Files:**
- `codegraph/tasks.py` (modify)

**Dependencies:** I-007

**Validation:**
- Each task type produces a hint
- Hints reference specific node IDs
- Hints are actionable

---

### TASK I-011 — Implement Task Batch Writer

**Description:**
Write the complete task batch to `tasks.json`.

**Reasoning:**
The task batch is the output consumed by the agent. Must include all metadata and be atomically written.

**Implementation Steps:**
1. Implement `write_tasks(batch: TaskBatch, project_root)`
2. Serialize to JSON
3. Include graph_version in header
4. Atomic write (write to temp, rename)
5. Store at `.codegraph/tasks/tasks.json`

**Files:**
- `codegraph/tasks.py` (modify)

**Dependencies:** I-007, A-013

**Validation:**
- Valid JSON written
- graph_version present
- Atomic write works

---

### TASK I-012 — Implement Task Batch Loader

**Description:**
Load existing tasks.json for display and processing.

**Reasoning:**
`codegraph tasks` needs to read and display existing tasks.

**Implementation Steps:**
1. Implement `load_tasks(project_root) -> TaskBatch`
2. Parse and validate JSON
3. Check graph_version against current
4. Stale tasks (old version) → mark as potentially stale

**Files:**
- `codegraph/tasks.py` (modify)

**Dependencies:** B-010

**Validation:**
- Tasks load correctly
- Version mismatch detected and reported

---

### TASK I-013 — Implement Agent Response Parser

**Description:**
Parse the agent's response JSON (agent_response.json) that contains actions for each task.

**Reasoning:**
Agents submit responses to tasks. The response must be validated against the expected schema.

**Implementation Steps:**
1. Implement `parse_agent_response(project_root) -> AgentResponse`
2. Validate JSON structure against B-011 schema
3. Validate graph_version matches current → reject if stale
4. Validate each action is a valid RepairActionType
5. Return structured AgentResponse

**Files:**
- `codegraph/tasks.py` (modify)

**Dependencies:** B-011, B-012

**Edge Cases:**
- Missing graph_version → reject
- Wrong graph_version → reject (README: "The system rejects any response whose echo does not match the current graph_version.")
- Unknown action type → reject that action, process others
- Malformed JSON → clear error

**Validation:**
- Valid response parses correctly
- Version mismatch rejected
- Invalid actions reported individually

---

### TASK I-014 — Implement Version Staleness Check

**Description:**
Implement the graph_version validation that ensures agent responses are not stale.

**Reasoning:**
README states: "version mismatch — agent submits a response with an old graph_version. The system rejects any response whose echo does not match."

**Implementation Steps:**
1. Implement `validate_version(response_version: int, current_version: int) -> bool`
2. If response_version != current_version → reject
3. Return clear error message with both versions
4. Agent must re-read tasks with new version

**Files:**
- `codegraph/tasks.py` (modify)

**Dependencies:** A-012, I-013

**Validation:**
- Matching versions → accepted
- Stale version → rejected with message

---

### TASK I-015 — Implement Task Filtering by Type

**Description:**
Support filtering tasks by type for `codegraph tasks --filter type=policy_violation`.

**Reasoning:**
Users may want to see only certain task types.

**Implementation Steps:**
1. Implement task filtering in task display:
   - By type: policy_violation, missing_edge, orphan, missing_intent, coverage_gap, stale_intent
   - By priority: show only priority ≤ N
   - By node: show tasks for specific node
2. Return filtered list

**Files:**
- `codegraph/tasks.py` (modify)

**Dependencies:** I-012

**Validation:**
- Filtering produces correct subset
- Empty filter → all tasks

---

### TASK I-016 — Implement Test Impact Integration in Tasks

**Description:**
Include affected test information in tasks where relevant.

**Reasoning:**
README states tasks include affected tests so agents know which tests to verify after making changes.

**Implementation Steps:**
1. For each task involving a code change:
   - Query tests index for test functions that cover the target node
   - Include affected_tests in task context
2. For tasks involving new code:
   - No affected tests (yet)
3. For tasks involving removed code:
   - Tests that will break → critical info

**Files:**
- `codegraph/tasks.py` (modify)

**Dependencies:** I-007, G-006

**Validation:**
- Affected tests populated for existing nodes
- Empty for new nodes
- Breaking tests highlighted

---

### TASK I-017 — Implement Task Deduplication

**Description:**
Prevent duplicate tasks for the same issue.

**Reasoning:**
Multiple analysis passes may detect the same issue. Deduplication ensures clean task list.

**Implementation Steps:**
1. Implement `deduplicate_tasks(tasks: list[TaskItem]) -> list[TaskItem]`
2. Define equality: same target_node + same task_type + same action
3. Keep highest priority version if duplicates differ
4. Log deduplication count

**Files:**
- `codegraph/tasks.py` (modify)

**Dependencies:** I-007

**Validation:**
- Duplicate tasks removed
- Unique tasks preserved
- Highest priority kept

---

### TASK I-018 — Implement Convergence Tracker

**Description:**
Track convergence metrics across repair loop iterations.

**Reasoning:**
README defines convergence criteria: "orphan count stagnant 3 iterations, total edge count stabilized ±5%, max iterations reached (default 10), or remaining actions are all flag_for_human_review."

**Implementation Steps:**
1. Implement `ConvergenceTracker` class in `codegraph/analyzer.py`
2. Track per iteration: orphan count, edge count, task count, action types
3. Implement convergence checks:
   - `is_orphan_stagnant() -> bool` (same count 3 iterations)
   - `is_edge_stabilized() -> bool` (±5% of previous)
   - `is_max_iterations() -> bool` (default 10)
   - `is_all_human_review() -> bool` (remaining tasks all human review)
4. `should_stop() -> bool` combining all criteria

**Files:**
- `codegraph/analyzer.py` (modify)

**Dependencies:** I-001

**Validation:**
- Convergence detected correctly for each criterion
- History tracked across iterations
- Stop conditions combine correctly

---

### TASK I-019 — Implement Repair Loop Orchestrator

**Description:**
Implement the full repair loop: analyze → generate tasks → agent response → apply → delta → repeat.

**Reasoning:**
The repair loop is the automated workflow for continuous improvement. It runs until convergence.

**Implementation Steps:**
1. Implement `repair_loop(project_root, max_iterations=10) -> RepairResult`
2. Loop:
   a. Run analyzer
   b. Generate tasks
   c. Wait for agent response (or simulate)
   d. Apply changes
   e. Run delta
   f. Check convergence
3. Log each iteration's metrics
4. Return final state and iteration history

**Files:**
- `codegraph/analyzer.py` (modify)

**Dependencies:** I-018, I-007, J-001, K-001

**Validation:**
- Loop converges on test case
- Max iterations respected
- History captured

---

### TASK I-020 — Implement Analysis Caching

**Description:**
Cache analysis results to avoid re-computation when graph hasn't changed.

**Reasoning:**
Analysis can be expensive for large codebases. If the graph version hasn't changed, reuse previous results.

**Implementation Steps:**
1. Implement `AnalysisCache` keyed by graph_version
2. Store analysis results in `.codegraph/cache/`
3. Check cache before running analysis
4. Invalidate on graph_version change

**Files:**
- `codegraph/analyzer.py` (modify)

**Dependencies:** I-001, A-012

**Validation:**
- Cache hit returns previous results
- Version change invalidates cache
- Cache miss triggers fresh analysis

---

### TASK I-021 — Implement Task Statistics Summary

**Description:**
Generate summary statistics for the current task batch.

**Reasoning:**
`codegraph status` needs task counts. Detailed breakdown by type and priority helps assess project health.

**Implementation Steps:**
1. Implement `task_statistics(batch: TaskBatch) -> TaskStats`
2. Report: total tasks, by type, by priority, completion rate
3. Include in status output

**Files:**
- `codegraph/tasks.py` (modify)

**Dependencies:** I-012

**Validation:**
- Counts match actual tasks
- All types and priorities accounted for

---

### TASK I-022 — Implement Task Completion Tracking

**Description:**
Track which tasks have been completed by agent responses.

**Reasoning:**
After an agent response is applied, the completed tasks should be marked. This helps with progress tracking.

**Implementation Steps:**
1. Add `completed_at`, `completed_by_version` fields to TaskItem
2. After apply, mark tasks addressed by the response
3. Preserve completed tasks in history
4. Active tasks = uncompleted tasks

**Files:**
- `codegraph/tasks.py` (modify)

**Dependencies:** I-007, B-010

**Validation:**
- Completed tasks marked
- Active count reflects uncompleted

---

### TASK I-023 — Implement Analyzer Edge Case: Cycle Mismatch

**Description:**
Detect when the workflow graph contains cycles that are NOT present in the suggested workflow.

**Reasoning:**
README failure mode: "cycle mismatch — actual workflow has a cycle that the suggested workflow either requires or forbids."

**Implementation Steps:**
1. Implement `detect_cycle_mismatches(workflow, suggested) -> list[CycleMismatch]`
2. Find cycles in actual workflow graph (use DFS cycle detection)
3. Check if any cycle involves nodes that have suggested rules
4. Report mismatches

**Files:**
- `codegraph/analyzer.py` (modify)

**Dependencies:** I-001, F-019, H-010

**Edge Cases:**
- Self-referencing node (recursion) → single-node cycle
- Large cycle (10+ nodes) → report, don't enumerate all paths

**Validation:**
- Known cycles detected
- Cycle-free graphs pass
- Suggested rule interactions flagged

---

### TASK I-024 — Implement Batch Context Optimization

**Description:**
Optimize pre-fetched context to minimize redundant graph queries across tasks in a batch.

**Reasoning:**
Multiple tasks may reference the same nodes. Batch-fetching context reduces query count.

**Implementation Steps:**
1. Collect all unique node IDs across all tasks in batch
2. Batch-query callers, callees, intents for all nodes at once
3. Distribute results to individual tasks
4. Reduce total queries from O(tasks × queries-per-task) to O(unique-nodes)

**Files:**
- `codegraph/tasks.py` (modify)

**Dependencies:** I-009, G-011

**Validation:**
- Same results as individual fetches
- Fewer total queries
- Performance improvement measurable

---

### TASK I-025 — Implement Analysis Report Formatter

**Description:**
Format the complete analysis report for CLI display with sections and summaries.

**Reasoning:**
The analyze command output must be human-readable with clear sections: violations, orphans, gaps, stale intents.

**Implementation Steps:**
1. Implement `format_analysis_report(analysis: AnalysisResult) -> str`
2. Sections: Summary, Policy Violations, Orphan Nodes, Coverage Gaps, Stale Intents, Missing Intents
3. Include counts and specific listings
4. Support `--json` for machine-readable output

**Files:**
- `codegraph/analyzer.py` (modify)

**Dependencies:** I-001

**Validation:**
- All sections present
- Counts accurate
- JSON output parses correctly

---

### TASK I-026 — Implement Missing Edge Detection

**Description:**
Detect edges that should exist based on code patterns but don't appear in the workflow graph.

**Reasoning:**
Beyond policy violations, there are structural patterns that suggest missing edges (e.g., a factory function that creates but never returns objects).

**Implementation Steps:**
1. Implement `detect_missing_edges(workflow, graph0) -> list[MissingEdge]`
2. Patterns:
   - Function creates an object of type X but never calls X methods → expected edge
   - Function imports module but never calls any of its functions
   - init calls super().__init__ pattern → verify edge exists
3. Keep heuristic-based, clearly mark as suggestions

**Files:**
- `codegraph/analyzer.py` (modify)

**Dependencies:** I-001, F-019

**Validation:**
- Obvious missing edges detected
- False positive rate acceptable
- Clearly marked as heuristic

---

### TASK I-027 — Implement Task JSON Schema Validation

**Description:**
Create and enforce a JSON schema for tasks.json.

**Reasoning:**
Agents must submit correctly formatted responses. The schema defines the contract.

**Implementation Steps:**
1. Define JSON Schema for tasks.json
2. Define JSON Schema for agent_response.json
3. Validate both files against schemas on load
4. Clear errors on schema violations

**Files:**
- `codegraph/schemas/tasks_schema.json`
- `codegraph/schemas/agent_response_schema.json`
- `codegraph/tasks.py` (modify)

**Dependencies:** A-015, B-010, B-011

**Validation:**
- Valid files pass schema
- Invalid files produce clear errors

---

### TASK I-028 — Implement Task History Log

**Description:**
Maintain a history of all task batches and their outcomes.

**Reasoning:**
History enables trend analysis (are violations decreasing?) and debugging (what did the agent do in iteration 3?).

**Implementation Steps:**
1. Implement `TaskHistory` stored at `.codegraph/tasks/history.json`
2. After each apply, append: batch summary, agent actions, outcome
3. Limit history size (configurable, default 50 iterations)
4. Support `codegraph tasks --history` display

**Files:**
- `codegraph/tasks.py` (modify)

**Dependencies:** I-011

**Validation:**
- History grows after each apply
- Size limit enforced
- History display works

---

### TASK I-029 — Implement Parallel Analysis Optimization

**Description:**
Run independent analysis checks in parallel for performance on large codebases.

**Reasoning:**
Orphan detection, policy diff, coverage gaps, and stale intents are independent and can run concurrently.

**Implementation Steps:**
1. Use `concurrent.futures.ThreadPoolExecutor` or `ProcessPoolExecutor`
2. Run independent checks in parallel:
   - Orphan detection (reads workflow)
   - Policy diff (reads suggested + workflow)
   - Coverage gaps (reads tests index)
   - Stale intent (reads graph0 + graph1)
3. Merge results

**Files:**
- `codegraph/analyzer.py` (modify)

**Dependencies:** I-001

**Validation:**
- Same results as sequential
- Performance improvement on multi-core
- Thread safety verified

---

### TASK I-030 — Implement Full Analyze Command Orchestrator

**Description:**
Create the top-level analyze function called by `codegraph analyze`.

**Reasoning:**
This orchestrates the complete analysis pipeline from loading graphs to producing tasks.

**Implementation Steps:**
1. Implement `run_analyze(project_root, options) -> TaskBatch`
2. Steps:
   a. Load Graph_0, Graph_1, Workflow, Suggested Workflow
   b. Load or build index
   c. Run all analyses
   d. Generate tasks from findings
   e. Write tasks.json
   f. Display summary
3. Handle missing files gracefully

**Files:**
- `codegraph/analyzer.py` (modify)

**Dependencies:** I-001, I-007, I-011

**Validation:**
- Full pipeline runs end-to-end
- Missing files produce helpful errors
- Tasks written correctly
---

### TASK I-031 — Integrate Graph_2 Semantic Data into Analyzer

**Description:**
Extend the analyzer core engine (I-001) to accept Graph_2 data and incorporate semantic findings into analysis results.

**Reasoning:**
The analyzer must consume Graph_2 to produce semantic-aware orphan classification (R-023), behavior-change stale detection (R-024), safety impact assessments (R-030), and semantic-enriched task context (R-037).

**Implementation Steps:**
1. Update `analyze()` signature to accept optional `graph2: Graph2`
2. When Graph_2 available:
   a. Use `classify_orphan_semantic()` (R-023) for enhanced orphan classification
   b. Use `detect_semantic_stale()` (R-024) for precise stale intent detection
   c. Use `assess_safety()` (R-030) before action recommendations
   d. Add semantic context to generated tasks (R-037)
3. When Graph_2 unavailable → fall back to existing structural analysis (no degradation)

**Files:**
- `codegraph/analyzer.py` (modify)

**Dependencies:** R-017, R-023, R-024, R-030, R-037, I-001

**Validation:**
- Analyzer uses Graph_2 when available
- Falls back gracefully when Graph_2 missing
- Semantic-enhanced findings more precise than structural-only

---

### TASK I-032 — Add Semantic Dead Code Verdict to Orphan Pipeline

**Description:**
Wire the semantic dead code analysis (R-029) into the orphan detection pipeline so dangerous orphans are not auto-removed.

**Reasoning:**
Event handlers, middleware, and dynamically invoked code appear as orphans structurally but have semantic survival signals. The verdict system (SAFE_TO_REMOVE, SUSPICIOUS, DANGEROUS) prevents automated deletion of critical code.

**Implementation Steps:**
1. After structural orphan classification, run `semantic_dead_code_check()` (R-029) on each orphan
2. Override `remove_dead_code` action to `flag_for_human_review` for DANGEROUS verdicts
3. Add verdict to task output so agents see why a node was flagged
4. Log: "N orphans reclassified by semantic analysis (X dangerous, Y suspicious)"

**Files:**
- `codegraph/analyzer.py` (modify)

**Dependencies:** R-029, I-002, I-030

**Validation:**
- DANGEROUS orphans flagged for human review
- SAFE_TO_REMOVE orphans still auto-removable
- SUSPICIOUS orphans get cautionary task description