# Group N — CLI Interface

> Click-based CLI scaffolding, all command implementations, output formatting, flags, error handling, and shell integration via `cli.py`.

---

### TASK N-001 — Implement CLI Framework Setup

**Description:**
Set up the Click-based CLI entry point with command group and global options.

**Reasoning:**
All codegraph functionality is accessed via CLI. Click provides stable, testable command parsing.

**Implementation Steps:**
1. Create `codegraph/cli.py`
2. Implement Click `@click.group()` as main entry point
3. Global options: `--verbose`, `--quiet`, `--json`, `--config`
4. Set up logging based on verbosity
5. Configure entry point in `pyproject.toml`: `codegraph = codegraph.cli:main`

**Files:**
- `codegraph/cli.py`

**Dependencies:** A-002, A-006

**Validation:**
- `codegraph --help` shows all commands
- Global options parsed correctly
- Entry point works after install

---

### TASK N-002 — Implement `codegraph build` Command

**Description:**
Full build command: extract AST, build Graph_0, initialize Graph_1, build workflow, build index.

**Reasoning:**
The build command is the initial setup. It creates everything from scratch.

**Implementation Steps:**
1. Implement `@cli.command() build(trace, archi, trace_all, level, include_imports)`
2. Steps:
   a. Discover source files
   b. Extract AST → Graph_0
   c. Initialize Graph_1 (preserve existing intents)
   d. Assign layers
   e. Build workflow (with optional trace)
   f. Build index
   g. Record commit hash
   h. Display summary
3. Flags: `--trace`, `--archi`, `--trace-all`, `--level`, `--include-imports`

**Files:**
- `codegraph/cli.py` (modify)

**Dependencies:** C-024, E-001, D-007, F-018, G-007, A-012

**Validation:**
- Full build completes on sample project
- All artifacts created in `.codegraph/`
- Summary displayed

---

### TASK N-003 — Implement `codegraph status` Command

**Description:**
Show current graph state: version, node counts, edge counts, staleness.

**Reasoning:**
Quick health check of the codegraph state.

**Implementation Steps:**
1. Implement `@cli.command() status()`
2. Display:
   - Graph version
   - Node count (by type, by layer)
   - Edge count (by type, by confidence)
   - Intent coverage (% of nodes with intent)
   - Stale intents count
   - Graph staleness (any changes since last build?)
   - Task count (if tasks exist)
3. Use `--verbose` for detailed breakdown
4. Use `--json` for machine output

**Files:**
- `codegraph/cli.py` (modify)

**Dependencies:** B-013, F-022, K-019

**Validation:**
- All metrics displayed
- Verbose shows more detail
- JSON output valid

---

### TASK N-004 — Implement `codegraph tasks` Command

**Description:**
Display current task list from tasks.json.

**Reasoning:**
Show the agent what work needs to be done.

**Implementation Steps:**
1. Implement `@cli.command() tasks(filter, format)`
2. Load tasks.json
3. Display tasks sorted by priority
4. Flags: `--filter type=X`, `--format json|text|table`
5. Include pre-fetched context in verbose mode
6. Show task count summary

**Files:**
- `codegraph/cli.py` (modify)

**Dependencies:** I-012, I-015

**Validation:**
- Tasks displayed sorted by priority
- Filtering works
- Format options work

---

### TASK N-005 — Implement `codegraph explain` Command

**Description:**
Show comprehensive information about a specific node.

**Reasoning:**
`codegraph explain "file::class::function"` gives full node details.

**Implementation Steps:**
1. Implement `@cli.command() explain(node_id)`
2. Call L-016 explain function
3. Display all node information
4. Support `--json` output
5. Handle node not found with suggestions

**Files:**
- `codegraph/cli.py` (modify)

**Dependencies:** L-016

**Validation:**
- Node info displayed
- Not found shows suggestions
- JSON output valid

---

### TASK N-006 — Implement `codegraph query` Command

**Description:**
Execute graph queries: callers, callees, dependencies, dependents, path, orphans, layer.

**Reasoning:**
Main interactive query interface.

**Implementation Steps:**
1. Implement `@cli.command() query(query_string, depth, limit, format)`
2. Parse query string
3. Execute query
4. Display results
5. Handle invalid queries with helpful errors
6. Flags: `--depth N`, `--limit N`, `--format text|json|tree|count`

