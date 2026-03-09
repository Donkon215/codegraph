# Group A — Project Setup & Architecture

> Foundational scaffolding, package structure, dependency management, configuration system, and project-level infrastructure.

---

### TASK A-001 — Initialize Python Package Structure

**Description:**
Create the top-level Python package directory `codegraph/` with `__init__.py`, establishing the importable module namespace.

**Reasoning:**
All modules (cli, extractor, annotator, etc.) must live under a single importable package. This is the root from which everything else is built.

**Implementation Steps:**
1. Create `codegraph/` directory
2. Create `codegraph/__init__.py` with package version variable `__version__`
3. Define `__all__` exports list
4. Add module-level docstring describing the package purpose

**Files:**
- `codegraph/__init__.py`

**Dependencies:** None

**Edge Cases:**
- Ensure package name does not conflict with any existing PyPI package (verify availability)

**Validation:**
- `import codegraph` succeeds
- `codegraph.__version__` returns a valid semver string

---

### TASK A-002 — Create pyproject.toml with Build Metadata

**Description:**
Define the Python project metadata, build system configuration, and dependency declarations using `pyproject.toml` (PEP 621).

**Reasoning:**
Modern Python packaging requires `pyproject.toml` for build configuration, dependency management, and metadata. This is required before any `pip install -e .` can work.

**Implementation Steps:**
1. Create `pyproject.toml` at repository root
2. Define `[project]` section: name, version, description, authors, license, python_requires (>=3.9)
3. Define `[project.scripts]` section: `codegraph = "codegraph.cli:main"`
4. Define `[build-system]` section using setuptools or hatchling
5. Define `[project.optional-dependencies]` for dev/test extras

**Files:**
- `pyproject.toml`

**Dependencies:** A-001

**Edge Cases:**
- Ensure minimum Python 3.9 is specified
- Declare optional dependency on `black` for code formatting in apply

**Validation:**
- `pip install -e .` succeeds
- `codegraph --help` is accessible from command line

---

### TASK A-003 — Define Core Runtime Dependencies

**Description:**
Identify and declare all runtime dependencies the codegraph package needs.

**Reasoning:**
Explicit dependency declaration ensures reproducible installs. Key dependencies include `click` (CLI framework), `coverage` (runtime tracing), `pyyaml` (config loading), and the Python `ast` module (stdlib, no install needed).

**Implementation Steps:**
1. Research and list all required third-party packages
2. Add to `pyproject.toml` under `[project.dependencies]`
3. Pin minimum versions where API compatibility matters
4. Create `requirements.txt` as alternative install path

**Files:**
- `pyproject.toml` (modify dependencies section)
- `requirements.txt`

**Dependencies:** A-002

**Expected Inputs/Outputs:**
- Input: Library requirements analysis
- Output: Complete dependency list with version constraints

**Validation:**
- Fresh `pip install -e .` in clean venv installs all dependencies
- All imports resolve without error

---

### TASK A-004 — Define Development Dependencies

**Description:**
Declare development-only dependencies: pytest, pytest-cov, black, ruff/flake8, mypy, pre-commit.

**Reasoning:**
Development tooling must be separated from runtime dependencies to keep the production install lightweight.

**Implementation Steps:**
1. Add `[project.optional-dependencies]` section with `dev` extra
2. Include: pytest, pytest-cov, black, ruff, mypy, pre-commit
3. Create `requirements-dev.txt` as alternative

**Files:**
- `pyproject.toml` (modify optional-dependencies)
- `requirements-dev.txt`

**Dependencies:** A-002

**Validation:**
- `pip install -e ".[dev]"` installs all dev tools
- `pytest --version` works
- `black --version` works

---

### TASK A-005 — Create Project Directory Layout

**Description:**
Create the full source directory structure matching the architecture described in the README.

**Reasoning:**
The README defines a specific project structure. All modules must exist (even as stubs) to enable parallel development and prevent import errors.

**Implementation Steps:**
1. Create all module files as per README project structure:
   - `codegraph/cli.py`
   - `codegraph/extractor.py`
   - `codegraph/annotator.py`
   - `codegraph/workflow.py`
   - `codegraph/suggest.py`
   - `codegraph/analyzer.py`
   - `codegraph/tasks.py`
   - `codegraph/delta.py`
   - `codegraph/apply.py`
   - `codegraph/query.py`
   - `codegraph/index.py`
   - `codegraph/archi_test.py`
   - `codegraph/test_impact.py`
   - `codegraph/filters.py`
   - `codegraph/layers.py`
