# Group P — Documentation, Packaging & Observability

> Package building, PyPI distribution, user documentation, API docs, observability, metrics, security documentation, and contributor guide.

---

### TASK P-001 — Implement PyPI Package Configuration

**Description:**
Configure `pyproject.toml` for PyPI distribution.

**Reasoning:**
codegraph must be installable via `pip install codegraph`.

**Implementation Steps:**
1. Complete `pyproject.toml` metadata:
   - name, version, description, authors, license
   - python_requires >= 3.9
   - classifiers
   - URLs (homepage, documentation, repository)
2. Configure `[project.scripts]` entry point: `codegraph = codegraph.cli:main`
3. Configure `[build-system]` with setuptools or hatchling

**Files:**
- `pyproject.toml` (modify)

**Dependencies:** A-002

**Validation:**
- `pip install .` works
- `codegraph --version` works after install
- Package metadata visible

---

### TASK P-002 — Implement Package Build and Publish Workflow

**Description:**
Create GitHub Actions workflow for building and publishing to PyPI.

**Reasoning:**
Automated release process ensures consistent, correct builds.

**Implementation Steps:**
1. Create `.github/workflows/publish.yml`
2. Trigger on GitHub release creation
3. Steps: build sdist and wheel, upload to PyPI
4. Use `twine` or `gh-action-pypi-publish`
5. Test on TestPyPI first

**Files:**
- `.github/workflows/publish.yml`

**Dependencies:** P-001, O-027

**Validation:**
- Workflow runs on release
- Package uploaded to PyPI
- Installable from PyPI

---

### TASK P-003 — Implement CHANGELOG Management

**Description:**
Set up changelog management for version tracking.

**Reasoning:**
Users need to know what changed between versions.

**Implementation Steps:**
1. Create `CHANGELOG.md` with Keep a Changelog format
2. Document all versions
3. Include: Added, Changed, Deprecated, Removed, Fixed, Security sections
4. Link to git tags

**Files:**
- `CHANGELOG.md`

**Dependencies:** P-001

**Validation:**
- Changelog follows standard format
- Each version documented
- Links work

---

### TASK P-004 — Implement Version Management

**Description:**
Set up single-source version management.

**Reasoning:**
Version should be defined in one place and accessible everywhere.

**Implementation Steps:**
1. Define version in `codegraph/__init__.py`: `__version__ = "0.1.0"`
2. Read from `pyproject.toml` via `importlib.metadata`
3. Use in CLI `--version` command
4. Semantic versioning: MAJOR.MINOR.PATCH

**Files:**
- `codegraph/__init__.py` (modify)

**Dependencies:** A-001, P-001

**Validation:**
- Version accessible programmatically
- Matches pyproject.toml
- CLI version command works

---

### TASK P-005 — Implement User Documentation: Getting Started Guide

**Description:**
Write a getting started guide for first-time users.

**Reasoning:**
New users need a clear path from install to first analysis.

**Implementation Steps:**
1. Create `docs/getting-started.md`
2. Sections:
   - Installation
   - Initialize a project: `codegraph init`
   - First build: `codegraph build`
   - See status: `codegraph status`
   - Run analysis: `codegraph analyze`
   - View tasks: `codegraph tasks`
3. Include example output

**Files:**
- `docs/getting-started.md`

**Dependencies:** N-026, N-002, N-003

**Validation:**
- Guide is followable from scratch
- Commands match actual CLI
- Output examples match reality

---

### TASK P-006 — Implement User Documentation: Concepts Guide

**Description:**
Write documentation explaining the core concepts: graphs, layers, workflow, policy.

**Reasoning:**
Users need to understand the conceptual model before using advanced features.

**Implementation Steps:**
1. Create `docs/concepts.md`
2. Sections:
   - The Six Data Structures (with diagrams)
   - Node Identity system
   - Body Hash and change detection
   - Layer system
   - Workflow edges and confidence levels
   - Suggested Workflow and policy rules
   - Tasks and repair loop
   - Delta and incremental updates

**Files:**
- `docs/concepts.md`

**Dependencies:** None (write from README knowledge)

**Validation:**
- All concepts explained clearly
- Examples for each concept
- Diagrams where helpful

---

### TASK P-007 — Implement User Documentation: CLI Reference

