"""codegraph.constants — Centralised magic strings, defaults, and system constants.

(Task A-023)
"""

from __future__ import annotations

# ── Directory / file names ─────────────────────────────────────────────

CODEGRAPH_DIR = ".codegraph"
GRAPHS_DIR = "graphs"
WORKFLOW_DIR = "workflow"
INDEX_DIR = "index"
TASKS_DIR = "tasks"
RESPONSES_DIR = "responses"
TEST_ARCHI_DIR = "test_archi"

GRAPH0_FILE = "graph0.json"
GRAPH1_FILE = "graph1.json"
GRAPH2_FILE = "graph2.json"
WORKFLOW_FILE = "workflow.json"
SUGGESTED_WORKFLOW_FILE = "suggested_workflow.json"
DELTA_FILE = "delta.json"
CONFIG_FILE = "config.yaml"
CYCLE_FILE = "cycle.json"
INDEX_DB_FILE = "index.db"
TASKS_FILE = "tasks.json"

# ── Default filter lists ───────────────────────────────────────────────

DEFAULT_EDGE_FILTERS: list[str] = [
    "builtins.*",
    "typing.*",
    "abc.*",
    "collections.abc.*",
    "logging.Logger.*",
    "pathlib.Path.*",
    "os.path.*",
]

DEFAULT_DUNDER_EXCLUDE: list[str] = [
    "__repr__",
    "__str__",
    "__len__",
    "__hash__",
    "__eq__",
    "__ne__",
    "__lt__",
    "__le__",
    "__gt__",
    "__ge__",
    "__bool__",
    "__contains__",
    "__iter__",
    "__next__",
    "__getitem__",
    "__setitem__",
    "__delitem__",
]

# ── Layer numbers ──────────────────────────────────────────────────────

LAYER_STDLIB = 0
LAYER_EXTERNAL = 1
LAYER_INTERNAL_LIB = 2
LAYER_PROJECT = 3
LAYER_TEST = 4

# ── Convergence ────────────────────────────────────────────────────────

MAX_ITERATIONS = 10
CONVERGENCE_THRESHOLD = 0.05  # 5 %

# ── Task priorities (lower = higher priority) ──────────────────────────

PRIORITY_POLICY_VIOLATION = 1
PRIORITY_MISSING_IMPORT = 2
PRIORITY_ORPHAN_NODE = 3
PRIORITY_STALE_INTENT = 4
PRIORITY_COVERAGE_GAP = 5
PRIORITY_INFO = 10

# ── Hash defaults ──────────────────────────────────────────────────────

BODY_HASH_LENGTH = 5  # hex chars
FILE_HASH_LENGTH = 12  # hex chars
DEPENDENCY_HASH_LENGTH = 12  # hex chars

# ── Format versioning ─────────────────────────────────────────────────

CURRENT_FORMAT_VERSION = 1

# ── Project-root marker files ──────────────────────────────────────────

PROJECT_ROOT_MARKERS: list[str] = [
    CODEGRAPH_DIR,
    ".git",
    "pyproject.toml",
]