**Files:**
- `codegraph/cli.py` (modify)

**Dependencies:** L-013

**Validation:**
- All query types work
- Flags applied
- Error messages helpful

---

### TASK N-007 — Implement `codegraph suggest` Command Group

**Description:**
Subcommands: `suggest add`, `suggest remove`, `suggest list`.

**Reasoning:**
Manage suggested workflow rules via CLI.

**Implementation Steps:**
1. Implement Click subgroup: `@cli.group() suggest()`
2. `suggest add --type required_call --source ... --target ... --scope ... [--reason ...]`
3. `suggest remove --source ... --target ... [--type ...]`
4. `suggest list [--filter ...]`
5. All subcommands display confirmation

**Files:**
- `codegraph/cli.py` (modify)

**Dependencies:** H-011, H-012, H-013

**Validation:**
- Add creates rule
- Remove deletes rule
- List shows rules

---

### TASK N-008 — Implement `codegraph apply` Command

**Description:**
Apply agent responses from agent_response.json.

**Reasoning:**
Executes the agent's repair actions.

**Implementation Steps:**
1. Implement `@cli.command() apply(response_file, dry_run)`
2. Load agent_response.json
3. Validate version
4. Apply actions
5. Display results
6. Flags: `--dry-run`, `--response-file <path>` (default: `.codegraph/agent_response.json`)

**Files:**
- `codegraph/cli.py` (modify)

**Dependencies:** J-001

**Validation:**
- Apply executes correctly
- Dry run shows diff without changes
- Version mismatch rejected

---

### TASK N-009 — Implement `codegraph delta` Command

**Description:**
Run incremental update to detect and process changes.

**Reasoning:**
After code changes, delta updates the graph without full rebuild.

**Implementation Steps:**
1. Implement `@cli.command() delta(dry_run)`
2. Execute delta engine
3. Display changes summary
4. Flags: `--dry-run`, `--verbose`

**Files:**
- `codegraph/cli.py` (modify)

**Dependencies:** K-001

**Validation:**
- Delta runs and detects changes
- Summary displayed
- Dry run works

---

### TASK N-010 — Implement `codegraph workflow` Command

**Description:**
Build/rebuild the workflow graph with various options.

**Reasoning:**
Separate workflow rebuild without full AST re-extraction.

**Implementation Steps:**
1. Implement `@cli.command() workflow(trace, archi, trace_all, level, include_imports)`
2. Rebuild workflow from existing Graph_0
3. Apply trace modes as selected
4. Apply filters
5. Display summary

**Files:**
- `codegraph/cli.py` (modify)

**Dependencies:** F-018

**Validation:**
- Workflow rebuilds correctly
- Trace options work
- Level compression works

---

### TASK N-011 — Implement `codegraph prune` Command

**Description:**
Remove stale intents, dangling rules, and orphan metadata.

**Reasoning:**
Cleanup command to remove outdated graph entries.

**Implementation Steps:**
1. Implement `@cli.command() prune(dry_run)`
2. Prune:
   - Stale intents (body_hash mismatch)
   - Dangling suggested workflow rules
   - Graph_1 entries for deleted nodes
3. Display what was pruned
4. `--dry-run` to preview

**Files:**
- `codegraph/cli.py` (modify)

**Dependencies:** E-007, H-014

**Validation:**
- Stale data removed
- Dry run shows what would be removed
- Valid data preserved

---

### TASK N-012 — Implement `codegraph validate` Command

**Description:**
Run all validation checks on the graph state.

**Reasoning:**
Comprehensive health check: graph consistency, workflow integrity, index consistency, rule validity.

**Implementation Steps:**
1. Implement `@cli.command() validate()`
2. Run validations:
   - Graph_0 structure validation
   - Graph_1 consistency check
   - Workflow edge validation
   - Index consistency check
   - Suggested workflow validation
3. Display all issues found
4. Exit code: 0=valid, 1=issues found

**Files:**
- `codegraph/cli.py` (modify)

**Dependencies:** F-020, G-010, H-019

**Validation:**
- All validation checks run
- Issues clearly reported
- Exit code correct

---

### TASK N-013 — Implement `codegraph diff` Command

**Description:**
Show differences between current and previous graph state.

**Reasoning:**
Visual diff of Graph_0, Graph_1, and workflow changes.

