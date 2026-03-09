# Group H — Suggested Workflow & Policy System

> Rule management, policy enforcement, scope expansion, suggested_workflow.json, and rule lifecycle via `suggest.py`.

---

### TASK H-001 — Implement Suggested Workflow Data Store

**Description:**
Create the data store for `suggested_workflow.json` that holds all architecture policy rules.

**Reasoning:**
The suggested workflow is a committed file that describes how the architecture SHOULD behave. It's separate from the observed workflow.

**Implementation Steps:**
1. Create `codegraph/suggest.py`
2. Implement `load_suggested_workflow(project_root) -> SuggestedWorkflow`
3. Implement `save_suggested_workflow(sw, project_root)`
4. Parse and validate JSON structure
5. Handle missing file (first time → empty rules list)

**Files:**
- `codegraph/suggest.py`

**Dependencies:** B-008, A-013

**Validation:**
- File loads and saves correctly
- Missing file handled gracefully
- JSON validated on load

---

### TASK H-002 — Implement `required_call` Rule Type

**Description:**
Implement the rule type that declares a function MUST call another function.

**Reasoning:**
Example from README: `"auth::validate_token" required_call "logging::log_access"` — security audit logging after auth validation.

**Implementation Steps:**
1. Implement `RequiredCallRule` in `codegraph/suggest.py`
2. Fields: `rule_type: "required_call"`, `source`, `target`, `scope`, `reason`
3. Validation: check that a `required_call` edge exists in the workflow
4. Violation: source exists but does not call target = violation

**Files:**
- `codegraph/suggest.py` (modify)

**Dependencies:** H-001, B-008

**Edge Cases:**
- Source doesn't exist → warning (rule may be stale)
- Target doesn't exist → warning (rule may be stale)
- Source calls target via intermediate → NOT satisfied (must be direct)

**Validation:**
- Required call present → no violation
- Required call missing → violation detected

---

### TASK H-003 — Implement `forbidden_call` Rule Type

**Description:**
Implement the rule type that declares a function MUST NOT call another function.

**Reasoning:**
Example from README: `"payment::*" forbidden_call "database::raw_query"` — prevent SQL injection risk.

**Implementation Steps:**
1. Implement `ForbiddenCallRule` in `codegraph/suggest.py`
2. Fields: `rule_type: "forbidden_call"`, `source`, `target`, `scope`, `reason`
3. Violation: source calls target = violation
4. No call found → satisfied

**Files:**
- `codegraph/suggest.py` (modify)

**Dependencies:** H-001, B-008

**Validation:**
- Forbidden call present → violation
- Forbidden call absent → no violation

---

### TASK H-004 — Implement Exact Scope (`scope: exact`)

**Description:**
Implement scope type that matches a single, specific node ID.

**Reasoning:**
Exact scope is the simplest: matches only __file::class::function__ exactly.

**Implementation Steps:**
1. Implement `match_scope_exact(node_id: str, scope_value: str) -> bool`
2. Exact string comparison
3. Node ID format: `file::class::function`
4. Must match the complete ID

**Files:**
- `codegraph/suggest.py` (modify)

**Dependencies:** H-001

**Validation:**
- Exact match returns True
- Partial match returns False
- Case-sensitive matching

---

### TASK H-005 — Implement Module Scope (`scope: module`)

**Description:**
Implement scope type that matches all nodes within a Python module.

**Reasoning:**
Module scope matches all functions/classes/methods in a module. Useful for module-level policies.

**Implementation Steps:**
1. Implement `match_scope_module(node_id: str, scope_value: str) -> bool`
2. Extract module name from node_id (portion before first `::`)
3. Compare with scope value
4. Support dotted module paths (`server.routes.auth`)

**Files:**
- `codegraph/suggest.py` (modify)

**Dependencies:** H-001

**Validation:**
- Nodes in module match
- Nodes in other modules don't match
- Dotted paths handled

---

### TASK H-006 — Implement Glob Scope (`scope: glob`)

**Description:**
Implement scope type that matches nodes using glob patterns with wildcards.

**Reasoning:**
Glob patterns like `payment::*` match all functions in the payment module. Powerful for broad policies.

