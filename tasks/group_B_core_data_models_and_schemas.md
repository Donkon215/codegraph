# Group B — Core Data Models & Schemas

> All data structures, JSON schemas, type definitions, and serialization logic for Graph_0, Graph_1, Workflow, Suggested Workflow, Tasks, Delta, and Agent Response.

---

### TASK B-001 — Define Graph0Node Data Model

**Description:**
Implement the Graph_0 node data model as a Python dataclass/TypedDict representing AST-extracted structural nodes.

**Reasoning:**
Graph_0 is the foundation of the entire system. Every other component reads from it. The data model must exactly match the JSON schema in the README.

**Implementation Steps:**
1. Create `codegraph/models/__init__.py` package
2. Create `codegraph/models/graph0.py`
3. Define `Graph0Node` dataclass:
   - `id: str` — stable node identifier
   - `body_hash: str` — AST body fingerprint
   - `file: str` — relative path to source file
   - `type: str` — one of: function, class, method, module
   - `line: int` — line number (display only)
4. Implement `to_dict()` and `from_dict()` serialization
5. Implement `__eq__` based on `id` field only
6. Implement `__hash__` based on `id` field only

**Files:**
- `codegraph/models/__init__.py`
- `codegraph/models/graph0.py`

**Dependencies:** A-017

**Edge Cases:**
- Node with no line number (module-level)
- Node type validation (reject unknown types)
- Empty body_hash for module nodes

**Validation:**
- Create node from dict and serialize back → identical
- Two nodes with same id are equal regardless of other fields
- Invalid type raises ValueError

---

### TASK B-002 — Define Graph0 Collection Model

**Description:**
Implement the Graph_0 collection model that holds all nodes plus metadata (version, timestamp, source file list).

**Reasoning:**
Graph_0 is not just a list of nodes — it has metadata header fields including `graph_version`. The collection model manages the entire file.

**Implementation Steps:**
1. Define `Graph0` dataclass in `codegraph/models/graph0.py`:
   - `graph_version: int`
   - `format_version: int = 1`
   - `extracted_at: str` (ISO 8601)
   - `source_files: list[str]`
   - `nodes: list[Graph0Node]`
2. Implement `to_json()` and `from_json()` for file I/O
3. Implement `get_node(node_id) -> Optional[Graph0Node]`
4. Implement `add_node(node)`, `remove_node(node_id)`
5. Implement `get_nodes_by_file(file_path) -> list[Graph0Node]`

**Files:**
- `codegraph/models/graph0.py` (modify)

**Dependencies:** B-001

**Edge Cases:**
- Duplicate node IDs (collision handling)
- Empty graph (no source files)
- Very large graph (10k+ nodes) — consider dict lookup

**Validation:**
- Round-trip JSON serialization preserves all data
- Node lookup by ID is O(1)
- File-based filtering returns correct subset

---

### TASK B-003 — Define Graph1Node Data Model

**Description:**
Implement the Graph_1 metadata overlay node data model with intent, layer, tags, and architectural layer.

**Reasoning:**
Graph_1 is the semantic metadata layer that agents read and write. It references Graph_0 nodes by ID and holds no structural edges.

**Implementation Steps:**
1. Create `codegraph/models/graph1.py`
2. Define `Graph1Node` dataclass:
   - `id: str` — must match a Graph_0 node ID
   - `intent: str` — agent/human description
   - `layer: int` — 0-4
   - `arch_layer: Optional[str]` — logical architecture role
   - `intent_author: str` — who wrote the intent
   - `intent_version: int` — increments on each update
   - `intent_timestamp: str` — ISO 8601
   - `tags: list[str]` — optional domain tags
3. Implement `to_dict()` and `from_dict()`
4. Implement `update_intent(new_intent, author)` that increments version and updates timestamp

**Files:**
- `codegraph/models/graph1.py`

**Dependencies:** A-017

**Edge Cases:**
- Node with no intent yet (intent might be empty/None)
- Tags list empty vs missing
- arch_layer is optional — None is valid
- intent_version starts at 1 on first annotation

**Validation:**
- `update_intent` increments version
- `update_intent` updates timestamp
- Serialization round-trip preserves all fields

---

### TASK B-004 — Define Graph1 Collection Model

**Description:**
Implement the Graph_1 collection model that manages all metadata overlay nodes.

**Reasoning:**
Graph_1 persists across rebuilds and must be merged carefully with Graph_0. The collection must handle additions, updates, and pruning of stale entries.

**Implementation Steps:**
1. Define `Graph1` dataclass in `codegraph/models/graph1.py`:
   - `format_version: int = 1`
   - `nodes: list[Graph1Node]`
2. Implement `to_json()` and `from_json()`
3. Implement `get_node(node_id) -> Optional[Graph1Node]`
4. Implement `upsert_node(node)` — insert or update
5. Implement `remove_node(node_id)`
6. Implement `get_nodes_missing_intent() -> list[str]` (nodes with empty/None intent)
7. Implement `get_stale_nodes(graph0: Graph0) -> list[str]` (nodes not in Graph_0)

**Files:**
- `codegraph/models/graph1.py` (modify)

**Dependencies:** B-003, B-002

**Edge Cases:**
- Upserting an existing node increments version
- Pruning removes nodes not in Graph_0
- Graph_1 may have fewer nodes than Graph_0 (not all annotated)

**Validation:**
- Upsert creates new node if not exists
- Upsert updates existing node and increments version
- Stale detection works against Graph_0

---

### TASK B-005 — Define WorkflowEdge Data Model

**Description:**
Implement the Workflow edge data model representing call relationships between nodes.

**Reasoning:**
Workflow edges are the core behavior graph. They carry source, target, type, and confidence information from multiple sources.

**Implementation Steps:**
1. Create `codegraph/models/workflow.py`
2. Define `WorkflowEdge` dataclass:
   - `source: str` — originating node ID
   - `target: str` — destination node ID or `<scope>::*` for dynamic
   - `edge_type: str` — one of: call, test, trace, dynamic
   - `confidence: str` — one of: runtime, test, static, ai_inferred