**Implementation Steps:**
1. Implement `@cli.command() diff(target)` where target is "graph", "workflow", or "all"
2. Load previous and current states
3. Display structured diff
4. Color coding for additions/removals
5. `--json` for machine output

**Files:**
- `codegraph/cli.py` (modify)

**Dependencies:** K-018, F-030

**Validation:**
- Diff shows changes correctly
- Color coding works in terminal
- JSON output valid

---

### TASK N-014 — Implement `codegraph archi-test` Command

**Description:**
Generate and/or run architecture tests.

**Reasoning:**
Entry point for architecture test management.

**Implementation Steps:**
1. Implement `@cli.command() archi_test(generate, run, cleanup)`
2. `--generate`: generate new archi tests
3. `--run`: run existing archi tests
4. `--cleanup`: remove orphaned archi tests
5. Default (no flag): generate + run

**Files:**
- `codegraph/cli.py` (modify)

**Dependencies:** M-001, M-003, M-015

**Validation:**
- Generate creates tests
- Run executes tests
- Cleanup removes orphans

---

### TASK N-015 — Implement `codegraph intent-apply` Command

**Description:**
Apply intent annotations to nodes from a file or inline specification.

**Reasoning:**
Batch intent application for bootstrapping.

**Implementation Steps:**
1. Implement `@cli.command() intent_apply(file, node, intent)`
2. Two modes:
   - File mode: `--file intents.yaml` with batch definitions
   - Inline mode: `--node "x::y::z" --intent "description"`
3. Apply intents to Graph_1
4. Display results

**Files:**
- `codegraph/cli.py` (modify)

**Dependencies:** E-002, E-004

**Validation:**
- File mode applies all intents
- Inline mode applies single intent
- Results displayed

---

### TASK N-016 — Implement `codegraph intent-missing` Command

**Description:**
List all nodes that don't have intent annotations.

**Reasoning:**
Quick view of annotation coverage gaps.

**Implementation Steps:**
1. Implement `@cli.command() intent_missing(layer, format)`
2. Call I-005 missing intent function
3. Display results grouped by file
4. Flags: `--layer N` to filter, `--format text|json`

**Files:**
- `codegraph/cli.py` (modify)

**Dependencies:** I-005

**Validation:**
- Missing intents listed
- Layer filter works
- Output formats work

---

### TASK N-017 — Implement `codegraph analyze` Command

**Description:**
Run full analysis and generate tasks.

**Reasoning:**
Main analysis entry point that produces the task batch.

**Implementation Steps:**
1. Implement `@cli.command() analyze(output)`
2. Run full analysis pipeline
3. Generate tasks
4. Write tasks.json
5. Display summary with task counts
6. Flag: `--output` to specify tasks.json location

**Files:**
- `codegraph/cli.py` (modify)

**Dependencies:** I-030

**Validation:**
- Analysis runs completely
- Tasks generated
- Summary displayed

---

### TASK N-018 — Implement `codegraph index rebuild` Command

**Description:**
Rebuild graph indexes from committed graph files.

**Reasoning:**
Recovery command when indexes become inconsistent.

**Implementation Steps:**
1. Implement as subcommand: `codegraph index rebuild`
2. Delete existing index databases
3. Rebuild all indexes
4. Display timing and statistics

**Files:**
- `codegraph/cli.py` (modify)

**Dependencies:** G-009

**Validation:**
- Indexes rebuilt
- Timing displayed
- Consistent after rebuild

---

### TASK N-019 — Implement `codegraph schema` Command

**Description:**
Export JSON schemas for all data formats.

**Reasoning:**
Agents and tools need schemas to generate valid data.

**Implementation Steps:**
1. Implement `@cli.command() schema(name)`
2. Export schema for: graph0, graph1, workflow, suggested_workflow, tasks, agent_response, delta
3. Output to stdout or file
4. List available schemas with no argument

**Files:**
- `codegraph/cli.py` (modify)

**Dependencies:** A-015, I-027

**Validation:**
- All schemas exportable
- Schemas are valid JSON Schema
- List shows all available

---

### TASK N-020 — Implement Output Formatting System

**Description:**
Create a unified output formatting system supporting text, JSON, and table formats.

**Reasoning:**
Multiple commands need the same output format options. A unified system prevents duplication.