**Implementation Steps:**
1. Implement `match_scope_glob(node_id: str, scope_value: str) -> bool`
2. Use `fnmatch.fnmatch()` for glob matching
3. Support `*` (any segment), `**` (multi-segment), `?` (single char)
4. Pattern applied to full node ID

**Files:**
- `codegraph/suggest.py` (modify)

**Dependencies:** H-001, B-027

**Edge Cases:**
- `*::*::process_*` → match all process_ functions in any module/class
- `payment::*` → match all direct children
- `**` → match everything (dangerous, warn)

**Validation:**
- Wildcards match correctly
- Non-matching patterns return False
- `**` matching everything triggers warning

---

### TASK H-007 — Implement Layer Scope (`scope: layer`)

**Description:**
Implement scope type that matches all nodes at a specific layer number.

**Reasoning:**
Layer-scoped rules apply to all nodes at a layer (e.g., "No Layer 4 test code may call Layer 0 stdlib directly").

**Implementation Steps:**
1. Implement `match_scope_layer(node_id: str, scope_value: int, graph1: Graph1) -> bool`
2. Look up node's layer in Graph_1
3. Compare with scope layer value
4. Must have access to Graph_1 for layer resolution

**Files:**
- `codegraph/suggest.py` (modify)

**Dependencies:** H-001, B-004, D-007

**Validation:**
- Layer 3 nodes match layer scope 3
- Layer 4 nodes don't match layer scope 3

---

### TASK H-008 — Implement Arch Layer Scope (`scope: arch_layer`)

**Description:**
Implement scope type that matches all nodes with a specific `arch_layer` annotation.

**Reasoning:**
Arch layer is a user-defined architectural classification (e.g., "controller", "service", "repository"). Allows domain-specific policies.

**Implementation Steps:**
1. Implement `match_scope_arch_layer(node_id: str, scope_value: str, graph1: Graph1) -> bool`
2. Look up node's arch_layer annotation in Graph_1
3. Compare with scope value
4. Nodes without arch_layer never match

**Files:**
- `codegraph/suggest.py` (modify)

**Dependencies:** H-001, B-039

**Validation:**
- Nodes with matching arch_layer match
- Nodes without arch_layer don't match

---

### TASK H-009 — Implement Scope Resolution Engine

**Description:**
Create unified scope resolution that expands a rule's scope to a list of matching node IDs.

**Reasoning:**
Rules with non-exact scopes need expansion: a glob scope must be expanded to all matching node IDs before evaluation.

**Implementation Steps:**
1. Implement `expand_scope(scope: Scope, graph0: Graph0, graph1: Graph1) -> set[str]`
2. Dispatch to appropriate scope matcher (exact, module, glob, layer, arch_layer)
3. Return set of all matching node IDs
4. Cache results for repeated scope evaluation

**Files:**
- `codegraph/suggest.py` (modify)

**Dependencies:** H-004 through H-008

**Edge Cases:**
- Scope matches zero nodes → warning ("dangling rule" failure mode)
- Scope matches thousands of nodes → performance (use caching)
- Invalid scope type → error

**Validation:**
- Each scope type correctly resolved
- Dangling scope detected and warned
- Cache improves repeated evaluation

---

### TASK H-010 — Implement Policy Violation Detector

**Description:**
Check all suggested workflow rules against the actual workflow and return violations.

**Reasoning:**
This is the core function that compares what SHOULD happen (suggested) with what DOES happen (workflow). Violations become tasks.

**Implementation Steps:**
1. Implement `detect_violations(suggested: SuggestedWorkflow, workflow: Workflow, graph0: Graph0, graph1: Graph1) -> list[PolicyViolation]`
2. For each rule:
   - Expand scope to matching node IDs
   - For `required_call`: check if each matching source has an edge to the target
   - For `forbidden_call`: check if any matching source has an edge to the target
3. Return PolicyViolation for each failed check

**Files:**
- `codegraph/suggest.py` (modify)

**Dependencies:** H-009, F-019

**Validation:**
- Known violations detected
- Satisfied rules don't produce violations
- Performance acceptable for 1000+ rules

---

### TASK H-011 — Implement `codegraph suggest add` Command Logic

**Description:**
Implement the logic for adding a new rule to suggested_workflow.json.