3. Implement `to_dict()` and `from_dict()`
4. Implement `is_dynamic() -> bool` (target contains `::*`)
5. Implement `__eq__` based on (source, target, edge_type, confidence)

**Files:**
- `codegraph/models/workflow.py`

**Dependencies:** A-017

**Edge Cases:**
- Dynamic edge with wildcard target
- Same source/target with different edge_type/confidence (both preserved)
- Self-referencing edge (source == target) — recursive functions

**Validation:**
- Dynamic edge detection works
- Two edges with same source/target but different types are not equal
- Serialization round-trip preserves all fields

---

### TASK B-006 — Define Workflow Collection Model

**Description:**
Implement the Workflow collection that holds all edges plus metadata.

**Reasoning:**
The workflow graph is queried frequently by the index layer and analyzer. The collection must support efficient edge lookup by source and target.

**Implementation Steps:**
1. Define `Workflow` dataclass in `codegraph/models/workflow.py`:
   - `format_version: int = 1`
   - `built_at: str` (ISO 8601)
   - `level: str` — one of: function, class, module
   - `edges: list[WorkflowEdge]`
2. Implement `to_json()` and `from_json()`
3. Implement `get_edges_from(source_id) -> list[WorkflowEdge]`
4. Implement `get_edges_to(target_id) -> list[WorkflowEdge]`
5. Implement `add_edge(edge)`, `remove_edge(source, target)`
6. Implement `get_dynamic_edges() -> list[WorkflowEdge]`
7. Build internal indexes (source_map, target_map) on load

**Files:**
- `codegraph/models/workflow.py` (modify)

**Dependencies:** B-005

**Edge Cases:**
- Duplicate edges (same source/target/type/confidence) — prevent duplicates
- Very large edge sets (50k+) — O(1) lookup required
- Empty workflow (no edges)

**Validation:**
- Edge lookup by source is O(1)
- Edge lookup by target is O(1)
- Deduplication works
- Dynamic edges filtered correctly

---

### TASK B-007 — Define SuggestedWorkflowRule Data Model

**Description:**
Implement the data model for architecture policy rules stored in `suggested_workflow.json`.

**Reasoning:**
Policy rules are the enforcement mechanism for architecture constraints. They support exact node IDs, module paths, glob patterns, and layer numbers.

**Implementation Steps:**
1. Create `codegraph/models/suggested_workflow.py`
2. Define `SuggestedWorkflowRule` dataclass:
   - `id: str` — auto-assigned rule identifier
   - `type: str` — required_call or forbidden_call
   - `source: Optional[str]` — node ID, module path, or glob
   - `target: Optional[str]` — node ID, module path, or glob
   - `source_layer: Optional[int]` — match all nodes at layer
   - `target_layer: Optional[int]` — match all nodes at layer
   - `source_arch_layer: Optional[str]` — match by arch_layer annotation
   - `target_arch_layer: Optional[str]` — match by arch_layer annotation
   - `reason: str` — human-readable explanation
   - `added_by: str` — who added the rule
   - `added_at: str` — ISO 8601
3. Implement `to_dict()` and `from_dict()`
4. Implement validation: at least one of source/source_layer/source_arch_layer, same for target

**Files:**
- `codegraph/models/suggested_workflow.py`

**Dependencies:** A-017

**Edge Cases:**
- Rule with glob pattern → must be expanded later
- Rule with layer number → applies to many nodes
- Missing required fields → validation error
- Both source and source_layer specified → error or precedence?

**Validation:**
- Valid rule serializes and deserializes correctly
- Missing source raises validation error
- Both rule types (required/forbidden) are handled

---

### TASK B-008 — Define SuggestedWorkflow Collection Model

**Description:**
Implement the collection model for managing all architecture policy rules.

**Reasoning:**
The suggested workflow must support CRUD operations and persist across rebuilds. It is committed and shared.

**Implementation Steps:**
1. Define `SuggestedWorkflow` dataclass in `codegraph/models/suggested_workflow.py`:
   - `version: int = 1`
   - `rules: list[SuggestedWorkflowRule]`
2. Implement `to_json()` and `from_json()`
3. Implement `add_rule(rule) -> str` (returns auto-assigned ID)
4. Implement `remove_rule(rule_id)`
5. Implement `get_rule(rule_id) -> Optional[SuggestedWorkflowRule]`
6. Implement `list_rules() -> list[SuggestedWorkflowRule]`
7. Auto-generate rule IDs as `rule_NNN`

**Files:**
- `codegraph/models/suggested_workflow.py` (modify)

**Dependencies:** B-007

**Edge Cases:**
- Removing a rule that doesn't exist → warning
- Adding duplicate rule → error or skip
- Rule ID auto-increment after deletions

**Validation:**
- Add/remove/list operations work correctly
- Rule IDs are unique
- Persistence across save/load

---

### TASK B-009 — Define TaskItem Data Model

**Description:**
Implement data models for all task types that appear in `tasks.json`.

**Reasoning:**
Tasks are the agent's work queue. Each task type has different fields (violations vs nodes). A unified model must handle all task types.

**Implementation Steps:**
1. Create `codegraph/models/tasks.py`
2. Define `PolicyViolation` dataclass:
   - `source: str`
   - `required_target: str`
   - `policy_reason: str`
   - `current_calls: list[str]`
   - `suggested_fix: str`
   - `suggested_fix_target: Optional[str]`
   - `affected_tests: list[str]`
   - `test_update_required: bool`
   - `test_change_type: Optional[str]`
3. Define `TaskNode` dataclass:
   - `id: str`
   - `file: Optional[str]`
   - `type: Optional[str]`
   - `calls: list[str]`
   - `called_by: list[str]`
   - `suggested_fix: str`
   - `missing_import: Optional[str]`
   - `dynamic_target: Optional[str]`
   - `previous_intent: Optional[str]`
   - `body_hash_changed: Optional[bool]`
   - `reason: Optional[str]`
4. Define `TaskItem` dataclass:
   - `task_id: str`
   - `priority: int`
   - `nodes: Optional[list[TaskNode]]`
   - `violations: Optional[list[PolicyViolation]]`
5. Implement serialization for all types

**Files:**
- `codegraph/models/tasks.py`

**Dependencies:** A-017

