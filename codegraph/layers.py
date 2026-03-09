"""codegraph.layers — Layer detection, classification, and safety enforcement.

Tasks D-001 through D-020.
"""

from __future__ import annotations

import enum
import site
import sys
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence

from codegraph.constants import (
    LAYER_EXTERNAL,
    LAYER_INTERNAL_LIB,
    LAYER_PROJECT,
    LAYER_STDLIB,
    LAYER_TEST,
)
from codegraph.logging_config import get_logger

if TYPE_CHECKING:
    from codegraph.config import CodegraphConfig
    from codegraph.models.graph0 import Graph0, Graph0Node
    from codegraph.models.graph1 import Graph1, Graph1Node
    from codegraph.models.suggested_workflow import SuggestedWorkflow, SuggestedWorkflowRule
    from codegraph.models.tasks import PolicyViolation
    from codegraph.models.workflow import Workflow

logger = get_logger("layers")


# ── D-001  Layer Enum and Constants ────────────────────────────────────


class Layer(enum.IntEnum):
    """Canonical layer numbering (0–4)."""

    STDLIB = LAYER_STDLIB          # 0
    EXTERNAL = LAYER_EXTERNAL      # 1
    INTERNAL_LIB = LAYER_INTERNAL_LIB  # 2
    PROJECT = LAYER_PROJECT        # 3
    TEST = LAYER_TEST              # 4

    def is_modifiable(self) -> bool:
        """Only project (3) and test (4) code may be modified by agents."""
        return self.value in (LAYER_PROJECT, LAYER_TEST)

    def description(self) -> str:
        """Human-readable label."""
        return _LAYER_DESCRIPTIONS[self]


_LAYER_DESCRIPTIONS: dict[Layer, str] = {
    Layer.STDLIB: "Python standard library",
    Layer.EXTERNAL: "Third-party dependency (pip-installed)",
    Layer.INTERNAL_LIB: "Internal shared library (configured)",
    Layer.PROJECT: "Project source code",
    Layer.TEST: "Test code",
}


# ── D-016  Virtual Environment Detection ───────────────────────────────


def _get_site_packages_dirs() -> list[str]:
    """Return normalised site-packages directories for the active environment."""
    dirs: list[str] = []
    for d in site.getsitepackages():
        dirs.append(str(Path(d).resolve()))
    user_site = site.getusersitepackages()
    if isinstance(user_site, str):
        dirs.append(str(Path(user_site).resolve()))
    return dirs


def is_in_virtualenv() -> bool:
    """Return *True* when running inside a virtual environment."""
    return sys.prefix != sys.base_prefix


def get_site_packages_path() -> str:
    """Return the primary site-packages directory for the current environment."""
    packages = _get_site_packages_dirs()
    return packages[0] if packages else ""


# ── D-002  Stdlib Detection ────────────────────────────────────────────

# Python 3.10+ has sys.stdlib_module_names
_STDLIB_NAMES: frozenset[str] = getattr(sys, "stdlib_module_names", frozenset())


def is_stdlib(module_name: str) -> bool:
    """Return *True* when *module_name* belongs to the Python standard library."""
    top_level = module_name.split(".")[0]
    return top_level in _STDLIB_NAMES


# ── D-003  External Dependency Detection ───────────────────────────────

_SITE_PACKAGES_DIRS: list[str] | None = None


def _cached_site_packages() -> list[str]:
    global _SITE_PACKAGES_DIRS
    if _SITE_PACKAGES_DIRS is None:
        _SITE_PACKAGES_DIRS = _get_site_packages_dirs()
    return _SITE_PACKAGES_DIRS


def is_external(file_path: str) -> bool:
    """Return *True* when *file_path* resides inside site-packages (layer 1)."""
    norm = str(Path(file_path).resolve())
    # Fast heuristic: check for site-packages in path
    if "site-packages" in norm:
        return True
    # Full check against known directories
    for sp in _cached_site_packages():
        if norm.startswith(sp):
            return True
    return False


# ── D-019  Editable Install Detection ──────────────────────────────────

_EDITABLE_PATHS: list[str] | None = None


