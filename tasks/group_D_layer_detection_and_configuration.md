# Group D — Layer Detection & Configuration

> Layer assignment system, automatic detection rules, configuration loading, and trust boundary enforcement via `layers.py`.

---

### TASK D-001 — Implement Layer Enum and Constants

**Description:**
Define the layer numbering system (0-4) as an enum with semantic labels.

**Reasoning:**
Layers are referenced throughout the system for access control, filtering, and policy enforcement. A central enum prevents magic numbers.

**Implementation Steps:**
1. Create `codegraph/layers.py`
2. Define `Layer` enum:
   - `STDLIB = 0`
   - `EXTERNAL = 1`
   - `INTERNAL_LIB = 2`
   - `PROJECT = 3`
   - `TEST = 4`
3. Add `is_modifiable() -> bool` (True for 3 and 4 only)
4. Add `description() -> str`

**Files:**
- `codegraph/layers.py`

**Dependencies:** A-005

**Validation:**
- Layer values match README
- `is_modifiable()` returns True only for 3 and 4

---

### TASK D-002 — Implement Stdlib Detection

**Description:**
Detect whether a module/file belongs to the Python standard library (layer 0).

**Reasoning:**
Stdlib modules must be layer 0. Python's `sys.stdlib_module_names` (3.10+) or `isort`'s stdlib list can be used.

**Implementation Steps:**
1. Implement `is_stdlib(module_name: str) -> bool`
2. For Python 3.10+: use `sys.stdlib_module_names`
3. For Python 3.9: use bundled list of stdlib module names
4. Handle sub-modules: `os.path` → stdlib
5. Cache the lookup set

**Files:**
- `codegraph/layers.py` (modify)

**Dependencies:** D-001

**Edge Cases:**
- Sub-modules of stdlib (os.path, json.decoder)
- Third-party packages that shadow stdlib names
- Python version-specific stdlib modules

**Validation:**
- `is_stdlib("os")` → True
- `is_stdlib("json")` → True
- `is_stdlib("requests")` → False
- `is_stdlib("os.path")` → True

---

### TASK D-003 — Implement External Dependency Detection

**Description:**
Detect whether a file is from an installed third-party package (layer 1) by checking `site-packages`.

**Reasoning:**
Files under `site-packages` are external dependencies. Agents should never modify them.

**Implementation Steps:**
1. Implement `is_external(file_path: str) -> bool`
2. Check if file path contains `site-packages`
3. Also check against `pip list` installed packages
4. Handle editable installs (`pip install -e`)

**Files:**
- `codegraph/layers.py` (modify)

**Dependencies:** D-001

**Edge Cases:**
- Editable installs (in project directory but are dependencies)
- Vendored dependencies (copied into project)
- Virtual environments at non-standard locations

**Validation:**
- site-packages file → layer 1
- Local project file → not layer 1
- Editable install detection

---

### TASK D-004 — Implement Internal Library Detection

**Description:**
Detect files belonging to configured internal shared libraries (layer 2) from `config.yaml`.

**Reasoning:**
Layer 2 cannot be auto-detected — it requires explicit configuration. The `internal_libs` config specifies which directories are shared infrastructure.

**Implementation Steps:**
1. Implement `is_internal_lib(file_path: str, config: Config) -> bool`
2. Check if file is under any directory listed in `config.internal_libs`
3. Use path prefix matching with normalization
4. Handle relative and absolute paths

**Files:**
- `codegraph/layers.py` (modify)

**Dependencies:** D-001, A-009

**Edge Cases:**
- Empty `internal_libs` config → no layer 2 assignments
- Nested internal lib directories
- Path with `../` traversal

**Validation:**
- File under configured dir → layer 2
- File not under any configured dir → not layer 2
- Empty config → no layer 2 nodes

---

### TASK D-005 — Implement Test Code Detection

**Description:**
Detect test files using standard patterns and configured test directories (layer 4).

**Reasoning:**
Test code is layer 4. Detection uses both standard patterns (`tests/`, `test_*.py`, `*_test.py`) and configured `test_dirs`.