**Validation:**
- All task types from README example serialize correctly
- Priority ordering is maintained
- Optional fields handled properly

---

### TASK B-010 — Define TaskBatch Data Model

**Description:**
Implement the top-level `tasks.json` structure that wraps all tasks with cycle and version metadata.

**Reasoning:**
The task batch is the primary interface between codegraph and the agent. It must include cycle number, graph version, and timestamp.

**Implementation Steps:**
1. Define `TaskBatch` dataclass in `codegraph/models/tasks.py`:
   - `cycle: int`
   - `graph_version: int`
   - `generated_at: str` (ISO 8601)
   - `tasks: list[TaskItem]`
2. Implement `to_json()` and `from_json()`
3. Implement `get_tasks_by_type(task_id) -> list[TaskItem]`
4. Implement `get_tasks_by_priority() -> list[TaskItem]` (sorted)
5. Ensure tasks are always sorted by priority in output

**Files:**
- `codegraph/models/tasks.py` (modify)

**Dependencies:** B-009

**Validation:**
- Tasks are sorted by priority in JSON output
- graph_version and cycle are present
- Round-trip serialization preserves order

---

### TASK B-011 — Define AgentResponse Data Model

**Description:**
Implement the `agent_response.json` data model that the agent writes and codegraph applies.

**Reasoning:**
The agent response is the output of agent reasoning. It must be validated before apply, especially the graph_version match.

**Implementation Steps:**
1. Create `codegraph/models/agent_response.py`
2. Define `IntentProposal` dataclass:
   - `node: str`
   - `intent: str`
   - `tags: list[str]`
3. Define `RepairAction` dataclass:
   - `node: str`
   - `action: str` — connect_call, add_import, remove_dead_code, flag_for_human_review
   - `target: Optional[str]`
   - `reason: str`
4. Define `WorkflowSuggestion` dataclass:
   - `type: str`
   - `source: str`
   - `target: str`
   - `reason: str`
5. Define `AgentResponse` dataclass:
   - `cycle: int`
   - `graph_version: int`
   - `intents: list[IntentProposal]`
   - `repairs: list[RepairAction]`
   - `workflow_suggestions: list[WorkflowSuggestion]`
6. Implement `to_json()` and `from_json()`
7. Implement `validate_version(current_version) -> bool`

**Files:**
- `codegraph/models/agent_response.py`

**Dependencies:** A-017

**Edge Cases:**
- Empty intents list (valid — only repairs)
- Empty repairs list (valid — only intents)
- Version mismatch → reject entirely
- Unknown action type → reject with error

**Validation:**
- Version validation catches mismatches
- All action types are validated
- Round-trip serialization works

---

### TASK B-012 — Define DeltaResult Data Model

**Description:**
Implement the `delta.json` data model that records incremental changes.

**Reasoning:**
Delta tracking is essential for the agent verification step and for incremental index updates.

**Implementation Steps:**
1. Create `codegraph/models/delta.py`
2. Define `DeltaResult` dataclass:
   - `computed_at: str` (ISO 8601)
   - `previous_graph_version: int`
   - `current_graph_version: int`
   - `files_changed: list[str]`
   - `nodes_added: list[str]`
   - `nodes_removed: list[str]`
   - `nodes_modified: list[str]`
   - `workflow_edges_added: list[tuple[str, str]]`
   - `workflow_edges_removed: list[tuple[str, str]]`
   - `stale_intents: list[str]`
3. Implement `to_json()` and `from_json()`
4. Implement `is_empty() -> bool` (no changes detected)
5. Implement `summary() -> str` (human-readable summary)

**Files:**
- `codegraph/models/delta.py`

**Dependencies:** A-017

**Validation:**
- Edge tuples serialize as arrays in JSON
- Summary produces readable output
- Empty delta is detected correctly

---

### TASK B-013 — Define StatusReport Data Model

**Description:**
Implement the status report data model used by `codegraph status`.

**Reasoning:**
The status command provides a system health snapshot. A structured model ensures consistent formatting.

**Implementation Steps:**
1. Create `codegraph/models/status.py`
2. Define `StatusReport` dataclass:
   - `nodes: int`
   - `edges: int`
   - `nodes_missing_intent: int`
   - `orphan_nodes: int`
   - `workflow_edges: int`
   - `suggested_workflow_edges: int`
   - `policy_violations: int`
   - `stale_intents: int`
   - `graph_version: int`
   - `cycle: int`
3. Implement `to_text() -> str` (aligned key-value format as in README)
4. Implement `to_json() -> str`

**Files:**
- `codegraph/models/status.py`

**Dependencies:** A-017

**Validation:**
- Text output matches README format exactly
- JSON output includes all fields

---

### TASK B-014 — Define ExplainResult Data Model

**Description:**
Implement the data model for `codegraph explain` output.

**Reasoning:**
The explain command provides full context for a single node. Agents use this for deep inspection before proposing repairs.

**Implementation Steps:**
1. Create `codegraph/models/explain.py`
2. Define `ExplainResult` dataclass:
   - `node_id: str`
   - `body_hash: str`
   - `body_hash_status: str` (unchanged/changed)
   - `line: int`
   - `intent: Optional[str]`
   - `layer: int`
   - `arch_layer: Optional[str]`
   - `called_by: list[str]`
   - `calls: list[str]`
   - `dynamic_edges: list[str]`
   - `tests_covering: list[str]`
   - `tags: list[str]`
3. Implement `to_text() -> str` (formatted as in README)
4. Implement `to_json() -> str`

**Files:**
- `codegraph/models/explain.py`

**Dependencies:** A-017

**Validation:**
- Text output matches README format
- All fields populated from graph data

---

### TASK B-015 — Define DiffResult Data Model

**Description:**
Implement the data model for `codegraph diff` output.

**Reasoning:**
The diff command compares graph states across commits. A structured result enables both human reading and programmatic processing.

**Implementation Steps:**
1. Create `codegraph/models/diff.py`
2. Define `DiffResult` dataclass:
   - `new_nodes: int`
   - `removed_nodes: int`
   - `changed_signatures: int`
   - `new_workflow_edges: int`
   - `removed_workflow_edges: int`
   - `stale_intents: int`
   - `new_node_ids: list[str]`
   - `removed_node_ids: list[str]`