**Reasoning:**
Users need a CLI to manage rules without manually editing JSON.

**Implementation Steps:**
1. Implement `add_rule(rule_type, source, target, scope_type, scope_value, reason=None)`
2. Validate rule_type is valid
3. Validate source/target format
4. Validate scope_type is valid
5. Append to suggested_workflow.json
6. Sort rules by scope for readability

**Files:**
- `codegraph/suggest.py` (modify)

**Dependencies:** H-001

**Edge Cases:**
- Duplicate rule → warn and skip
- Invalid node format → error with guidance
- Missing reason → allowed but encouraged

**Validation:**
- New rule appears in file
- Duplicates detected
- Invalid input rejected

---

### TASK H-012 — Implement `codegraph suggest remove` Command Logic

**Description:**
Implement removal of a rule from suggested_workflow.json.

**Reasoning:**
Obsolete rules must be cleanable without manual JSON editing.

**Implementation Steps:**
1. Implement `remove_rule(rule_id_or_match)`
2. Support removal by: rule ID (index), or matching source+target+type
3. Confirm removal in output
4. Save updated file

**Files:**
- `codegraph/suggest.py` (modify)

**Dependencies:** H-001

**Validation:**
- Rule removed from file
- File still valid JSON
- Non-matching removal → error

---

### TASK H-013 — Implement `codegraph suggest list` Command Logic

**Description:**
List all current rules in suggested_workflow.json with their metadata.

**Reasoning:**
Users need to inspect current policy rules.

**Implementation Steps:**
1. Implement `list_rules(filter_scope=None, filter_type=None) -> list[RuleDisplay]`
2. Support filtering by scope type and rule type
3. Format for CLI display (table format)
4. Show: index, type, source, target, scope, reason

**Files:**
- `codegraph/suggest.py` (modify)

**Dependencies:** H-001

**Validation:**
- All rules listed
- Filters work correctly
- Output is readable

---

### TASK H-014 — Implement Dangling Rule Detection

**Description:**
Detect rules whose source or target no longer exists in the codebase.

**Reasoning:**
README failure mode: "dangling rules — suggested_workflow.json references a node or scope that no longer matches any nodes."

**Implementation Steps:**
1. Implement `find_dangling_rules(suggested, graph0) -> list[DanglingRule]`
2. For each rule:
   - Check if source matches at least one Graph_0 node
   - Check if target matches at least one Graph_0 node
   - For scope-based rules: check if scope expansion produces matches
3. Report rules with zero matches as dangling

**Files:**
- `codegraph/suggest.py` (modify)

**Dependencies:** H-009, B-002

**Validation:**
- Removed function makes rule dangling → detected
- Renamed module makes scope dangling → detected
- Valid rules not flagged

---

### TASK H-015 — Implement Wildcard Zero-Match Warning

**Description:**
Warn when a glob pattern in a rule matches zero nodes.

**Reasoning:**
README failure mode: "wildcard zero matches — a glob pattern in suggested_workflow.json matches zero nodes."

**Implementation Steps:**
1. During scope expansion (H-009), track match count
2. If glob scope matches zero → add to warnings
3. Include in `codegraph validate` output
4. Separate from dangling rules (scope is technically valid but unmatched)

**Files:**
- `codegraph/suggest.py` (modify)

**Dependencies:** H-009, H-014

**Validation:**
- Glob matching nothing → warning
- Glob matching something → no warning

---

### TASK H-016 — Implement Rule Import from Template

**Description:**
Support importing predefined rule sets (e.g., "python-web-app", "microservice") as starting points.

**Reasoning:**
New projects benefit from common policy templates. Reduces bootstrapping effort.

**Implementation Steps:**
1. Implement `import_rules_template(template_name: str, project_root: Path)`
2. Ship built-in templates as YAML/JSON files
3. Merge imported rules with existing rules (no overwrite)
4. Templates: generic Python, web app, CLI app

**Files:**
- `codegraph/suggest.py` (modify)
- `codegraph/templates/` (new directory)

**Dependencies:** H-001

**Validation:**
- Template import adds rules
- Existing rules preserved
- Invalid template name → error with available list

---

### TASK H-017 — Implement Rule Versioning