def _discover_editable_install_paths() -> list[str]:
    """Find directories installed in editable mode (pip install -e)."""
    paths: list[str] = []
    for sp_dir in _cached_site_packages():
        sp = Path(sp_dir)
        if not sp.is_dir():
            continue
        # Modern: direct_url.json in *.dist-info with editable flag
        for dist_info in sp.glob("*.dist-info"):
            direct_url = dist_info / "direct_url.json"
            if direct_url.exists():
                try:
                    import json
                    data = json.loads(direct_url.read_text(encoding="utf-8"))
                    if data.get("dir_info", {}).get("editable", False):
                        url = data.get("url", "")
                        if url.startswith("file://"):
                            local = url[7:]
                            # Windows: file:///C:/... → C:/...
                            if len(local) > 2 and local[0] == "/" and local[2] == ":":
                                local = local[1:]
                            paths.append(str(Path(local).resolve()))
                except Exception:
                    pass
        # Legacy: .egg-link files
        for egg_link in sp.glob("*.egg-link"):
            try:
                first_line = egg_link.read_text(encoding="utf-8").splitlines()[0].strip()
                if first_line:
                    paths.append(str(Path(first_line).resolve()))
            except Exception:
                pass
    return paths


def _cached_editable_paths() -> list[str]:
    global _EDITABLE_PATHS
    if _EDITABLE_PATHS is None:
        _EDITABLE_PATHS = _discover_editable_install_paths()
    return _EDITABLE_PATHS


def is_editable_install(file_path: str, project_root: str = "") -> bool:
    """Return *True* when *file_path* belongs to an editable-installed package.

    Excludes the project itself (identified by *project_root*) to avoid
    self-classification as external.
    """
    norm = str(Path(file_path).resolve())
    project_resolved = str(Path(project_root).resolve()) if project_root else ""
    for ep in _cached_editable_paths():
        if norm.startswith(ep):
            # Skip self-reference
            if project_resolved and ep.startswith(project_resolved):
                continue
            return True
    return False


# ── D-004  Internal Library Detection ──────────────────────────────────


def is_internal_lib(file_path: str, config: CodegraphConfig) -> bool:
    """Return *True* when *file_path* is under a configured internal_libs directory."""
    if not config.internal_libs:
        return False
    norm = PurePosixPath(Path(file_path).as_posix())
    for lib_dir in config.internal_libs:
        lib_posix = PurePosixPath(Path(lib_dir).as_posix())
        try:
            norm.relative_to(lib_posix)
            return True
        except ValueError:
            continue
    return False


# ── D-005  Test Code Detection ─────────────────────────────────────────

_TEST_FILE_PATTERNS = ("test_", "conftest.py")
_TEST_FILE_SUFFIXES = ("_test.py",)
_TEST_DIR_NAMES = ("tests", "test")


def is_test(file_path: str, config: CodegraphConfig) -> bool:
    """Return *True* when *file_path* is test code (layer 4)."""
    parts = Path(file_path).parts
    name = parts[-1] if parts else ""

    # Filename patterns
    if name.startswith("test_") or name == "conftest.py":
        return True
    if name.endswith("_test.py"):
        return True

    # Standard test directories
    lower_parts = [p.lower() for p in parts]
    for td in _TEST_DIR_NAMES:
        if td in lower_parts:
            return True

    # Config-specified test_dirs
    if config.test_dirs:
        norm = PurePosixPath(Path(file_path).as_posix())
        for td in config.test_dirs:
            td_posix = PurePosixPath(Path(td).as_posix())
            try:
                norm.relative_to(td_posix)
                return True
            except ValueError:
                continue

    return False


# ── D-006  Project Source Detection (unified detect_layer) ─────────────