3. Implement `to_text() -> str`
4. Implement `to_json() -> str`

**Files:**
- `codegraph/models/diff.py`

**Dependencies:** A-017

**Validation:**
- Text output matches README format
- Counts are accurate

---

### TASK B-016 — Implement Intent Quality Validator

**Description:**
Create a validator that checks intent strings against the quality rules from the README: must include verb + domain object + purpose.

**Reasoning:**
Bad intents like "helper function" or "utility" provide no value. Validation at application time prevents low-quality annotations.

**Implementation Steps:**
1. Add `validate_intent(intent: str) -> tuple[bool, list[str]]` to `codegraph/models/graph1.py`
2. Check for minimum length (e.g., 10 characters)
3. Check that intent starts with or contains a verb
4. Use simple heuristics: must contain at least 3 words
5. Warn about common bad patterns: "helper", "utility", "misc", "data processing"
6. Return list of warning messages

**Files:**
- `codegraph/models/graph1.py` (modify)

**Dependencies:** B-003

**Edge Cases:**
- Very short intents → warning
- Intents matching known bad patterns → warning
- Non-English intents → skip validation

**Validation:**
- "helper function" triggers warning
- "fetch OHLCV market data from exchange REST API" passes
- Empty intent triggers error

---

### TASK B-017 — Implement Node Type Enum and Validation

**Description:**
Define the `NodeType` enum and validation logic for node type fields.

**Reasoning:**
Node types (function, class, method, module) are used across Graph_0, queries, and filtering. An enum prevents typos and enables type checking.

**Implementation Steps:**
1. Define `NodeType` enum in `codegraph/models/graph0.py`:
   - `FUNCTION = "function"`
   - `CLASS = "class"`
   - `METHOD = "method"`
   - `MODULE = "module"`
2. Add validation to Graph0Node constructor
3. Add `is_callable() -> bool` method (True for function and method)

**Files:**
- `codegraph/models/graph0.py` (modify)

**Dependencies:** B-001

**Validation:**
- Invalid type raises ValueError
- Enum values match README strings exactly

---

### TASK B-018 — Implement Edge Type and Confidence Enums

**Description:**
Define enums for edge types and confidence levels with ordering.

**Reasoning:**
The README defines a precedence ordering for confidence: runtime > test > static > ai_inferred. This must be programmatically comparable.

**Implementation Steps:**
1. Define `EdgeType` enum in `codegraph/models/workflow.py`:
   - `CALL = "call"`, `TEST = "test"`, `TRACE = "trace"`, `DYNAMIC = "dynamic"`
2. Define `Confidence` enum with ordering:
   - `RUNTIME = "runtime"` (value 4)
   - `TEST = "test"` (value 3)
   - `STATIC = "static"` (value 2)
   - `AI_INFERRED = "ai_inferred"` (value 1)
3. Implement comparison operators on Confidence
4. Implement `Confidence.from_string(s) -> Confidence`

**Files:**
- `codegraph/models/workflow.py` (modify)

**Dependencies:** B-005

**Validation:**
- `Confidence.RUNTIME > Confidence.STATIC` is True
- Enum values match README strings

---

### TASK B-019 — Implement Task ID Enum and Priority Mapping

**Description:**
Define the `TaskID` enum with built-in priority ordering.

**Reasoning:**
Task priority ordering is fixed by the README. An enum with priority makes it impossible to get the ordering wrong.

**Implementation Steps:**
1. Define `TaskID` enum in `codegraph/models/tasks.py`:
   - `POLICY_VIOLATION = "policy_violation"` (priority 1)
   - `MISSING_IMPORT = "missing_import"` (priority 2)
   - `ORPHAN_NODES = "orphan_nodes"` (priority 3)
   - `UNRESOLVED_DYNAMIC = "unresolved_dynamic"` (priority 4)
   - `INTENT_MISSING = "intent_missing"` (priority 5)
   - `STALE_INTENT = "stale_intent"` (priority 6)
   - `MISSING_ARCHITECTURE_TEST = "missing_architecture_test"` (priority 3)
   - `MISSING_TEST_COVERAGE = "missing_test_coverage"` (priority 5)
2. Add `priority` property to each enum member
3. Implement comparison based on priority

**Files:**
- `codegraph/models/tasks.py` (modify)

**Dependencies:** B-009

**Validation:**
- `TaskID.POLICY_VIOLATION.priority == 1`
- Tasks sort correctly by priority

---

### TASK B-020 — Implement Repair Action Type Enum

**Description:**
Define the `RepairActionType` enum for valid agent repair actions.

**Reasoning:**
Only four repair actions are valid. An enum prevents invalid actions from being submitted.

**Implementation Steps:**
1. Define `RepairActionType` enum in `codegraph/models/agent_response.py`:
   - `CONNECT_CALL = "connect_call"`
   - `ADD_IMPORT = "add_import"`
   - `REMOVE_DEAD_CODE = "remove_dead_code"`
   - `FLAG_FOR_HUMAN_REVIEW = "flag_for_human_review"`
2. Add `modifies_code() -> bool` property (True for connect_call, add_import, remove_dead_code)
3. Add validation in AgentResponse parsing

**Files:**
- `codegraph/models/agent_response.py` (modify)

**Dependencies:** B-011

**Validation:**
- Unknown action type raises ValueError
- `modifies_code()` returns correct values

---

### TASK B-021 — Implement Test Change Type Enum

**Description:**
Define the `TestChangeType` enum for test impact analysis.

**Reasoning:**
Test change types classify how affected tests need updating. An enum ensures consistency.

**Implementation Steps:**
1. Define `TestChangeType` enum in `codegraph/models/tasks.py`:
   - `UPDATE_EXECUTION_PATH = "update_execution_path"`
   - `UPDATE_MOCK = "update_mock"`
   - `UPDATE_ASSERTION = "update_assertion"`
   - `ADD_NEW_TEST = "add_new_test"`
2. Add to TaskNode and PolicyViolation models

**Files:**
- `codegraph/models/tasks.py` (modify)