**Implementation Steps:**
1. Implement `OutputFormatter` class in `codegraph/formatters.py`
2. Support formats: text (default), json, table, csv
3. Handle: single values, lists, dictionaries, nested structures
4. Respect `--verbose`, `--quiet` flags
5. Color support for terminals (via click.style)

**Files:**
- `codegraph/formatters.py`

**Dependencies:** A-005

**Validation:**
- All formats produce correct output
- Verbose adds detail
- Quiet reduces output

---

### TASK N-021 — Implement Error Display Handler

**Description:**
Create a unified error handler that formats errors consistently and provides actionable guidance.

**Reasoning:**
All 17+ failure modes need clear error messages with recovery instructions.

**Implementation Steps:**
1. Implement `handle_error(error: CodegraphError, verbose: bool)` in CLI
2. For each error type:
   - Clear description of what went wrong
   - What caused it (file, node, operation)
   - How to fix it (specific commands or actions)
3. In verbose mode: include full traceback
4. In quiet mode: just the error message

**Files:**
- `codegraph/cli.py` (modify)

**Dependencies:** A-007

**Validation:**
- Each error type has clear message
- Recovery instructions present
- Verbose shows traceback

---

### TASK N-022 — Implement Progress Indicators

**Description:**
Show progress bars/spinners for long-running operations.

**Reasoning:**
Build, trace, and analyze can take seconds to minutes. Progress feedback is essential.

**Implementation Steps:**
1. Use Click's progress bar for file iteration
2. Use spinner for analysis/trace operations
3. Show: current file, elapsed time, estimated remaining
4. Respect `--quiet` (no progress) and `--json` (no progress)

**Files:**
- `codegraph/cli.py` (modify)

**Dependencies:** A-019

**Validation:**
- Progress shown during build
- Quiet mode suppresses progress
- JSON mode suppresses progress

---

### TASK N-023 — Implement CLI Configuration from Config File

**Description:**
Load CLI defaults from config.yaml to reduce repetitive flag specification.

**Reasoning:**
Users shouldn't need to specify `--level module` every time if that's their preference.

**Implementation Steps:**
1. Read config.yaml for CLI defaults
2. Config options:
   - default_level: function|class|module
   - default_format: text|json
   - trace_by_default: true|false
   - verbose: true|false
3. CLI flags override config file
4. `--config` flag to specify config path

**Files:**
- `codegraph/cli.py` (modify)

**Dependencies:** A-009

**Validation:**
- Config defaults applied
- CLI flags override config
- Missing config uses built-in defaults

---

### TASK N-024 — Implement Command Timing and Statistics

**Description:**
Display execution time and statistics for each command.

**Reasoning:**
Performance tracking helps users identify slow operations.

**Implementation Steps:**
1. Wrap each command with timing decorator
2. In verbose mode: show execution time at end
3. Show: total time, files processed, nodes affected
4. Store timing history for `codegraph status --verbose`

**Files:**
- `codegraph/cli.py` (modify)

**Dependencies:** N-001

**Validation:**
- Timing displayed for all commands
- Statistics accurate
- Only in verbose mode

---

### TASK N-025 — Implement CLI Shell Completion

**Description:**
Support shell completion for commands, flags, and node IDs.

**Reasoning:**
Tab completion makes CLI usage much faster.

**Implementation Steps:**
1. Use Click's built-in shell completion support
2. Complete: command names, flag names
3. Custom completion for: node IDs (from index), query functions, rule types
4. Support: bash, zsh, fish
5. Add shell completion install instructions

**Files:**
- `codegraph/cli.py` (modify)

**Dependencies:** N-001, G-012

**Validation:**
- Command completion works
- Node ID completion works
- Install instructions clear

---

### TASK N-026 — Implement `codegraph init` Command

**Description:**
Initialize codegraph in a project: create `.codegraph/` directory, generate default config.

**Reasoning:**
First-run experience for new projects.

**Implementation Steps:**
1. Implement `@cli.command() init()`
2. Create `.codegraph/` directory structure
3. Generate default `config.yaml`
4. Add `.codegraph/` to `.gitignore` (specific files only)
5. Display next steps guidance

**Files:**
- `codegraph/cli.py` (modify)

**Dependencies:** A-008, A-009, A-011