2. Add module-level docstrings to each file
3. Create `tests/` directory with `__init__.py`

**Files:**
- All files listed above
- `tests/__init__.py`

**Dependencies:** A-001

**Validation:**
- All modules are importable from `codegraph` package
- `python -c "from codegraph import cli, extractor, annotator"` succeeds

---

### TASK A-006 — Implement Logging Infrastructure

**Description:**
Create a centralized logging configuration module that all codegraph components use.

**Reasoning:**
Consistent logging across CLI commands, extraction, analysis, and apply steps is critical for debugging and agent observability. The README references multiple warning/error scenarios that need structured logging.

**Implementation Steps:**
1. Create `codegraph/logging_config.py`
2. Configure Python `logging` module with named loggers per component
3. Support log levels: DEBUG, INFO, WARNING, ERROR
4. Support output formats: human-readable (CLI) and JSON (agent consumption)
5. Add `--verbose` / `--quiet` flag support for CLI
6. Ensure log messages include component name and timestamp

**Files:**
- `codegraph/logging_config.py`

**Dependencies:** A-005

**Edge Cases:**
- Log to stderr so stdout remains clean for structured output
- Support `--json-log` flag for machine-parseable log output

**Validation:**
- Logger outputs to stderr
- Log format includes timestamp, level, component
- `--verbose` increases output, `--quiet` suppresses INFO

---

### TASK A-007 — Define Exception Hierarchy

**Description:**
Create a custom exception hierarchy for all codegraph error conditions mentioned in the README's Failure Modes table.

**Reasoning:**
Structured exceptions enable proper error handling, recovery, and informative error messages. The README lists 17+ failure modes that each need distinct handling.

**Implementation Steps:**
1. Create `codegraph/exceptions.py`
2. Define base `CodegraphError` exception
3. Define specific exceptions:
   - `ASTParseError`
   - `ModuleImportError`
   - `IntentConflictError`
   - `NodeIDCollisionError`
   - `StaleBodyHashError`
   - `TraceCrashError`
   - `GraphDriftError`
   - `DanglingRuleError`
   - `RepairConflictError`
   - `VersionMismatchError`
   - `AlreadyConnectedError`
   - `InsufficientDeadCodeSignalsError`
   - `DeltaUncommittedError`
   - `IndexInconsistencyError`
   - `CycleMismatchError`
4. Each exception includes relevant context fields (node_id, file, etc.)

**Files:**
- `codegraph/exceptions.py`

**Dependencies:** A-005

**Validation:**
- All exceptions are subclasses of `CodegraphError`
- Each includes descriptive `__str__` with context
- Unit tests verify exception messages include relevant IDs

---

### TASK A-008 — Create .codegraph Directory Manager

**Description:**
Implement a utility module that initializes and manages the `.codegraph/` directory structure within a target project.

**Reasoning:**
All codegraph artifacts are stored under `.codegraph/`. This module ensures the directory tree exists, handles first-run initialization, and provides path resolution for all subsystems.

**Implementation Steps:**
1. Create `codegraph/storage.py`
2. Implement `ensure_codegraph_dir(project_root)` that creates the full directory tree:
   - `.codegraph/`
   - `.codegraph/graphs/`
   - `.codegraph/workflow/`
   - `.codegraph/index/`
   - `.codegraph/tasks/`
   - `.codegraph/responses/`
   - `.codegraph/test_archi/`
3. Implement path resolution methods for each artifact
4. Implement `is_initialized(project_root) -> bool`

**Files:**
- `codegraph/storage.py`

**Dependencies:** A-005

**Edge Cases:**
- Handle case where `.codegraph/` already exists (idempotent)
- Handle case where project root is not writable
- Handle case where `.codegraph/` is a symlink

**Validation:**
- After `ensure_codegraph_dir()`, all subdirectories exist
- Calling it twice is safe (no errors)
- Path resolution returns correct absolute paths

---

### TASK A-009 — Implement Config Loader for config.yaml

**Description:**
Implement a YAML configuration loader that reads `.codegraph/config.yaml` and provides default values when the file is absent.

**Reasoning:**
The README specifies that `config.yaml` controls layer detection (internal_libs, test_dirs). The system must operate with sensible defaults when no config exists.