**Dependencies:** B-009

**Validation:**
- All enum values match README strings

---

### TASK B-022 — Implement Suggested Fix Enum

**Description:**
Define the enum for suggested fix types that appear in task hints.

**Reasoning:**
Suggested fixes guide agent action. A defined set ensures parseable, consistent hints.

**Implementation Steps:**
1. Define `SuggestedFix` enum in `codegraph/models/tasks.py`:
   - `CONNECT_CALL = "connect_call"`
   - `ADD_IMPORT = "add_import"`
   - `FLAG_FOR_HUMAN_REVIEW = "flag_for_human_review"`
   - `GENERATE_ARCHI_TEST = "generate_archi_test"`
2. Add to TaskNode model

**Files:**
- `codegraph/models/tasks.py` (modify)

**Dependencies:** B-009

**Validation:**
- All values match README suggested_fix strings

---

### TASK B-023 — Implement Rule Type Enum

**Description:**
Define the enum for suggested workflow rule types.

**Reasoning:**
Only `required_call` and `forbidden_call` are valid. Enforce at the type level.

**Implementation Steps:**
1. Define `RuleType` enum in `codegraph/models/suggested_workflow.py`:
   - `REQUIRED_CALL = "required_call"`
   - `FORBIDDEN_CALL = "forbidden_call"`
2. Implement `is_violation(edge_exists: bool) -> bool`:
   - required_call: violation if edge does NOT exist
   - forbidden_call: violation if edge DOES exist

**Files:**
- `codegraph/models/suggested_workflow.py` (modify)

**Dependencies:** B-007

**Validation:**
- `REQUIRED_CALL.is_violation(edge_exists=False)` returns True
- `FORBIDDEN_CALL.is_violation(edge_exists=True)` returns True

---

### TASK B-024 — Implement Node ID Collision Detector

**Description:**
Create logic that detects node ID collisions and applies the `[N]` disambiguator suffix.

**Reasoning:**
Identically named functions in the same scope produce colliding IDs. The system must detect and resolve this with numeric suffixes.

**Implementation Steps:**
1. Add `CollisionResolver` class to `codegraph/models/graph0.py`
2. Track seen IDs during extraction
3. When a collision is detected:
   - First occurrence keeps original ID
   - Subsequent occurrences get `[2]`, `[3]`, etc.
4. Log collisions as warnings
5. Return collision report for `codegraph build` output

**Files:**
- `codegraph/models/graph0.py` (modify)

**Dependencies:** B-001

**Edge Cases:**
- Three identical names → `func`, `func[2]`, `func[3]`
- Collision after previous non-colliding build (IDs change)
- Disambiguator survives delta updates

**Validation:**
- Two identical names get distinct IDs
- Warning is logged
- Disambiguator format matches README (`[2]`)

---

### TASK B-025 — Implement Graph0/Graph1 Alignment Checker

**Description:**
Create a function that validates Graph_1 references are valid against Graph_0.

**Reasoning:**
Graph_1 references Graph_0 by ID. Drift detection catches stale entries after rebuilds, renames, or deletions.

**Implementation Steps:**
1. Add `check_alignment(graph0: Graph0, graph1: Graph1) -> AlignmentReport` to `codegraph/models/`
2. Find Graph_1 entries with no matching Graph_0 node → stale
3. Find Graph_0 nodes with no Graph_1 entry → missing intent
4. Find Graph_0 nodes whose body_hash changed since last Graph_1 update → stale intent
5. Return `AlignmentReport` with lists of each category

**Files:**
- `codegraph/models/alignment.py`

**Dependencies:** B-002, B-004

**Validation:**
- Stale entries detected when node removed from Graph_0
- Missing intents detected for new nodes
- Body hash changes detected

---

### TASK B-026 — Implement Workflow Edge Deduplication

**Description:**
Implement logic to prevent exact duplicate edges while preserving edges from different sources.

**Reasoning:**
The README states all edges from all sources are preserved, but exact duplicates (same source + target + type + confidence) should not appear.

**Implementation Steps:**
1. Add `deduplicate_edges(edges: list[WorkflowEdge]) -> list[WorkflowEdge]`
2. Use a set of (source, target, edge_type, confidence) tuples for dedup
3. Preserve order of first occurrence
4. Return deduplicated list

**Files:**
- `codegraph/models/workflow.py` (modify)

**Dependencies:** B-005

**Validation:**
- Exact duplicates removed
- Edges with different confidence preserved
- Order maintained

---

### TASK B-027 — Implement Graph Version Validation for Agent Response

**Description:**
Implement the version check that rejects agent responses targeting a stale graph version.

**Reasoning:**
This is a critical safety mechanism. The README states: "an agent response referencing a stale graph version must be rejected."

**Implementation Steps:**
1. Add `validate_response_version(response: AgentResponse, current_version: int) -> bool` to `codegraph/models/agent_response.py`
2. Compare `response.graph_version` against `current_version`
3. Return False if versions don't match
4. Include helpful error message with both versions

**Files:**
- `codegraph/models/agent_response.py` (modify)

**Dependencies:** B-011

**Validation:**
- Matching versions pass
- Mismatching versions fail with clear error
- Error message includes both version numbers

---

### TASK B-028 — Implement Cycle Validation for Agent Response

**Description:**
Implement cycle number validation between tasks.json and agent_response.json.

**Reasoning:**
The cycle field in the response must match the tasks batch it was generated from. Mismatched cycles indicate stale responses.

**Implementation Steps:**
1. Add cycle validation to `AgentResponse.validate()` method
2. Check cycle number matches expected
3. Warn (not reject) on cycle mismatch to allow manual corrections

**Files:**
- `codegraph/models/agent_response.py` (modify)

**Dependencies:** B-011

**Validation:**
- Matching cycles pass
- Mismatched cycles generate warning

---

### TASK B-029 — Implement JSON Schema Export

**Description:**
Generate JSON Schema files (.schema.json) for all data models to enable external validation.

**Reasoning:**
External tools and agents may want to validate their JSON against formal schemas before submission.