**Description:**
Generate comprehensive CLI reference documentation.

**Reasoning:**
Every command, flag, and output format must be documented.

**Implementation Steps:**
1. Create `docs/cli-reference.md`
2. Auto-generate from Click command definitions
3. For each command:
   - Description
   - Usage
   - All flags and options with descriptions
   - Example invocation and output
   - Exit codes
4. Include global options section

**Files:**
- `docs/cli-reference.md`

**Dependencies:** N-001 through N-033

**Validation:**
- Every command documented
- Examples run successfully
- Auto-generation reproducible

---

### TASK P-008 — Implement User Documentation: JSON Schema Reference

**Description:**
Document all JSON file formats consumed and produced by codegraph.

**Reasoning:**
Agents and tools need to generate valid data.

**Implementation Steps:**
1. Create `docs/schema-reference.md`
2. Document:
   - graph0.json format
   - graph1.json format
   - workflow.json format
   - suggested_workflow.json format
   - tasks.json format
   - agent_response.json format
   - delta.json format
3. Include full examples for each

**Files:**
- `docs/schema-reference.md`

**Dependencies:** A-015

**Validation:**
- All formats documented
- Examples are valid
- Match actual schemas

---

### TASK P-009 — Implement User Documentation: Agent Integration Guide

**Description:**
Write guide for AI agent developers integrating with codegraph.

**Reasoning:**
The primary consumers of codegraph are AI agents. They need clear instructions.

**Implementation Steps:**
1. Create `docs/agent-integration.md`
2. Sections:
   - Reading tasks.json
   - Understanding pre-fetched context
   - Constructing agent_response.json
   - graph_version validation
   - Repair action types and their contracts
   - Workflow suggestions
   - Common mistakes and how to avoid them

**Files:**
- `docs/agent-integration.md`

**Dependencies:** B-010, B-011

**Validation:**
- Guide is sufficient for agent implementation
- All contracts documented
- Error scenarios explained

---

### TASK P-010 — Implement User Documentation: Configuration Guide

**Description:**
Document all configuration options and their effects.

**Reasoning:**
Users need to know how to customize codegraph behavior.

**Implementation Steps:**
1. Create `docs/configuration.md`
2. Document:
   - config.yaml full schema
   - Layer configuration
   - Filter configuration
   - CLI defaults
   - Internal library paths
   - Formatter settings
3. Include annotated example config.yaml

**Files:**
- `docs/configuration.md`

**Dependencies:** A-009

**Validation:**
- All config options documented
- Example config is valid
- Defaults listed

---

### TASK P-011 — Implement User Documentation: Failure Modes Reference

**Description:**
Document all 17+ failure modes: what triggers them, what happens, how to resolve.

**Reasoning:**
When things go wrong, users need quick resolution guidance.

**Implementation Steps:**
1. Create `docs/failure-modes.md`
2. For each failure mode:
   - Name and ID
   - What triggers it
   - What codegraph does (error, warning, skip)
   - How to resolve
   - Prevention
3. Include troubleshooting flowchart

**Files:**
- `docs/failure-modes.md`

**Dependencies:** A-007

**Validation:**
- All 17+ failure modes documented
- Resolution steps actionable
- Matches actual behavior

---

### TASK P-012 — Implement API Documentation (Sphinx/mkdocs)

**Description:**
Set up auto-generated API documentation from docstrings.

**Reasoning:**
Library users and contributors need API reference.

**Implementation Steps:**
1. Choose documentation tool (mkdocs with mkdocstrings or Sphinx)
2. Configure in `mkdocs.yml` or `docs/conf.py`
3. Auto-generate from docstrings
4. Organize by module
5. Deploy to GitHub Pages

**Files:**
- `mkdocs.yml` or `docs/conf.py`
- `docs/` (various pages)

**Dependencies:** P-005 through P-011

**Validation:**
- Docs build without warnings
- All public APIs documented
- Deployed and accessible

---

### TASK P-013 — Implement Structured Logging

**Description:**
Implement structured JSON logging for all operations.

**Reasoning:**
Structured logs enable machine parsing, filtering, and monitoring.

**Implementation Steps:**
1. Configure `structlog` or standard logging with JSON formatter
2. Log fields: timestamp, level, module, operation, duration, details
3. Log all significant operations: build, delta, analyze, apply
4. Log all errors with context
5. Control via `--log-level` and `--log-format` flags