def detect_layer(
    file_path: str,
    config: CodegraphConfig,
    *,
    project_root: str = "",
) -> int:
    """Determine the layer for *file_path* by applying rules in order.

    Order: stdlib(0) → external(1) → internal_lib(2) → test(4) → project(3).
    """
    # Default project_root to CWD so editable self-installs are excluded
    effective_root = project_root or str(Path.cwd())

    # Layer 1 — external / site-packages
    if is_external(file_path):
        return LAYER_EXTERNAL

    # Layer 1 — editable installs (not self)
    if is_editable_install(file_path, project_root=effective_root):
        return LAYER_EXTERNAL

    # Layer 2 — internal shared libraries (config-driven)
    if is_internal_lib(file_path, config):
        return LAYER_INTERNAL_LIB

    # Layer 4 — test code
    if is_test(file_path, config):
        return LAYER_TEST

    # Layer 3 — project source (default)
    return LAYER_PROJECT


# ── D-013  Runtime Layer Override ──────────────────────────────────────


def parse_layer_overrides(raw: Sequence[str]) -> dict[str, int]:
    """Parse CLI ``--layer-override`` values (``path:layer_number``).

    Returns a mapping of normalised path prefix → layer number.
    Raises *ValueError* on invalid syntax or layer numbers.
    """
    overrides: dict[str, int] = {}
    for item in raw:
        if ":" not in item:
            raise ValueError(
                f"Invalid layer override '{item}'. Expected format: path:layer_number"
            )
        path_str, layer_str = item.rsplit(":", 1)
        try:
            layer_num = int(layer_str)
        except ValueError:
            raise ValueError(
                f"Invalid layer number '{layer_str}' in override '{item}'"
            ) from None
        if layer_num not in range(5):
            raise ValueError(
                f"Layer number must be 0-4, got {layer_num} in override '{item}'"
            )
        norm_path = Path(path_str).as_posix().rstrip("/")
        overrides[norm_path] = layer_num
        logger.info("Layer override: %s → layer %d", norm_path, layer_num)
    return overrides


def apply_layer_overrides(
    layers: dict[str, int],
    overrides: dict[str, int],
) -> dict[str, int]:
    """Apply runtime overrides to an existing layer mapping.

    Any node whose file path starts with an override prefix gets that layer.
    """
    if not overrides:
        return layers
    result = dict(layers)
    for node_id, current_layer in result.items():
        # node_id format is typically "module.path::func"
        # We match on the file path embedded in node ids or pass file-based keys
        for prefix, layer_num in overrides.items():
            if node_id.startswith(prefix) or prefix in node_id:
                if current_layer != layer_num:
                    logger.info(
                        "Override: %s layer %d → %d", node_id, current_layer, layer_num
                    )
                result[node_id] = layer_num
                break
    return result


# ── D-007  Layer Assignment for All Nodes ──────────────────────────────


def assign_layers(
    nodes: Sequence[Graph0Node],
    config: CodegraphConfig,
    *,
    project_root: str = "",
    overrides: dict[str, int] | None = None,
) -> dict[str, int]:
    """Assign a layer to every node based on its file path.

    Returns a mapping of *node_id* → layer number.
    """
    layers: dict[str, int] = {}
    # Cache per-file to avoid redundant detection
    file_cache: dict[str, int] = {}

    for node in nodes:
        fp = node.file
        if fp not in file_cache:
            file_cache[fp] = detect_layer(fp, config, project_root=project_root)
        layers[node.id] = file_cache[fp]

    if overrides:
        layers = apply_layer_overrides(layers, overrides)

    return layers


# ── D-008  Layer Validation ────────────────────────────────────────────


@dataclass
class LayerWarning:
    """A potential layer-assignment issue."""

    node_id: str
    message: str
    detected_layer: int
    assigned_layer: int