**Implementation Steps:**
1. Create `codegraph/schemas/` directory
2. Generate JSON Schema for:
   - `graph0.schema.json`
   - `graph1.schema.json`
   - `workflow.schema.json`
   - `suggested_workflow.schema.json`
   - `tasks.schema.json`
   - `agent_response.schema.json`
   - `delta.schema.json`
3. Auto-generate from dataclass definitions if using Pydantic
4. Add CLI command `codegraph schema <type>` to print schema

**Files:**
- `codegraph/schemas/graph0.schema.json`
- `codegraph/schemas/graph1.schema.json`
- `codegraph/schemas/workflow.schema.json`
- `codegraph/schemas/suggested_workflow.schema.json`
- `codegraph/schemas/tasks.schema.json`
- `codegraph/schemas/agent_response.schema.json`
- `codegraph/schemas/delta.schema.json`

**Dependencies:** B-001 through B-012

**Validation:**
- Schemas are valid JSON Schema draft-07+
- README examples validate against schemas
- Schemas match dataclass definitions

---

### TASK B-030 — Implement Model Factory Functions

**Description:**
Create factory/builder functions for constructing complex model instances from partial data.

**Reasoning:**
Tests and internal code frequently need to construct model instances. Factory functions reduce boilerplate and ensure required fields are populated.

**Implementation Steps:**
1. Create `codegraph/models/factories.py`
2. Implement:
   - `make_graph0_node(id, file, type, **kwargs) -> Graph0Node`
   - `make_graph1_node(id, intent, layer, **kwargs) -> Graph1Node`
   - `make_workflow_edge(source, target, **kwargs) -> WorkflowEdge`
   - `make_task(task_id, **kwargs) -> TaskItem`
   - `make_rule(type, source, target, reason, **kwargs) -> SuggestedWorkflowRule`
3. Provide sensible defaults for optional fields
4. Auto-generate timestamps, versions where needed

**Files:**
- `codegraph/models/factories.py`

**Dependencies:** B-001 through B-012

**Validation:**
- Factories produce valid model instances
- Default values are sensible
- All required fields must be provided

---

### TASK B-031 — Define Convergence State Model

**Description:**
Implement a model tracking repair loop convergence state across iterations.

**Reasoning:**
The README defines specific stopping conditions: orphan count stagnant for 3 iterations, edge count stabilized within 5%, max iterations reached, or all actions are flag_for_human_review.

**Implementation Steps:**
1. Create `codegraph/models/convergence.py`
2. Define `ConvergenceState` dataclass:
   - `iteration: int`
   - `orphan_history: list[int]` (last N orphan counts)
   - `edge_count_history: list[int]` (last N edge counts)
   - `max_iterations: int` (default 10)
   - `convergence_window: int` (default 3)
   - `edge_stability_threshold: float` (default 0.05)
3. Implement `should_stop() -> tuple[bool, str]` returning (stop, reason)
4. Implement `record_iteration(orphans, edges, all_flagged)`

**Files:**
- `codegraph/models/convergence.py`

**Dependencies:** A-017

**Edge Cases:**
- First iteration (no history) → never stop
- Fewer than 3 iterations → don't check orphan stagnation
- Edge count exactly at 5% boundary

**Validation:**
- Stops after 3 stagnant orphan counts
- Stops when edge count stabilizes within 5%
- Stops at max iterations
- Stops when all actions are flag_for_human_review

---

### TASK B-032 — Implement Glob Pattern Matcher for Rule Scoping

**Description:**
Create a pattern matching utility that expands rule scope patterns against the current node list.

**Reasoning:**
Suggested workflow rules can use glob patterns (`src/api/*`), layer numbers, and arch_layer values. These must be expanded to concrete node IDs at task generation time.

**Implementation Steps:**
1. Add `expand_rule_scope(scope: str, nodes: list[Graph0Node], graph1: Graph1) -> list[str]`
2. Handle exact node ID → return [id]
3. Handle module path → return all nodes in module
4. Handle glob pattern → use `fnmatch` against node IDs
5. Handle layer number → filter by layer from Graph_1
6. Handle arch_layer → filter by arch_layer from Graph_1
7. Log warning if pattern matches zero nodes

**Files:**
- `codegraph/models/suggested_workflow.py` (modify)

**Dependencies:** B-007, B-002, B-004

**Edge Cases:**
- Pattern matches zero nodes → warning, not error
- Pattern matches thousands of nodes → performance concern
- Invalid glob syntax → error with message

**Validation:**
- Exact ID returns single match
- Glob `src/api/*` matches all api nodes
- Layer filter matches correct nodes
- Zero matches produces warning

---

### TASK B-033 — Implement Model Serialization Registry

**Description:**
Create a central registry that maps model types to their serialization/deserialization functions.

**Reasoning:**
Multiple modules need to load and save different model types. A registry avoids switch statements and makes the system extensible.

**Implementation Steps:**
1. Add serialization registry to `codegraph/models/__init__.py`
2. Register all model types with their file names and serializers
3. Implement `load_model(model_type, project_root) -> model`
4. Implement `save_model(model, project_root)`
5. Resolve file paths from model type

**Files:**
- `codegraph/models/__init__.py` (modify)

**Dependencies:** B-001 through B-012

**Validation:**
- Load/save works for all model types
- File paths are correct for each model type

---

### TASK B-034 — Implement Response History Manager

**Description:**
Create a manager for storing and retrieving historical agent responses and task batches.

**Reasoning:**
Tasks and responses accumulate in subdirectories with cycle-numbered filenames. History enables auditing of past agent decisions.

**Implementation Steps:**
1. Add `ResponseHistoryManager` class to `codegraph/models/`
2. Implement `save_tasks(batch: TaskBatch)` → writes to `tasks/tasks_{cycle}.json`
3. Implement `save_response(response: AgentResponse)` → writes to `responses/response_{cycle}.json`
4. Implement `load_tasks(cycle: int) -> TaskBatch`
5. Implement `load_response(cycle: int) -> AgentResponse`
6. Implement `list_cycles() -> list[int]`

**Files:**
- `codegraph/models/history.py`

**Dependencies:** B-010, B-011, A-008

**Validation:**
- Saves create correctly numbered files
- Load retrieves correct cycle
- List returns all available cycles