**Implementation Steps:**
1. Create `codegraph/config.py`
2. Define `CodegraphConfig` dataclass with fields:
   - `internal_libs: list[str]` (default: [])
   - `test_dirs: list[str]` (default: [])
   - `edge_filters: list[str]` (default: predefined noise list)
   - `max_iterations: int` (default: 10)
   - `convergence_threshold: float` (default: 0.05)
3. Implement `load_config(project_root) -> CodegraphConfig`
4. Handle missing file gracefully with defaults
5. Validate config values and report errors

**Files:**
- `codegraph/config.py`

**Dependencies:** A-008, A-003 (pyyaml)

**Edge Cases:**
- Missing config.yaml → use defaults only
- Invalid YAML syntax → raise clear error with line number
- Unknown keys → warn but do not fail
- Empty file → use defaults

**Validation:**
- Loading from valid YAML produces correct config
- Loading from missing file produces defaults
- Invalid YAML raises informative error

---

### TASK A-010 — Implement Project Root Detection

**Description:**
Implement logic to detect the project root directory by searching for marker files (`.codegraph/`, `.git/`, `pyproject.toml`).

**Reasoning:**
CLI commands can be run from any subdirectory. The system must find the project root to locate `.codegraph/` and the source tree.

**Implementation Steps:**
1. Add `find_project_root(start_path=None) -> Path` to `codegraph/config.py`
2. Walk up from start_path (or cwd) looking for `.codegraph/`, `.git/`, or `pyproject.toml`
3. Return the first directory containing any marker
4. Raise `ProjectNotFoundError` if reaching filesystem root without finding a marker

**Files:**
- `codegraph/config.py` (modify)

**Dependencies:** A-009

**Edge Cases:**
- Running from deeply nested subdirectory
- Multiple markers at different levels (use closest)
- Symlinked directories
- Running from outside any project

**Validation:**
- Finds root from nested subdirectory
- Finds root when `.codegraph/` is the marker
- Raises error when no project found

---

### TASK A-011 — Implement .gitignore Template Generator

**Description:**
Generate a `.gitignore` entries file or append rules for `.codegraph/` artifacts that should not be committed.

**Reasoning:**
The README specifies which files to commit and which to ignore. Incorrect gitignore configuration risks committing derived or sensitive data.

**Implementation Steps:**
1. Add `generate_gitignore(project_root)` to `codegraph/storage.py`
2. Auto-append codegraph-specific ignore rules:
   ```
   .codegraph/graphs/graph0.json
   .codegraph/workflow/workflow.json
   .codegraph/delta.json
   .codegraph/index/
   .codegraph/tasks/
   .codegraph/responses/
   ```
3. Check if rules already exist before appending
4. Preserve existing `.gitignore` content

**Files:**
- `codegraph/storage.py` (modify)

**Dependencies:** A-008

**Edge Cases:**
- `.gitignore` doesn't exist → create it
- Rules already present → skip
- File is read-only

**Validation:**
- After generation, gitignore contains all required rules
- Running twice doesn't duplicate entries
- Existing gitignore content preserved

---

### TASK A-012 — Define Graph Version Counter

**Description:**
Implement a monotonically incrementing `graph_version` stored in Graph_0 metadata, updated on every `build` or `delta`.

**Reasoning:**
`graph_version` is a critical contract between `tasks.json` and `agent_response.json`. Stale responses must be rejected. The version must be durable across process restarts.

**Implementation Steps:**
1. Add `graph_version` management to `codegraph/storage.py`
2. Store version in `.codegraph/graphs/graph0.json` metadata header
3. Implement `get_graph_version() -> int`
4. Implement `increment_graph_version() -> int`
5. Ensure atomic file writes to prevent corruption

**Files:**
- `codegraph/storage.py` (modify)

**Dependencies:** A-008

**Edge Cases:**
- First build → version starts at 1
- Corrupted version field → reset to 1 with warning
- Concurrent access (unlikely but handle gracefully)

**Validation:**
- Version increments on build
- Version increments on delta
- Version is readable after increment
- Version survives process restart

---

### TASK A-013 — Implement Atomic File Writer

**Description:**
Create a utility that writes JSON and YAML files atomically using write-to-temp-then-rename pattern.

**Reasoning:**
Partial writes to graph files during crashes would corrupt the system state. Atomic writes ensure files are either fully written or not modified.

**Implementation Steps:**
1. Add `atomic_write(path, data, format='json')` to `codegraph/storage.py`
2. Write to a temp file in the same directory
3. Flush and fsync the temp file
4. Rename temp file to target path (atomic on POSIX)
5. Support JSON and YAML formats
6. Handle Windows rename behavior (delete-then-rename)