**Implementation Steps:**
1. Implement `is_test(file_path: str, config: Config) -> bool`
2. Check patterns:
   - File is under `tests/` directory
   - File matches `test_*.py` pattern
   - File matches `*_test.py` pattern
   - File is under any directory in `config.test_dirs`
3. Handle case sensitivity on different OS

**Files:**
- `codegraph/layers.py` (modify)

**Dependencies:** D-001, A-009

**Edge Cases:**
- `conftest.py` → treat as test code
- `tests/helpers.py` (test helper, not a test) → still layer 4
- Custom test dirs from config
- Pytest fixtures in non-test directories

**Validation:**
- `tests/test_trade.py` → layer 4
- `test_utils.py` → layer 4
- `utils_test.py` → layer 4
- `src/trade.py` → not layer 4

---

### TASK D-006 — Implement Project Source Detection (Default Layer 3)

**Description:**
Assign layer 3 to all files that don't match layers 0, 1, 2, or 4.

**Reasoning:**
Layer 3 is the default for project source files. It's assigned by exclusion — anything that isn't stdlib, external, internal lib, or test is project source.

**Implementation Steps:**
1. Implement `detect_layer(file_path: str, config: Config) -> int`
2. Apply detection rules in order:
   - stdlib → 0
   - site-packages → 1
   - `internal_libs` config → 2
   - test patterns → 4
   - default → 3
3. Return layer number

**Files:**
- `codegraph/layers.py` (modify)

**Dependencies:** D-002, D-003, D-004, D-005

**Validation:**
- Detection rules applied in correct order
- Default is layer 3
- No file is unassigned

---

### TASK D-007 — Implement Layer Assignment for All Nodes

**Description:**
Assign layers to all Graph_0 nodes during or after extraction.

**Reasoning:**
Every node in Graph_0 needs a layer in Graph_1 for filtering, policy enforcement, and safety checks.

**Implementation Steps:**
1. Implement `assign_layers(nodes: list[Graph0Node], config: Config) -> dict[str, int]`
2. For each node, detect layer based on its file path
3. Return mapping of node_id → layer
4. Used during Graph_1 initialization to set layer field

**Files:**
- `codegraph/layers.py` (modify)

**Dependencies:** D-006, B-001

**Validation:**
- All nodes get a layer
- Layer matches file path rules

---

### TASK D-008 — Implement Layer Validation

**Description:**
Validate that layer assignments are consistent with the detection rules.

**Reasoning:**
Mislabeled layers are a safety risk. Validation catches configuration errors that could let agents modify protected code.

**Implementation Steps:**
1. Implement `validate_layers(graph0: Graph0, graph1: Graph1, config: Config) -> list[LayerWarning]`
2. Check:
   - No layer 0/1 nodes in project directories
   - No layer 3 nodes in site-packages
   - All internal_libs directories exist
   - All test_dirs directories exist
3. Report warnings for any mismatches

**Files:**
- `codegraph/layers.py` (modify)

**Dependencies:** D-007, B-002, B-004

**Validation:**
- Mislabeled nodes detected
- Non-existent configured directories warned
- Valid assignments pass

---

### TASK D-009 — Implement Layer-Based Node Filtering

**Description:**
Create filter functions that return nodes at specific layers or layer ranges.

**Reasoning:**
Many operations need to filter by layer: runtime tracing only includes layers 3-4, agents can only modify 3-4, etc.

**Implementation Steps:**
1. Implement `filter_by_layer(nodes, layer) -> list`
2. Implement `filter_modifiable(nodes) -> list` (layers 3 and 4 only)
3. Implement `filter_project_source(nodes) -> list` (layer 3 only)
4. Implement `filter_test_code(nodes) -> list` (layer 4 only)

**Files:**
- `codegraph/layers.py` (modify)

**Dependencies:** D-007

**Validation:**
- Correct nodes returned per filter
- Empty list when no nodes match

---

### TASK D-010 — Implement Layer Safety Guard