---

### TASK B-035 — Implement Validation Pipeline for All Models

**Description:**
Create a unified validation pipeline that validates any model instance against its schema and business rules.

**Reasoning:**
Validation must happen at all entry points: file loading, CLI input, agent response parsing. A pipeline ensures nothing is missed.

**Implementation Steps:**
1. Create `codegraph/models/validation.py`
2. Implement `validate(model) -> ValidationResult`
3. Check schema compliance (required fields, types)
4. Check business rules (valid node IDs, valid types, valid references)
5. Return structured errors with field paths
6. Support `strict` mode (errors) and `lenient` mode (warnings)

**Files:**
- `codegraph/models/validation.py`

**Dependencies:** B-001 through B-012

**Validation:**
- Valid models pass validation
- Missing required fields produce errors
- Invalid references produce warnings in lenient mode

---

### TASK B-036 — Define WorkflowLevel Enum

**Description:**
Define the enum for workflow graph compression levels (function, class, module).

**Reasoning:**
The `--level` flag on `codegraph workflow` controls graph granularity. An enum ensures valid values.

**Implementation Steps:**
1. Define `WorkflowLevel` enum in `codegraph/models/workflow.py`:
   - `FUNCTION = "function"`
   - `CLASS = "class"`
   - `MODULE = "module"`

**Files:**
- `codegraph/models/workflow.py` (modify)

**Dependencies:** B-005

**Validation:**
- Invalid level raises error
- Default is FUNCTION

---

### TASK B-037 — Implement Edge Confidence Comparison Logic

**Description:**
Implement the confidence comparison logic that agents use to choose between conflicting edges.

**Reasoning:**
The README specifies precedence: runtime > test > static > ai_inferred. When two edges to different targets exist from the same source, agents prefer higher confidence.

**Implementation Steps:**
1. Add `compare_edges(a: WorkflowEdge, b: WorkflowEdge) -> WorkflowEdge` to workflow model
2. Return the edge with higher confidence
3. When confidence is equal, prefer trace > call > test > dynamic edge type
4. Add `best_edge_for(edges: list[WorkflowEdge]) -> WorkflowEdge`

**Files:**
- `codegraph/models/workflow.py` (modify)

**Dependencies:** B-018

**Validation:**
- Runtime edge preferred over static
- Equal confidence uses edge type tiebreaker

---

### TASK B-038 — Implement Dead Code Signal Checker

**Description:**
Create a utility that checks all four dead-code signals required before node removal.

**Reasoning:**
The README requires all four signals: no incoming edges, no imports, no config/registry references, no test coverage. This is a safety-critical check.

**Implementation Steps:**
1. Create `codegraph/models/dead_code.py`
2. Define `DeadCodeSignals` dataclass:
   - `no_incoming_edges: bool`
   - `no_imports: bool`
   - `no_config_references: bool`
   - `no_test_coverage: bool`
3. Implement `all_confirmed() -> bool` → True only when all four are True
4. Implement `missing_signals() -> list[str]` → list of unconfirmed signals

**Files:**
- `codegraph/models/dead_code.py`

**Dependencies:** A-017

**Validation:**
- All four True → `all_confirmed()` returns True
- Any False → `all_confirmed()` returns False
- Missing signals correctly reported

---

### TASK B-039 — Implement Arch Layer Helpers

**Description:**
Create helper functions for working with architectural layer annotations.

**Reasoning:**
`arch_layer` is used in rule scoping and policy enforcement. Helpers standardize common operations.

**Implementation Steps:**
1. Add arch layer helpers to `codegraph/models/graph1.py`
2. `get_nodes_by_arch_layer(graph1, arch_layer) -> list[str]`
3. `set_arch_layer(graph1, node_id, arch_layer)`
4. `validate_arch_layer_name(name) -> bool` — warn on non-standard values
5. Define standard values as constants: controller, service, domain, repository, infra

**Files:**
- `codegraph/models/graph1.py` (modify)

**Dependencies:** B-003

**Validation:**
- Filtering by arch_layer returns correct nodes
- Setting arch_layer persists
- Non-standard names produce warning

---

### TASK B-040 — Implement Module-Level and Class-Level Node Models

**Description:**
Extend the Graph_0 and Graph_1 models to support module and class intent nodes.

**Reasoning:**
The README states "Intent is not limited to functions. Graph_1 can annotate modules and classes." Module IDs use path without extension; class IDs use `file::ClassName`.

**Implementation Steps:**
1. Ensure Graph0Node supports type=module and type=class
2. Module IDs: `src/pipeline` (no .py extension)
3. Class IDs: `src/trade.py::RiskEngine`
4. Ensure Graph1Node accepts these IDs
5. Update intent validation to work with module/class intents
6. Update factories to support module and class nodes

**Files:**
- `codegraph/models/graph0.py` (modify)
- `codegraph/models/graph1.py` (modify)
- `codegraph/models/factories.py` (modify)

**Dependencies:** B-001, B-003, B-017

**Edge Cases:**
- Module with no functions (valid)
- Class with no methods (valid)
- Nested classes

**Validation:**
- Module node ID has no .py extension
- Class node ID uses correct format
- Intent application works for modules and classes

---

### TASK B-041 — Add `dependency_hash` Field to Graph0Node (CAS Integration)

**Description:**
Extend `Graph0Node` dataclass with a `dependency_hash: Optional[str]` field that stores the content-addressed hash combining the node's body_hash with the dependency_hashes of everything it calls.

**Reasoning:**
This is the data model change required by the Content Addressed Graph (CAS) system (Group Q). The `dependency_hash` field turns the graph into a Bazel-style content-addressed structure where any downstream change is visible at every upstream node. The field is `Optional` for backward compatibility with pre-CAS graph files.

**Implementation Steps:**
1. Add `dependency_hash: Optional[str] = None` to `Graph0Node` dataclass
2. Update `to_dict()` — include `dependency_hash` if not None
3. Update `from_dict()` — load `dependency_hash` with default `None`
4. Update `Graph0` collection to support bulk `dependency_hash` updates via `update_dependency_hashes(hashes: dict[str, str])`
5. Do NOT include `dependency_hash` in `__eq__` or `__hash__` — equality is still based on `id` only