**Files:**
- `codegraph/storage.py` (modify)

**Dependencies:** A-008

**Edge Cases:**
- Disk full during write
- Permission denied on target
- Target directory doesn't exist
- Windows file locking

**Validation:**
- File is fully written or not modified
- Interrupted write doesn't corrupt existing file
- Both JSON and YAML formats work

---

### TASK A-014 — Implement JSON Schema Validators

**Description:**
Create JSON schema definitions and validation functions for all codegraph data structures.

**Reasoning:**
The README defines precise JSON schemas for Graph_0, Graph_1, Workflow edges, tasks.json, agent_response.json, and delta.json. Input validation prevents corrupted data from propagating through the system.

**Implementation Steps:**
1. Create `codegraph/schemas.py`
2. Define validation schemas or Pydantic models for:
   - Graph_0 node
   - Graph_1 node
   - Workflow edge
   - tasks.json structure
   - agent_response.json structure
   - delta.json structure
   - suggested_workflow.json structure
3. Implement `validate_graph0(data)`, `validate_graph1(data)`, etc.
4. Return detailed validation errors with field paths

**Files:**
- `codegraph/schemas.py`

**Dependencies:** A-005

**Edge Cases:**
- Partial data (missing optional fields)
- Extra unknown fields (warn, don't reject)
- Type coercion (string "3" for integer 3)

**Validation:**
- Valid data passes validation
- Invalid data returns specific field errors
- All JSON examples from README validate successfully

---

### TASK A-015 — Create Test Fixtures and Helpers

**Description:**
Set up pytest fixtures, test helpers, and sample project structures used across all test modules.

**Reasoning:**
Tests need reproducible sample projects with known AST structures. Shared fixtures prevent duplication and ensure consistency.

**Implementation Steps:**
1. Create `tests/conftest.py` with common fixtures
2. Create `tests/fixtures/` directory with sample Python projects
3. Create fixture: `sample_project` → temp dir with sample .py files
4. Create fixture: `initialized_project` → sample_project with `.codegraph/` init
5. Create fixture: `sample_graph0`, `sample_graph1`, `sample_workflow`
6. Create helper functions for asserting JSON structure

**Files:**
- `tests/conftest.py`
- `tests/fixtures/sample_project/src/data.py`
- `tests/fixtures/sample_project/src/signal.py`
- `tests/fixtures/sample_project/src/trade.py`
- `tests/fixtures/sample_project/tests/test_data.py`

**Dependencies:** A-005, A-004

**Validation:**
- All fixtures are accessible in test functions
- Sample project has known, stable structure
- Fixtures clean up temp directories

---

### TASK A-016 — Implement Cycle Counter

**Description:**
Implement a cycle counter that tracks how many agent cycles have been executed, stored in `.codegraph/` metadata.

**Reasoning:**
`tasks.json` includes a `cycle` field and responses must echo it. The cycle number helps audit agent history across files in `tasks/` and `responses/`.

**Implementation Steps:**
1. Add cycle tracking to `codegraph/storage.py`
2. Store cycle in `.codegraph/cycle.json` or as metadata in graph0
3. Implement `get_current_cycle() -> int`
4. Implement `increment_cycle() -> int`
5. Ensure cycle increments when `codegraph tasks` generates a new batch

**Files:**
- `codegraph/storage.py` (modify)

**Dependencies:** A-008

**Validation:**
- Cycle starts at 1
- Increments on each tasks generation
- Survives process restart

---

### TASK A-017 — Create Type Stubs and Protocols

**Description:**
Define TypedDict, Protocol, and dataclass types for all core data structures used across modules.

**Reasoning:**
Strong typing enables mypy checking, IDE autocomplete, and catches integration errors early. Shared types prevent each module from defining its own incompatible representations.

**Implementation Steps:**
1. Create `codegraph/types.py`
2. Define TypedDicts:
   - `Graph0Node`, `Graph1Node`, `WorkflowEdge`
   - `TaskItem`, `PolicyViolation`, `RepairAction`
   - `DeltaResult`, `StatusReport`
3. Define enums:
   - `NodeType` (function, class, method, module)
   - `EdgeType` (call, test, trace, dynamic)
   - `Confidence` (runtime, test, static, ai_inferred)
   - `LayerNumber` (0-4)
   - `RepairActionType` (connect_call, add_import, remove_dead_code, flag_for_human_review)
   - `TaskID` (policy_violation, missing_import, orphan_nodes, etc.)
4. Define Protocol classes for pluggable components

**Files:**
- `codegraph/types.py`

**Dependencies:** A-005

**Validation:**
- `mypy codegraph/types.py` passes with no errors
- All types are importable from `codegraph.types`

---

### TASK A-018 — Set Up Pre-commit Hooks

**Description:**
Configure pre-commit hooks for code quality enforcement: black, ruff, mypy.

**Reasoning:**
Automated code quality checks prevent style inconsistencies and catch type errors before they reach the test suite.

**Implementation Steps:**
1. Create `.pre-commit-config.yaml`
2. Configure hooks: black, ruff, mypy
3. Add trailing-whitespace and end-of-file-fixer hooks
4. Test hooks run correctly

**Files:**
- `.pre-commit-config.yaml`

**Dependencies:** A-004

**Validation:**
- `pre-commit run --all-files` passes
- Black reformats are caught
- Type errors are caught

---

### TASK A-019 — Create Makefile / Task Runner

**Description:**
Create a Makefile or `justfile` with common development commands.

**Reasoning:**
Standardized commands reduce onboarding friction and ensure contributors run the right commands.

**Implementation Steps:**
1. Create `Makefile` with targets:
   - `install` → `pip install -e ".[dev]"`
   - `test` → `pytest tests/`
   - `lint` → `ruff check codegraph/`
   - `format` → `black codegraph/ tests/`
   - `typecheck` → `mypy codegraph/`
   - `clean` → remove build artifacts
   - `build` → build distribution package

**Files:**
- `Makefile`

**Dependencies:** A-002, A-004

**Validation:**
- `make install` succeeds
- `make test` runs tests
- `make lint` checks code

---

### TASK A-020 — Implement File Hashing Utility

**Description:**
Create a utility function that computes deterministic file content hashes for change detection.

**Reasoning:**
The delta engine needs to detect file changes. Git diff is one approach, but direct content hashing provides a fallback and enables hash-based caching.

**Implementation Steps:**
1. Add `hash_file(path) -> str` to `codegraph/utils.py`
2. Create `codegraph/utils.py` as general utilities module
3. Use SHA-256 truncated to 12 hex characters
4. Ensure consistent encoding (UTF-8) and line ending normalization

**Files:**
- `codegraph/utils.py`

**Dependencies:** A-005

**Validation:**
- Same file content produces same hash
- Different content produces different hash
- Hash is stable across platforms

---

### TASK A-021 — Implement Body Hash Generator

**Description:**
Create a function that computes AST body hashes for Python functions, ignoring whitespace and comments.

**Reasoning:**
`body_hash` is a core concept — it detects logic changes while ignoring formatting. This must use AST-level comparison, not text-level.

**Implementation Steps:**
1. Add `compute_body_hash(source_code, node_name) -> str` to `codegraph/utils.py`
2. Parse the function body with `ast.parse`
3. Strip all comments and docstrings from the AST
4. Serialize the AST to a canonical form (using `ast.dump`)
5. Hash the canonical form with SHA-256, truncated to 5 hex chars

**Files:**
- `codegraph/utils.py` (modify)

**Dependencies:** A-020

**Edge Cases:**
- Function with only a docstring → valid but minimal hash
- Function with decorators → decorators excluded from body hash
- Lambda expressions
- Nested function definitions

**Validation:**
- Reformatting code doesn't change body_hash
- Adding/removing comments doesn't change body_hash
- Changing logic does change body_hash
- Adding/removing parameters changes body_hash

---

### TASK A-022 — Implement Node ID Generator

**Description:**
Create a function that generates stable node IDs in the format `file::class::function` or `file::function`.

**Reasoning:**
Node IDs are the primary reference key across all graphs. They must be deterministic, stable across minor refactors, and handle collision disambiguation.

**Implementation Steps:**
1. Add `generate_node_id(file_path, class_name, func_name, disambiguator=None) -> str` to `codegraph/utils.py`
2. Use relative path from project root
3. Format: `path/file.py::ClassName::method_name` or `path/file.py::function_name`
4. For modules: `path/file` (no extension)
5. For classes: `path/file.py::ClassName`
6. Add `[N]` suffix for disambiguation when needed

**Files:**
- `codegraph/utils.py` (modify)

**Dependencies:** A-020

**Edge Cases:**
- Nested classes: `file.py::Outer::Inner::method`
- Module-level IDs: `path/module` (no .py)
- Collision disambiguation: `file.py::func[2]`
- Deeply nested paths

**Validation:**
- ID format matches README examples
- Same input produces same ID
- Disambiguator appended correctly
- Module IDs have no extension

---

### TASK A-023 — Create Constants Module

**Description:**
Define all magic strings, default values, and system constants in a centralized module.

**Reasoning:**
Scattered magic strings lead to typos and inconsistency. Centralizing constants ensures all modules reference the same values.

**Implementation Steps:**
1. Create `codegraph/constants.py`
2. Define:
   - File paths: `GRAPH0_FILE`, `GRAPH1_FILE`, `WORKFLOW_FILE`, etc.
   - Directory names: `CODEGRAPH_DIR`, `INDEX_DIR`, etc.
   - Default filter patterns for edge filtering
   - Default dunder methods to filter
   - Task priority ordering
   - Max iteration count (10)
   - Convergence threshold (5%)

**Files:**
- `codegraph/constants.py`

**Dependencies:** A-005

**Validation:**
- All constants are importable
- No duplicate values where uniqueness is required

---

### TASK A-024 — Implement Timestamp Utility

**Description:**
Create a utility for ISO 8601 timestamp generation and parsing.

**Reasoning:**
Multiple schemas require ISO 8601 timestamps (tasks, delta, intents). A single utility ensures consistent formatting.

**Implementation Steps:**
1. Add `iso_now() -> str` to `codegraph/utils.py`
2. Add `parse_iso(s) -> datetime` to `codegraph/utils.py`
3. Always use UTC timezone
4. Format: `YYYY-MM-DDTHH:MM:SSZ`

**Files:**
- `codegraph/utils.py` (modify)

**Dependencies:** A-020

**Validation:**
- Timestamps are valid ISO 8601
- Round-trip: `parse_iso(iso_now())` works
- Always UTC

---

### TASK A-025 — Set Up CI/CD Pipeline Configuration

**Description:**
Create GitHub Actions workflow for continuous integration: test, lint, type-check on every push and PR.

**Reasoning:**
Automated CI prevents regressions and ensures code quality on every change. Essential for a production-grade project.

**Implementation Steps:**
1. Create `.github/workflows/ci.yml`
2. Matrix test against Python 3.9, 3.10, 3.11, 3.12
3. Steps: install deps, lint, typecheck, test with coverage
4. Upload coverage report
5. Fail on lint errors, type errors, or test failures

**Files:**
- `.github/workflows/ci.yml`

**Dependencies:** A-002, A-004

**Validation:**
- Workflow runs on push and PR
- All matrix combinations tested
- Clear failure messages on issues

---

### TASK A-026 — Implement Path Normalization Utility

**Description:**
Create a utility that normalizes file paths to forward-slash, relative-to-project-root format used in node IDs.

**Reasoning:**
Node IDs use forward-slash paths relative to project root. All path inputs (from AST, from CLI, from config) must be normalized consistently.

**Implementation Steps:**
1. Add `normalize_path(absolute_path, project_root) -> str` to `codegraph/utils.py`
2. Convert to relative path from project root
3. Convert backslashes to forward slashes
4. Strip leading `./`
5. Ensure consistency across Windows and Unix

**Files:**
- `codegraph/utils.py` (modify)

**Dependencies:** A-020, A-010

**Edge Cases:**
- Path outside project root → raise error
- Symlinks → resolve before normalizing
- Case sensitivity differences on Windows

**Validation:**
- Windows paths normalized correctly
- Relative paths returned
- Consistent across OS

---

### TASK A-027 — Create Plugin Architecture Stub

**Description:**
Design the extension point architecture for future language support (JS/TS, Go).

**Reasoning:**
The README mentions planned JS/TS and Go support. The extraction layer must be designed for pluggability from the start so adding languages doesn't require refactoring the core.

**Implementation Steps:**
1. Define `LanguageExtractor` Protocol/ABC in `codegraph/types.py`
2. Define required interface: `extract_nodes(file_path) -> list[Graph0Node]`
3. Define required interface: `extract_edges(file_path, nodes) -> list[WorkflowEdge]`
4. Define `supported_extensions() -> list[str]`
5. Create `codegraph/extractors/` directory
6. Create `codegraph/extractors/__init__.py` with registry
7. Move Python-specific extraction to `codegraph/extractors/python.py`

**Files:**
- `codegraph/extractors/__init__.py`
- `codegraph/extractors/python.py` (stub)
- `codegraph/types.py` (modify)

**Dependencies:** A-017

**Validation:**
- `LanguageExtractor` protocol is importable
- Registry can register and retrieve extractors by file extension

---

### TASK A-028 — Implement Git Interface Utility

**Description:**
Create a utility module wrapping common git operations needed by delta engine and diff commands.

**Reasoning:**
The delta engine uses `git diff --name-only HEAD`. The diff command checks out previous commits. These git interactions need a clean abstraction.

**Implementation Steps:**
1. Create `codegraph/git_utils.py`
2. Implement `get_changed_files(since='HEAD') -> list[str]`
3. Implement `get_file_at_commit(file_path, commit) -> str`
4. Implement `is_git_repo(path) -> bool`
5. Implement `get_current_commit() -> str`
6. Handle non-git projects gracefully

**Files:**
- `codegraph/git_utils.py`

**Dependencies:** A-005

**Edge Cases:**
- Not a git repository → return empty list / raise clear error
- Uncommitted changes → handle per README (fall back to full build)
- Binary files in diff → filter out
- Newly added (untracked) files

**Validation:**
- Returns correct changed files from a known git state
- Handles non-git directory gracefully
- Handles uncommitted changes

---

### TASK A-029 — Define Storage Format Versioning

**Description:**
Implement a format version header for all codegraph JSON files to support future migrations.

**Reasoning:**
As the project evolves, JSON schemas will change. Version headers enable forward compatibility and automated migration.

**Implementation Steps:**
1. Add `format_version` field to all JSON output files
2. Define current format version as `1`
3. Implement `check_format_version(data, expected) -> bool`
4. Add migration stub framework for future use

**Files:**
- `codegraph/storage.py` (modify)
- `codegraph/schemas.py` (modify)

**Dependencies:** A-013, A-014

**Validation:**
- All generated JSON files include `format_version`
- Version check correctly rejects mismatched versions

---

### TASK A-030 — Implement Progress Reporter

**Description:**
Create a progress reporting utility for long-running operations (build, workflow trace, index rebuild).

**Reasoning:**
Full builds on large repos can take minutes. Users need feedback on progress. Agents need to know if a command is stalled.

**Implementation Steps:**
1. Add `ProgressReporter` class to `codegraph/utils.py`
2. Support total/current/percentage display
3. Support both interactive (terminal) and non-interactive (agent) modes
4. In agent mode: emit JSON progress events
5. In terminal mode: show progress bar

**Files:**
- `codegraph/utils.py` (modify)

**Dependencies:** A-006

**Edge Cases:**
- Unknown total (use spinner instead of percentage)
- Redirected stdout (disable terminal codes)

**Validation:**
- Progress displays correctly in terminal
- JSON mode emits parseable events
- Unknown total shows indeterminate progress

---

### TASK A-031 — Research SQLite/DuckDB Backend Design

**Description:**
Research and document the design for migrating from JSON to SQLite/DuckDB for large repositories.

**Reasoning:**
The README notes JSON backend is suitable for ~500 files; beyond that, a database backend is needed. This design should inform current interface decisions.

**Research Notes:**
- Evaluate SQLite vs DuckDB for graph storage
- Consider read/write patterns (frequent reads, batch writes)
- Design abstract storage interface that both JSON and DB backends implement
- Consider index integration (indexes could use the same DB)

**Implementation Steps:**
1. Create `docs/adr/001-storage-backend.md` architecture decision record
2. Define `StorageBackend` Protocol
3. Document migration path from JSON to SQLite
4. Identify which operations benefit most from DB backend

**Files:**
- `docs/adr/001-storage-backend.md`

**Dependencies:** A-008

**Validation:**
- ADR is reviewed and captures key tradeoffs
- StorageBackend protocol covers all current JSON operations

---

### TASK A-032 — Implement Error Recovery Framework

**Description:**
Create a recovery framework that handles the failure modes described in the README systematically.

**Reasoning:**
The README lists 17+ failure modes with specific recovery actions. A structured recovery framework ensures consistent handling.

**Implementation Steps:**
1. Create `codegraph/recovery.py`
2. Define recovery strategies for each failure mode:
   - AST parse error → skip file, continue
   - Module import error → mark as layer 1
   - Test crash during trace → fall back to static
   - Delta on uncommitted → fall back to full build
3. Implement `RecoveryHandler` that wraps operations with try/catch and recovery
4. Log all recovery actions

**Files:**
- `codegraph/recovery.py`

**Dependencies:** A-007, A-006

**Validation:**
- Each failure mode triggers correct recovery
- Recovery actions are logged
- Processing continues after recoverable errors

---

### TASK A-033 — Implement Source File Discovery

**Description:**
Create a file discovery utility that finds all Python source files in a project, respecting gitignore and configuration.

**Reasoning:**
The extraction engine needs to know which files to process. File discovery must respect `.gitignore`, exclude `.codegraph/`, and handle configured directories.

**Implementation Steps:**
1. Add `discover_source_files(project_root, config) -> list[Path]` to `codegraph/utils.py`
2. Walk the project directory tree
3. Filter by file extension (`.py` for Python)
4. Respect `.gitignore` patterns
5. Exclude `.codegraph/`, `__pycache__/`, `.git/`, `node_modules/`
6. Include files from `test_dirs` config as test files

**Files:**
- `codegraph/utils.py` (modify)

**Dependencies:** A-009, A-020

**Edge Cases:**
- Symlinked directories → follow or skip (configurable)
- Very large repos with 10k+ files → stream results
- Hidden directories
- Binary files with `.py` extension (unlikely but handle)

**Validation:**
- Finds all `.py` files in sample project
- Excludes `.codegraph/` and `__pycache__/`
- Respects gitignore
- Handles empty project

---

### TASK A-034 — Implement JSON Pretty Printer for CLI Output

**Description:**
Create a utility for formatting JSON output that is both human-readable and machine-parseable.

**Reasoning:**
CLI output must be structured JSON for agent consumption but also readable for human debugging. Consistent formatting across all commands is important.

**Implementation Steps:**
1. Add `format_json(data, compact=False) -> str` to `codegraph/utils.py`
2. Default: indented with 2 spaces for readability
3. Compact mode: single-line for piping to agents
4. Support `--json` flag to force JSON output
5. Support `--compact` flag for minimal formatting

**Files:**
- `codegraph/utils.py` (modify)

**Dependencies:** A-020

**Validation:**
- Output is valid JSON
- Pretty mode is human-readable
- Compact mode is single-line
- All data types serialize correctly

---

### TASK A-035 — Define Abstract Storage Interface

**Description:**
Define an abstract interface for graph storage that can be implemented by JSON (now) and SQLite/DuckDB (later).

**Reasoning:**
Decoupling storage format from business logic enables the planned migration to database backends without refactoring core modules.

**Implementation Steps:**
1. Define `GraphStore` Protocol in `codegraph/types.py`:
   - `load_graph0() -> dict`
   - `save_graph0(data: dict)`
   - `load_graph1() -> dict`
   - `save_graph1(data: dict)`
   - `load_workflow() -> dict`
   - `save_workflow(data: dict)`
   - `load_suggested_workflow() -> dict`
   - `save_suggested_workflow(data: dict)`
   - `load_delta() -> dict`
   - `save_delta(data: dict)`
2. Implement `JsonGraphStore` in `codegraph/storage.py`
3. Use `GraphStore` protocol in all modules

**Files:**
- `codegraph/types.py` (modify)
- `codegraph/storage.py` (modify)

**Dependencies:** A-017, A-013

**Validation:**
- JsonGraphStore implements all protocol methods
- All modules use GraphStore protocol, not concrete class
- Storage is swappable

---

### TASK A-036 — Create Sample/Demo Project for Testing

**Description:**
Create a minimal but realistic sample project that exercises all codegraph features, used for integration testing and documentation.

**Reasoning:**
The README uses a trading project example. A full sample project enables end-to-end testing and serves as a living example for documentation.

**Implementation Steps:**
1. Create `examples/trading/` directory
2. Create `examples/trading/src/data.py` with `fetch_data()` function
3. Create `examples/trading/src/signal.py` with `generate_signal()` function
4. Create `examples/trading/src/trade.py` with `execute_order()`, `validate_trade()` functions
5. Create `examples/trading/src/pipeline.py` with orchestration
6. Create `examples/trading/tests/test_trade.py`
7. Ensure the project mirrors the README examples exactly

**Files:**
- `examples/trading/src/data.py`
- `examples/trading/src/signal.py`
- `examples/trading/src/trade.py`
- `examples/trading/src/pipeline.py`
- `examples/trading/tests/test_trade.py`

**Dependencies:** A-005

**Validation:**
- Sample project is importable
- Functions have realistic structure
- Tests pass with pytest