def validate_layers(
    graph0: Graph0,
    graph1: Graph1,
    config: CodegraphConfig,
    *,
    project_root: str = "",
) -> list[LayerWarning]:
    """Validate that Graph_1 layer assignments match detection rules."""
    warnings: list[LayerWarning] = []

    for g1_node in graph1.nodes:
        g0_node = graph0.get_node(g1_node.id)
        if g0_node is None:
            continue
        detected = detect_layer(g0_node.file, config, project_root=project_root)
        if detected != g1_node.layer:
            warnings.append(
                LayerWarning(
                    node_id=g1_node.id,
                    message=(
                        f"Assigned layer {g1_node.layer} but detection says {detected} "
                        f"for file '{g0_node.file}'"
                    ),
                    detected_layer=detected,
                    assigned_layer=g1_node.layer,
                )
            )

    # Check configured directories exist
    if project_root:
        root = Path(project_root)
        for lib_dir in config.internal_libs:
            if not (root / lib_dir).is_dir():
                warnings.append(
                    LayerWarning(
                        node_id="<config>",
                        message=f"Configured internal_libs directory does not exist: {lib_dir}",
                        detected_layer=-1,
                        assigned_layer=-1,
                    )
                )
        for td in config.test_dirs:
            if not (root / td).is_dir():
                warnings.append(
                    LayerWarning(
                        node_id="<config>",
                        message=f"Configured test_dirs directory does not exist: {td}",
                        detected_layer=-1,
                        assigned_layer=-1,
                    )
                )

    return warnings


# ── D-009  Layer-Based Node Filtering ──────────────────────────────────


def filter_by_layer(
    nodes: Sequence[Graph1Node],
    layer: int,
) -> list[Graph1Node]:
    """Return nodes at the given *layer*."""
    return [n for n in nodes if n.layer == layer]


def filter_modifiable(nodes: Sequence[Graph1Node]) -> list[Graph1Node]:
    """Return only nodes at layers 3 (project) and 4 (test)."""
    return [n for n in nodes if n.layer in (LAYER_PROJECT, LAYER_TEST)]


def filter_project_source(nodes: Sequence[Graph1Node]) -> list[Graph1Node]:
    """Return only layer 3 (project source) nodes."""
    return [n for n in nodes if n.layer == LAYER_PROJECT]


def filter_test_code(nodes: Sequence[Graph1Node]) -> list[Graph1Node]:
    """Return only layer 4 (test) nodes."""
    return [n for n in nodes if n.layer == LAYER_TEST]


# ── D-010  Layer Safety Guard ──────────────────────────────────────────


def check_modification_safety(node_id: str, graph1: Graph1) -> bool:
    """Return *True* only if *node_id* is at a modifiable layer (3 or 4).

    Raises :class:`~codegraph.exceptions.LayerViolationError` if the node
    exists and is at a non-modifiable layer.
    """
    from codegraph.exceptions import LayerViolationError

    node = graph1.get_node(node_id)
    if node is None:
        # Unknown node — let caller decide
        return True
    layer = Layer(node.layer)
    if layer.is_modifiable():
        return True
    raise LayerViolationError(
        node_id=node_id,
        layer=node.layer,
    )


# ── D-014  Layer Statistics Reporter ───────────────────────────────────


def layer_statistics(graph1: Graph1) -> dict[int, int]:
    """Count nodes per layer, including zeroes for empty layers."""
    stats: dict[int, int] = {lyr.value: 0 for lyr in Layer}
    for node in graph1.nodes:
        stats[node.layer] = stats.get(node.layer, 0) + 1
    return stats


def format_layer_stats(stats: dict[int, int]) -> str:
    """Format layer statistics for CLI output."""
    lines: list[str] = ["Layer distribution:"]
    total = sum(stats.values())
    for lyr in Layer:
        count = stats.get(lyr.value, 0)
        pct = (count / total * 100) if total else 0
        lines.append(f"  {lyr.value} ({lyr.name:12s}): {count:5d}  ({pct:5.1f}%)")
    lines.append(f"  {'':14s}  Total: {total}")
    return "\n".join(lines)


# ── D-015  Layer Change Detection for Delta ────────────────────────────


@dataclass
class LayerChange:
    """Records a node whose layer changed between builds."""

    node_id: str
    old_layer: int
    new_layer: int


def detect_layer_changes(
    old_layers: dict[str, int],
    new_layers: dict[str, int],
) -> list[LayerChange]:
    """Compare two layer mappings and return nodes whose layer changed."""
    changes: list[LayerChange] = []
    for node_id, new_lyr in new_layers.items():
        old_lyr = old_layers.get(node_id)
        if old_lyr is not None and old_lyr != new_lyr:
            changes.append(LayerChange(node_id=node_id, old_layer=old_lyr, new_layer=new_lyr))
            logger.info("Layer change: %s %d → %d", node_id, old_lyr, new_lyr)
    return changes