**Files:**
- `codegraph/logging.py`

**Dependencies:** A-006

**Validation:**
- JSON log output parseable
- All operations logged
- Levels controlled correctly

---

### TASK P-014 — Implement Operation Metrics Collection

**Description:**
Collect and report metrics on codegraph operations.

**Reasoning:**
Metrics help identify performance issues and usage patterns.

**Implementation Steps:**
1. Collect metrics:
   - Build time, delta time, analyze time
   - Node count, edge count, task count
   - Index size
   - File count processed
2. Store in `.codegraph/metrics.json`
3. Display in `codegraph status --metrics`

**Files:**
- `codegraph/metrics.py`

**Dependencies:** A-005

**Validation:**
- Metrics collected for all operations
- Stored persistently
- Displayed on request

---

### TASK P-015 — Implement Graph Health Dashboard Data

**Description:**
Generate dashboard-ready data about codebase health.

**Reasoning:**
Teams want to track codebase health over time: policy compliance, test coverage, intent coverage.

**Implementation Steps:**
1. Generate health metrics:
   - Policy compliance rate
   - Test coverage (via edges)
   - Intent coverage %
   - Orphan rate
   - Graph complexity (avg edges per node)
2. Output as JSON for dashboard consumption
3. Historical tracking for trends

**Files:**
- `codegraph/metrics.py` (modify)

**Dependencies:** P-014, I-001

**Validation:**
- All health metrics calculated
- JSON output for dashboards
- Historical data tracked

---

### TASK P-016 — Implement Security Documentation

**Description:**
Document security considerations for codegraph usage.

**Reasoning:**
codegraph modifies source code (apply). Security implications must be documented.