**Description:**
Create a safety check that prevents modifications to non-modifiable layers (0, 1, 2).

**Reasoning:**
The README states: "Agents should only propose modifications to nodes at Layer 3 or Layer 4." The apply system must enforce this.

**Implementation Steps:**
1. Implement `check_modification_safety(node_id: str, graph1: Graph1) -> bool`
2. Return True only if node is at layer 3 or 4
3. Implement `LayerViolationError` exception
4. Used by apply system before modifying any code

**Files:**
- `codegraph/layers.py` (modify)

**Dependencies:** D-001, A-007

**Validation:**
- Layer 0/1/2 modifications blocked
- Layer 3/4 modifications allowed
- Clear error message on violation

---

### TASK D-011 — Implement Config YAML Schema Validation

**Description:**
Validate the structure of `.codegraph/config.yaml` against expected schema.

**Reasoning:**
Invalid config can cause subtle bugs (e.g., misspelled `internal_libs` being silently ignored). Strict validation prevents this.

**Implementation Steps:**
1. Define expected config schema:
   - `internal_libs: list[str]` (optional)
   - `test_dirs: list[str]` (optional)
   - `include_stubs: bool` (optional, default false)
   - `edge_filters: list[str]` (optional)
   - `max_iterations: int` (optional, default 10)
2. Validate loaded config against schema
3. Warn on unknown keys
4. Error on incorrect types

**Files:**
- `codegraph/config.py` (modify)

**Dependencies:** A-009

**Validation:**
- Valid config passes
- Unknown keys produce warning
- Wrong types produce error

---

### TASK D-012 — Implement Config Defaults Documentation

**Description:**
Document all configuration options with their defaults and effects.

**Reasoning:**
Users need to know what can be configured and what the defaults are. Missing documentation leads to misconfiguration.

**Implementation Steps:**
1. Add config documentation to README or separate config reference doc
2. Document each option: name, type, default, description, example
3. Include a complete example config.yaml
4. Document impact of missing config file

**Files:**
- `docs/configuration.md`

**Dependencies:** A-009, D-011

**Validation:**
- All config options documented
- Example config is valid YAML

---

### TASK D-013 — Implement Runtime Layer Override

**Description:**
Allow CLI users to override layer detection for specific files or directories at runtime.

**Reasoning:**
Sometimes a user needs to temporarily treat a file as a different layer for analysis purposes without changing the config file.

**Implementation Steps:**
1. Add `--layer-override` CLI option: `--layer-override src/legacy/:2`
2. Parse override format: `path:layer_number`
3. Apply overrides after automatic detection
4. Log overrides for auditability

**Files:**
- `codegraph/layers.py` (modify)

**Dependencies:** D-006

**Edge Cases:**
- Override to invalid layer number → error
- Override conflicting with config → override wins
- Override for non-existent path → warning

**Validation:**
- Override applied correctly
- Logged for audit
- Invalid values rejected

---

### TASK D-014 — Implement Layer Statistics Reporter

**Description:**
Generate layer distribution statistics for `codegraph status`.

**Reasoning:**
Status output should show how many nodes are at each layer. This helps verify layer detection is working correctly.

**Implementation Steps:**
1. Implement `layer_statistics(graph1: Graph1) -> dict[int, int]`
2. Count nodes per layer
3. Include in status report
4. Format for CLI output

**Files:**
- `codegraph/layers.py` (modify)

**Dependencies:** D-007, B-004

**Validation:**
- Counts match actual node distribution
- All layers represented (including zero counts)

---

### TASK D-015 — Implement Layer Change Detection for Delta

**Description:**
Detect when a file's layer changes between builds (e.g., moved from src/ to tests/).

**Reasoning:**
File relocation can change its layer assignment. Delta should detect this and update Graph_1.

**Implementation Steps:**
1. Compare layer assignments between old and new extraction
2. Flag nodes whose layer changed
3. Include in delta report as metadata
4. Update Graph_1 layer field

**Files:**
- `codegraph/layers.py` (modify)

**Dependencies:** D-007, B-012