**Description:**
Track when rules were added/modified and by whom.

**Reasoning:**
In team settings, knowing who added a rule and when helps resolve disagreements about policy.

**Implementation Steps:**
1. Add optional `created_at`, `updated_at`, `author` fields to rules
2. Auto-populate on add/modify
3. Preserve on load/save cycle
4. Display in `suggest list --verbose`

**Files:**
- `codegraph/suggest.py` (modify)
- `codegraph/models/suggested_workflow.py` (modify)

**Dependencies:** H-001, B-008

**Validation:**
- New rules get timestamps
- Existing rules without timestamps load fine (backward compat)

---

### TASK H-018 — Implement Rule Priority/Severity

**Description:**
Allow rules to have severity levels (error, warning, info) to control how violations are reported.

**Reasoning:**
Not all policy violations are equal. Some are critical security policies, others are style preferences.

**Implementation Steps:**
1. Add optional `severity` field to rules: "error", "warning", "info"
2. Default to "error" if not specified
3. Filter violations by severity in reporting
4. Severity affects task priority generation

**Files:**
- `codegraph/suggest.py` (modify)
- `codegraph/models/suggested_workflow.py` (modify)

**Dependencies:** H-001, B-008

**Validation:**
- Severity field persists
- Default works when absent
- Filtering by severity works

---

### TASK H-019 — Implement Suggested Workflow Validation

**Description:**
Validate the entire suggested_workflow.json for structural and semantic correctness.

**Reasoning:**
Manual edits may introduce errors. Validation catches them before they cause analysis failures.

**Implementation Steps:**
1. Implement `validate_suggested_workflow(sw, graph0) -> list[Issue]`
2. Structural checks: valid JSON, required fields present, valid enum values
3. Semantic checks: dangling rules, zero-match wildcards, no contradictions
4. Contradiction check: same source+target with both required and forbidden

**Files:**
- `codegraph/suggest.py` (modify)

**Dependencies:** H-014, H-015

**Edge Cases:**
- Required and forbidden for same call → contradiction error
- Overlapping glob scopes → info (not necessarily wrong)

**Validation:**
- Structural errors caught
- Contradictions detected
- Valid file passes

---

### TASK H-020 — Implement Policy Diff Report

**Description:**
Generate a comparison between suggested workflow and actual workflow, showing satisfied, violated, and unverifiable rules.

**Reasoning:**
This diff is the core input to the analyzer and task generator. It must be comprehensive and actionable.

**Implementation Steps:**
1. Implement `policy_diff(suggested, workflow, graph0, graph1) -> PolicyDiff`
2. Classify each rule as:
   - `satisfied`: rule condition met
   - `violated`: rule condition broken
   - `unverifiable`: source or target don't exist
   - `dangling`: scope matches nothing
3. Include details for each violated rule (which nodes, which missing edges)

**Files:**
- `codegraph/suggest.py` (modify)

**Dependencies:** H-010, H-014

**Validation:**
- All rules classified
- Violated rules have details
- Unverifiable rules separated from violations

---

### TASK H-021 — Implement Rule Serialization Compatibility

**Description:**
Ensure suggested_workflow.json format is forward and backward compatible.

**Reasoning:**
As the rule format evolves (new fields, new scope types), old files must still load.

**Implementation Steps:**
1. Add `schema_version` to suggested_workflow.json header
2. Implement version-based deserialization
3. Unknown fields → preserved (forward compat)
4. Missing optional fields → default values (backward compat)

**Files:**
- `codegraph/suggest.py` (modify)

**Dependencies:** H-001

**Validation:**
- Old format files load with defaults
- New format files with unknown fields preserved

---

### TASK H-022 — Implement Suggested Workflow Promotion from Analysis

**Description:**
Support promoting workflow suggestions (from analyzer) to permanent suggested_workflow.json rules.

**Reasoning:**
README mentions workflow suggestions in agent responses can be promoted to permanent rules.

**Implementation Steps:**
1. Implement `promote_suggestion(suggestion, project_root)`
2. Parse agent's workflow suggestion
3. Convert to SuggestedWorkflowRule format
4. Add to suggested_workflow.json
5. Log the promotion

**Files:**
- `codegraph/suggest.py` (modify)