**Files:**
- `codegraph/models/graph0.py` (modify)

**Dependencies:** B-001, B-002

**Edge Cases:**
- Old graph files without `dependency_hash` → loads as None
- Node with no callees → `dependency_hash` is hash of just `body_hash`
- Serialization must exclude None values to keep JSON clean

**Validation:**
- Old graph JSON loads without error (backward compat)
- New graph JSON includes `dependency_hash` when present
- `update_dependency_hashes()` sets hashes for all specified nodes
- Equality/hash unchanged (still id-only)

---

### TASK B-042 — Add CAS Statistics to DeltaResult Model

**Description:**
Extend `DeltaResult` with CAS-specific statistics fields: affected_nodes count, propagation_factor, nodes_skipped, cache_hit_rate.

**Reasoning:**
CAS delta produces additional metrics that measure its effectiveness. These must be part of the DeltaResult model for display and logging.

**Implementation Steps:**
1. Add CAS fields to `DeltaResult` dataclass:
   - `cas_enabled: bool = False`
   - `cas_body_changed_nodes: int = 0`
   - `cas_affected_nodes: int = 0`
   - `cas_propagation_factor: float = 0.0`
   - `cas_nodes_skipped: int = 0`
   - `cas_scc_count: int = 0`
2. Update `to_json()` / `from_json()` — include CAS fields only when `cas_enabled`
3. Update `summary()` to include CAS section when enabled

**Files:**
- `codegraph/models/delta.py` (modify)

**Dependencies:** B-012

**Edge Cases:**
- CAS disabled → fields are zero/false, not included in JSON
- Backward compat with old delta.json files → defaults to disabled

**Validation:**
- CAS fields serialize when enabled
- Old delta JSON loads without error
- Summary includes CAS section when enabled

---

### TASK B-043 — Add CAS Fields to ExplainResult Model

**Description:**
Extend `ExplainResult` with CAS-specific fields: dependency_hash, dependency_chain, dependent_count, would_invalidate.

**Reasoning:**
The `codegraph explain` command should show CAS information for a node so developers and agents can understand the dependency hash structure and change impact.

**Implementation Steps:**
1. Add CAS fields to `ExplainResult` dataclass:
   - `dependency_hash: Optional[str] = None`
   - `dependency_chain: list[str] = []` (direct callees contributing to hash)
   - `dependent_count: int = 0`
   - `would_invalidate: list[str] = []` (top N nodes affected if this changes)
2. Update `to_text()` — add "Content Address" section when `dependency_hash` is present
3. Update `to_json()` — include CAS fields when present

**Files:**
- `codegraph/models/explain.py` (modify)

**Dependencies:** B-014

**Edge Cases:**
- CAS not computed → fields are None/empty, section omitted from text output
- Node with 1000 dependents → show top 20 in text, all in JSON

**Validation:**
- Text output includes CAS section when dependency_hash present
- Text output omits CAS section when dependency_hash is None
- JSON includes all CAS fields
---

### TASK B-044 — Add Graph2Node Dataclass to Core Models

**Description:**
Register the Graph2Node data model (R-001) in the core models package so it's accessible alongside GraphNode, IntentNode, and WorkflowEdge.

**Reasoning:**
All graph models live in `codegraph/models/`. Graph_2 models must follow the same pattern for import consistency and schema validation.

**Implementation Steps:**
1. Ensure `codegraph/models/graph2.py` is importable from `codegraph.models`
2. Add `Graph2Node`, `Graph2`, `SemanticAction`, `SideEffect`, `DataFlowSummary` to `__init__.py` exports
3. Add JSON Schema for graph2.json alongside existing schemas

**Files:**
- `codegraph/models/__init__.py` (modify)
- `codegraph/schemas/graph2_schema.json`

**Dependencies:** R-001, R-007, B-001

**Validation:**
- `from codegraph.models import Graph2Node` works
- Schema validates graph2.json structure
- Model round-trip serialization matches schema

---

### TASK B-045 — Add Semantic Fields to ExplainResult Model

**Description:**
Extend `ExplainResult` with Graph_2 semantic fields: actions, guards, side_effects, domain_tags, behavior_hash, confidence.

**Reasoning:**
The `codegraph explain` command needs to display semantic information alongside structural and CAS data. The model must carry these fields.

**Implementation Steps:**
1. Add semantic fields to `ExplainResult`:
   - `actions: list[dict] = []` — serialized SemanticAction entries
   - `guards: list[dict] = []` — serialized Guard entries
   - `side_effects: list[dict] = []` — serialized SideEffect entries
   - `domain_tags: list[str] = []`
   - `behavior_hash: Optional[str] = None`
   - `semantic_confidence: Optional[float] = None`
2. Update `to_text()` — add "Behavior" section when semantic data present
3. Update `to_json()` — include semantic fields

**Files:**
- `codegraph/models/explain.py` (modify)

**Dependencies:** R-001, B-014, B-043

**Edge Cases:**
- No Graph_2 → fields empty, section omitted
- Low confidence → show warning in text output

**Validation:**
- Text output includes behavior section when populated
- JSON includes all semantic fields
- Empty semantic fields don't break existing output

---

### TASK B-046 — Add SemanticContext Fields to TaskNode Model

**Description:**
Extend `TaskNode` model with semantic context so generated tasks carry behavioral information for agents.

**Reasoning:**
Agents performing repairs need to know the semantic role of the node they're modifying — whether it performs authentication, has database side effects, or contains safety guards.

**Implementation Steps:**
1. Add to `TaskNode` model:
   - `semantic_context: Optional[dict] = None` — contains summarized actions, effects, guards, domain
   - `safety_warnings: list[str] = []` — e.g., "Node performs AUTHENTICATE", "Node has DATABASE_WRITE side effects"
2. Populate in task generation when Graph_2 is available
3. Include in tasks.json serialization

**Files:**
- `codegraph/models/tasks.py` (modify)

**Dependencies:** R-037, B-009

**Validation:**
- Tasks include semantic context when available
- Safety warnings populated for risky nodes
- Missing Graph_2 doesn't break TaskNode serialization