**Validation:**
- Moved file gets new layer
- Layer change reported in delta
- Graph_1 updated

---

### TASK D-016 — Implement Virtual Environment Detection

**Description:**
Detect the active virtual environment path to properly identify site-packages.

**Reasoning:**
Virtual environments can be at various locations. Correct identification is needed for layer 1 detection.

**Implementation Steps:**
1. Detect virtualenv using `sys.prefix` vs `sys.base_prefix`
2. Find `site-packages` directory
3. Handle: venv, virtualenv, conda, poetry, pipenv
4. Fall back to system site-packages if no virtualenv

**Files:**
- `codegraph/layers.py` (modify)

**Dependencies:** D-003

**Edge Cases:**
- No virtual environment active
- Multiple site-packages directories
- Conda environments
- Poetry managed environments

**Validation:**
- Correct site-packages path found in venv
- Correct path in conda env
- System site-packages as fallback

---

### TASK D-017 — Implement Layer Violation Reporting for Suggested Workflow

**Description:**
Check for layer constraint violations that should be reported as policy violations.

**Reasoning:**
Suggested workflow rules can use layer-scoped constraints (e.g., layer 3 must not import layer 2). The analyzer needs layer data to check these.

**Implementation Steps:**
1. Implement `check_layer_constraints(workflow: Workflow, rules: SuggestedWorkflow, layers: dict) -> list[PolicyViolation]`
2. For each layer-scoped rule, expand to matching nodes
3. Check whether the edge exists (required) or doesn't exist (forbidden)
4. Return violations

**Files:**
- `codegraph/layers.py` (modify)

**Dependencies:** D-007, B-007, B-006

**Validation:**
- Layer 3 → Layer 2 forbidden rule detects violations
- No violations when constraint satisfied
- Correct expansion of layer-scoped rules

---

### TASK D-018 — Implement Config Hot Reload Detection

**Description:**
Detect when `config.yaml` has changed since last build, triggering a full rebuild recommendation.

**Reasoning:**
The README states: "After changing config.yaml → codegraph build (full rebuild)." The system should detect config changes and warn the user.

**Implementation Steps:**
1. Store config file hash after each build
2. On delta: compare current config hash against stored
3. If changed: warn that a full rebuild is recommended
4. Store hash in `.codegraph/` metadata

**Files:**
- `codegraph/config.py` (modify)
- `codegraph/storage.py` (modify)

**Dependencies:** A-009, A-020

**Validation:**
- Changed config detected
- Warning issued
- Unchanged config produces no warning

---

### TASK D-019 — Implement Editable Install Detection for Layer 1

**Description:**
Handle Python packages installed in editable mode (`pip install -e`) that appear in the project directory but should be layer 1.

**Reasoning:**
Editable installs place packages in the project directory but they're still dependencies. Without special handling, they'd be classified as layer 3.

**Implementation Steps:**
1. Check for `.egg-link` files in site-packages
2. Check for editable install records in `dist-info`
3. Cross-reference with project directory
4. Mark editable-installed packages as layer 1

**Files:**
- `codegraph/layers.py` (modify)

**Dependencies:** D-003, D-016

**Edge Cases:**
- Self-referencing editable install (the codegraph project itself)
- Multiple editable installs
- Stale .egg-link files

**Validation:**
- Editable install correctly identified as layer 1
- False positives avoided

---

### TASK D-020 — Implement Layer Migration Safety Check

**Description:**
When a node's layer changes (e.g., file moved), check that existing intents and rules are still valid.

**Reasoning:**
Moving a file from layer 3 to layer 2 means it's now infrastructure. Existing rules referencing it by layer may break.

**Implementation Steps:**
1. After layer detection, compare against previous assignments
2. For each changed layer:
   - Check if any existing rules reference the old layer
   - Check if the node has repairs pending
   - Warn about potential stale rules
3. Include in delta report

**Files:**
- `codegraph/layers.py` (modify)

**Dependencies:** D-015, B-007

**Validation:**
- Layer change triggers warnings for affected rules
- No false warnings for unchanged layers