**Implementation Steps:**
1. Create `SECURITY.md`
2. Document:
   - Code modification risks (apply system)
   - Agent trust model
   - Layer safety guards (why agents can't modify layers 0-2)
   - Suggested workflow as security policy tool
   - Dead code removal safeguards (4 signals)
   - Version validation as replay prevention
3. Security contact information

**Files:**
- `SECURITY.md`

**Dependencies:** None

**Validation:**
- All security aspects covered
- Risks documented honestly
- Mitigations explained

---

### TASK P-017 — Implement Contributing Guide

**Description:**
Write contributing guide for open-source contributors.

**Reasoning:**
Contributors need to know how to set up, test, and submit changes.

**Implementation Steps:**
1. Create `CONTRIBUTING.md`
2. Sections:
   - Development setup
   - Running tests
   - Code style (ruff, black, mypy)
   - PR process
   - Architecture overview (which module does what)
   - Adding a new query function
   - Adding a new repair action
   - Adding a new failure mode

**Files:**
- `CONTRIBUTING.md`

**Dependencies:** O-001

**Validation:**
- Guide is followable
- Dev setup works
- PR process clear

---

### TASK P-018 — Implement LICENSE File

**Description:**
Add project license.

**Reasoning:**
Required for open-source distribution.

**Implementation Steps:**
1. Create `LICENSE` file with chosen license (MIT, Apache 2.0, etc.)
2. Add license field to pyproject.toml
3. Add license header to all source files (optional)

**Files:**
- `LICENSE`
- `pyproject.toml` (modify)

**Dependencies:** P-001

**Validation:**
- License file present
- pyproject.toml matches
- License is valid

---

### TASK P-019 — Implement Docker Support

**Description:**
Create Dockerfile for running codegraph in containers.

**Reasoning:**
CI/CD and team environments benefit from containerized tooling.

**Implementation Steps:**
1. Create `Dockerfile`
2. Base: python:3.11-slim
3. Install codegraph and dependencies
4. Entry point: codegraph CLI
5. Document volume mounts for project source and .codegraph/

**Files:**
- `Dockerfile`
- `docs/docker.md`

**Dependencies:** P-001

**Validation:**
- Docker build succeeds
- Container runs codegraph commands
- Volume mounts work

---

### TASK P-020 — Implement README Rewrite

**Description:**
Rewrite the README as a user-facing introduction (separate from the engineering spec).

**Reasoning:**
The current README is a detailed engineering specification. Users need a concise, inviting README.

**Implementation Steps:**
1. Restructure `README.md`:
   - Brief description (1 paragraph)
   - Key features (bullet list)
   - Quick start (5 commands)
   - Architecture diagram (ASCII or Mermaid)
   - Link to full documentation
   - Installation instructions
   - Contributing link
2. Move engineering spec to `docs/engineering-spec.md`

**Files:**
- `README.md` (rewrite)
- `docs/engineering-spec.md` (new, current README content)

**Dependencies:** P-005

**Validation:**
- README is concise and inviting
- Key info accessible in < 30 seconds
- Links to docs work

---

### TASK P-021 — Implement SQLite/DuckDB Migration Research

**Description:**
Research and prototype storage backend migration for large repos (>500 files).

**Reasoning:**
README notes: "For repositories exceeding ~500 files, a future version may adopt SQLite or DuckDB as the storage backend."

**Implementation Steps:**
1. Benchmark JSON vs SQLite vs DuckDB for:
   - Graph storage (nodes, edges)
   - Query performance
   - Delta update speed
   - Disk usage
2. Prototype SQLite backend for Graph_0 storage
3. Write migration plan document
4. Document recommendations

**Files:**
- `docs/adr/001-storage-backend.md`
- `benchmarks/storage_benchmark.py`

**Dependencies:** A-020

**Validation:**
- Benchmarks complete
- Recommendations documented
- Prototype functional

---

### TASK P-022 — Implement Architecture Decision Records

**Description:**
Create ADR (Architecture Decision Record) files for key design decisions.

**Reasoning:**
Future developers need to understand WHY decisions were made, not just what.

**Implementation Steps:**
1. Create `docs/adr/` directory
2. ADR template
3. Initial ADRs:
   - ADR-001: Storage backend (JSON files)
   - ADR-002: Node ID format (file::class::function)
   - ADR-003: Body hash algorithm
   - ADR-004: Layer system design
   - ADR-005: Edge confidence levels
   - ADR-006: Coverage.py over sys.settrace

**Files:**
- `docs/adr/` (multiple files)

**Dependencies:** None

**Validation:**
- ADRs follow standard template
- All key decisions documented
- Context and consequences included

---

### TASK P-023 — Implement Plugin Architecture Documentation

**Description:**
Document the plugin architecture stub for future extensibility.

**Reasoning:**
README mentions planned plugin support (graph exporters, custom analyzers).

**Implementation Steps:**
1. Create `docs/plugins.md`
2. Document:
   - Plugin types: exporters, analyzers, filters, formatters
   - Plugin interface contracts
   - Registration mechanism
   - Example plugin
3. Create example plugin in `examples/plugins/`

**Files:**
- `docs/plugins.md`
- `examples/plugins/example_exporter.py`

**Dependencies:** A-023

**Validation:**
- Plugin interface documented
- Example plugin works
- Registration documented

---

### TASK P-024 — Implement Error Code Registry

**Description:**
Define and document all error codes used by codegraph.

**Reasoning:**
Consistent error codes help automated tools and agents handle errors programmatically.

**Implementation Steps:**
1. Create `codegraph/error_codes.py`
2. Define enum of all error codes: CG-001 through CG-XXX
3. Map each failure mode to an error code
4. Include in error output: `[CG-012] Version mismatch: expected 42, got 41`
5. Document in `docs/error-codes.md`

**Files:**
- `codegraph/error_codes.py`
- `docs/error-codes.md`

**Dependencies:** A-007

**Validation:**
- All errors have codes
- Codes documented
- Codes appear in CLI output

---

### TASK P-025 — Implement Project Completion Checklist

**Description:**
Create a comprehensive checklist verifying all README features are implemented.

**Reasoning:**
Final verification that the engineering spec is fully realized.

**Implementation Steps:**
1. Create `docs/completion-checklist.md`
2. Checklist:
   - All 6 data structures implemented
   - All 15+ Python modules implemented
   - All 17+ CLI commands implemented
   - All 17+ failure modes handled
   - All 50+ test scenarios covered
   - All JSON schemas defined
   - All query functions implemented
   - All repair actions implemented
   - Documentation complete
   - CI/CD configured
3. Status: ✅ / ❌ for each item

**Files:**
- `docs/completion-checklist.md`

**Dependencies:** All other groups

**Validation:**
- All items checked
- No false positives (manually verified)