**Validation:**
- Directory created
- Config generated
- Gitignore updated

---

### TASK N-027 — Implement `codegraph version` Command

**Description:**
Display codegraph version and environment information.

**Reasoning:**
Essential for debugging and support.

**Implementation Steps:**
1. Implement `@cli.command() version()`
2. Display: codegraph version, Python version, path, git version
3. For `--verbose`: installed dependencies with versions

**Files:**
- `codegraph/cli.py` (modify)

**Dependencies:** A-001

**Validation:**
- Version displayed
- Verbose shows dependencies

---

### TASK N-028 — Implement CLI Exit Code Convention

**Description:**
Define and implement consistent exit codes for all commands.

**Reasoning:**
CI/CD integration requires predictable exit codes.

**Implementation Steps:**
1. Define exit codes:
   - 0: success
   - 1: error (general)
   - 2: validation issues found
   - 3: version mismatch
   - 4: configuration error
2. Implement in all command handlers
3. Document exit codes

**Files:**
- `codegraph/cli.py` (modify)

**Dependencies:** N-001

**Validation:**
- Correct exit codes for each scenario
- CI/CD can rely on exit codes

---

### TASK N-029 — Implement CLI Logging Configuration

**Description:**
Configure structured logging based on CLI verbosity flags.

**Reasoning:**
Debug information must be accessible when needed but hidden by default.

**Implementation Steps:**
1. `--quiet`: WARNING only, no progress
2. Default: INFO, progress output
3. `--verbose`: DEBUG, full details, timing
4. `--json`: structured JSON log output
5. Log to stderr, output to stdout

**Files:**
- `codegraph/cli.py` (modify)

**Dependencies:** A-006

**Validation:**
- Verbosity levels work correctly
- Logs go to stderr
- Output goes to stdout

---

### TASK N-030 — Implement CLI Integration Tests

**Description:**
Create integration tests that exercise the full CLI command suite.

**Reasoning:**
CLI is the user-facing interface. Every command must work end-to-end.

**Implementation Steps:**
1. Use Click's `CliRunner` for testing
2. Test each command with valid inputs
3. Test error handling for each command
4. Test flag combinations
5. Use sample project fixture

**Files:**
- `tests/test_cli.py`

**Dependencies:** N-001 through N-029

**Validation:**
- All commands tested
- Error paths tested
- Flag combinations tested

---

### TASK N-031 — Implement `codegraph test-impact` Command

**Description:**
Show which tests are affected by recent changes.

**Reasoning:**
Quick way to know which tests to run after making changes.

**Implementation Steps:**
1. Implement `@cli.command() test_impact(since, format)`
2. Detect changes since last build (or `--since commit`)
3. Run test impact analysis
4. Display affected tests
5. Support `--format pytest` for pytest command output

**Files:**
- `codegraph/cli.py` (modify)

**Dependencies:** M-007, M-012

**Validation:**
- Affected tests displayed
- Format options work
- Since flag works

---

### TASK N-032 — Implement `codegraph repair` Command

**Description:**
Run the automated repair loop.

**Reasoning:**
Entry point for the convergence-based repair loop.

**Implementation Steps:**
1. Implement `@cli.command() repair(max_iterations, dry_run)`
2. Run repair loop with convergence tracking
3. Display iteration progress
4. Show convergence metrics
5. Flags: `--max-iterations N` (default 10), `--dry-run`

**Files:**
- `codegraph/cli.py` (modify)

**Dependencies:** I-019

**Validation:**
- Repair loop runs
- Convergence shown
- Max iterations respected

---

### TASK N-033 — Implement Multi-Command Pipeline Support

**Description:**
Support running multiple commands in sequence: `codegraph build && codegraph analyze && codegraph tasks`.

**Reasoning:**
Common workflows combine multiple commands. Pipeline support makes this smooth.

**Implementation Steps:**
1. Implement `@cli.command() pipeline(steps)` or `@cli.command() run_all()`
2. Pre-defined pipelines:
   - `full`: build → analyze → tasks
   - `update`: delta → analyze → tasks
   - `check`: validate → status
3. Stop on first error unless `--continue` flag

**Files:**
- `codegraph/cli.py` (modify)

**Dependencies:** N-002, N-009, N-017

**Validation:**
- Pipeline runs commands in order
- Error stops pipeline
- Continue flag works