**Dependencies:** H-011, B-011

**Validation:**
- Agent suggestion converts to rule
- Rule added to file
- No duplicate promotion

---

### TASK H-023 — Implement Rule Dependency Checking

**Description:**
Check for circular or conflicting dependencies between rules.

**Reasoning:**
Complex rule sets may have circular requirements or contradictions that make compliance impossible.

**Implementation Steps:**
1. Implement `check_rule_dependencies(rules) -> list[RuleConflict]`
2. Build rule dependency graph
3. Detect cycles (A requires B, B requires A through forbidden chain)
4. Detect contradictions (same pair, required + forbidden)

**Files:**
- `codegraph/suggest.py` (modify)

**Dependencies:** H-010

**Validation:**
- Circular dependencies detected
- Direct contradictions detected
- Independent rules pass

---

### TASK H-024 — Implement Rule Statistics Dashboard

**Description:**
Generate comprehensive statistics about the suggested workflow and its compliance.

**Reasoning:**
Project health dashboards need rule compliance metrics.

**Implementation Steps:**
1. Implement `rule_statistics(suggested, workflow, graph0) -> RuleStats`
2. Report:
   - Total rules, by type
   - Compliance rate (satisfied / total)
   - Most violated rules
   - Dangling rules count
   - Coverage (percentage of nodes covered by at least one rule)

**Files:**
- `codegraph/suggest.py` (modify)

**Dependencies:** H-010, H-014

**Validation:**
- Statistics match manual count
- Compliance rate accurate

---

### TASK H-025 — Implement Suggested Workflow JSON Schema Validator

**Description:**
Create a JSON schema for suggested_workflow.json and validate against it.

**Reasoning:**
Machine-readable schema prevents malformed rule files and enables IDE autocompletion.

**Implementation Steps:**
1. Define JSON Schema for suggested_workflow.json
2. Store schema in `codegraph/schemas/suggested_workflow_schema.json`
3. Validate on load using jsonschema library
4. Provide clear error messages on schema violation

**Files:**
- `codegraph/schemas/suggested_workflow_schema.json`
- `codegraph/suggest.py` (modify)

**Dependencies:** H-001, A-015

**Validation:**
- Valid file passes schema
- Invalid file reports specific error
- Schema published for IDE use
---

### TASK H-026 — Add Semantic Policy Rule Types to Schema

**Description:**
Extend the suggested workflow schema and rule parser to support semantic-aware rule types: `requires_guard`, `forbidden_effect`, `required_effect`, `domain_boundary`, `action_sequence`.

**Reasoning:**
Structural rules ("A must call B") are necessary but insufficient. Semantic rules ("functions that MUTATE must have a GUARD") encode behavioral invariants. This integrates R-025 rule types into the existing policy infrastructure.

**Implementation Steps:**
1. Add semantic rule types to `suggested_workflow_schema.json`
2. Add `semantic_rule: bool` field to rule model
3. Parse semantic rules in rule loader
4. Validate that action_type and effect_type references match known enums

**Files:**
- `codegraph/schemas/suggested_workflow_schema.json` (modify)
- `codegraph/suggest.py` (modify)

**Dependencies:** R-025, H-001, H-025

**Validation:**
- Semantic rules parse correctly
- Invalid enum references caught during validation
- schema accepts both structural and semantic rules

---

### TASK H-027 — Integrate Semantic Violation Detector into Policy Engine

**Description:**
Wire the semantic policy violation detector (R-026) into the existing policy evaluation pipeline so semantic rules are checked alongside structural rules.

**Reasoning:**
Semantic violations must surface in the same reports and analysis results as structural violations, providing a unified compliance view.

**Implementation Steps:**
1. Call `evaluate_semantic_rules()` (R-026) from the policy evaluation flow
2. Merge semantic violations into the same violation result list
3. Tag semantic violations with `source: "semantic"` for filtering
4. Ensure semantic rule violations generate tasks like structural violations

**Files:**
- `codegraph/suggest.py` (modify)
- `codegraph/analyzer.py` (modify)

**Dependencies:** R-026, H-010, I-001

**Validation:**
- Semantic violations appear in analysis results
- Violations tagged as semantic
- Task generation includes semantic policy violations