# ── D-017  Layer Violation Reporting for Suggested Workflow ────────────


def check_layer_constraints(
    workflow: Workflow,
    rules: SuggestedWorkflow,
    layers: dict[str, int],
) -> list[PolicyViolation]:
    """Check layer-scoped suggested workflow rules for violations.

    Expands rules that use *source_layer* / *target_layer* to match
    concrete nodes. Returns a list of :class:`PolicyViolation` items.
    """
    from codegraph.models.suggested_workflow import RuleType
    from codegraph.models.tasks import PolicyViolation as PV

    violations: list[PV] = []

    # Build a set of existing edges for fast lookup
    edge_set: set[tuple[str, str]] = set()
    for edge in workflow.edges:
        edge_set.add((edge.source, edge.target))

    # Nodes grouped by layer
    nodes_by_layer: dict[int, list[str]] = {}
    for nid, lyr in layers.items():
        nodes_by_layer.setdefault(lyr, []).append(nid)

    for rule in rules.rules:
        # Only process layer-scoped rules
        if rule.source_layer is None and rule.target_layer is None:
            continue

        sources: list[str] = []
        targets: list[str] = []

        if rule.source is not None:
            sources = [rule.source]
        elif rule.source_layer is not None:
            sources = nodes_by_layer.get(rule.source_layer, [])

        if rule.target is not None:
            targets = [rule.target]
        elif rule.target_layer is not None:
            targets = nodes_by_layer.get(rule.target_layer, [])

        rule_type = RuleType(rule.type)

        for src in sources:
            for tgt in targets:
                edge_exists = (src, tgt) in edge_set
                if rule_type.is_violation(edge_exists):
                    violations.append(
                        PV(
                            source=src,
                            required_target=tgt,
                            policy_reason=(
                                f"Layer constraint violated (rule {rule.id}): "
                                f"{rule.reason}"
                            ),
                        )
                    )

    return violations


# ── D-020  Layer Migration Safety Check ────────────────────────────────


@dataclass
class MigrationWarning:
    """Warning about a layer change that may invalidate existing rules."""

    node_id: str
    old_layer: int
    new_layer: int
    affected_rule_ids: list[str] = field(default_factory=list)
    message: str = ""


def check_layer_migration_safety(
    changes: list[LayerChange],
    rules: SuggestedWorkflow,
) -> list[MigrationWarning]:
    """Check whether layer changes invalidate suggested-workflow rules.

    For each node that changed layer, find rules that reference either
    the node directly or its old/new layer and flag them.
    """
    warnings: list[MigrationWarning] = []
    changed_ids = {c.node_id for c in changes}

    for change in changes:
        affected: list[str] = []
        for rule in rules.rules:
            # Rule references the node directly
            if rule.source == change.node_id or rule.target == change.node_id:
                affected.append(rule.id)
                continue
            # Rule references the old layer
            if rule.source_layer == change.old_layer or rule.target_layer == change.old_layer:
                affected.append(rule.id)
                continue

        if affected:
            warnings.append(
                MigrationWarning(
                    node_id=change.node_id,
                    old_layer=change.old_layer,
                    new_layer=change.new_layer,
                    affected_rule_ids=affected,
                    message=(
                        f"Node '{change.node_id}' moved from layer {change.old_layer} "
                        f"to {change.new_layer}; rules {affected} may need review"
                    ),
                )
            )
            logger.warning(
                "Migration safety: %s layer %d→%d affects rules %s",
                change.node_id, change.old_layer, change.new_layer, affected,
            )

    return warnings


# ── Module-level cache reset (for testing) ─────────────────────────────


def _reset_caches() -> None:
    """Reset module-level caches (useful in tests)."""
    global _SITE_PACKAGES_DIRS, _EDITABLE_PATHS
    _SITE_PACKAGES_DIRS = None
    _EDITABLE_PATHS = None
