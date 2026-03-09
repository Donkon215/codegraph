"""codegraph.filters — Edge and node filtering utilities.

Covers tasks F-002 through F-008:
  F-002  Dunder methods filter
  F-003  Logging/print filter
  F-004  Stdlib utilities filter
  F-005  Dataclass auto-methods filter
  F-006  Test harness internals filter
  F-007  Configurable filter pipeline
  F-008  Runtime trace layer filter
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from codegraph.logging_config import get_logger

logger = get_logger("filters")


# ═══════════════════════════════════════════════════════════════════════
# Base filter interface
# ═══════════════════════════════════════════════════════════════════════


class EdgeFilter(ABC):
    """Abstract base for workflow edge filters."""

    name: str = "base"

    @abstractmethod
    def should_filter(self, source: str, target: str, edge: Any) -> bool:
        """Return True if the edge should be removed."""

    def apply(self, edges: list) -> list:
        """Filter a list of WorkflowEdge objects, returning kept edges."""
        kept = [e for e in edges if not self.should_filter(e.source, e.target, e)]
        removed = len(edges) - len(kept)
        if removed:
            logger.debug("Filter '%s' removed %d edges", self.name, removed)
        return kept


# ═══════════════════════════════════════════════════════════════════════
# F-002 — Dunder methods filter
# ═══════════════════════════════════════════════════════════════════════

DEFAULT_DUNDER_FILTER = frozenset({
    "__init__", "__repr__", "__str__", "__eq__",
    "__ne__", "__lt__", "__le__", "__gt__", "__ge__",
    "__hash__", "__bool__", "__len__", "__contains__",
    "__iter__", "__next__", "__getitem__", "__setitem__",
    "__delitem__",
})

# __call__ explicitly kept — it has semantic meaning
DUNDER_KEEP = frozenset({"__call__", "__enter__", "__exit__"})


class DunderFilter(EdgeFilter):
    """Filter edges involving dunder methods (F-002)."""

    name = "dunder"

    def __init__(self, exclude: Optional[Set[str]] = None) -> None:
        self._exclude = exclude or DEFAULT_DUNDER_FILTER

    def should_filter(self, source: str, target: str, edge: Any) -> bool:
        for node_id in (source, target):
            parts = node_id.rsplit("::", 1)
            if len(parts) == 2:
                fname = parts[1]
                if fname.startswith("__") and fname.endswith("__") and fname in self._exclude:
                    return True
        return False


# ═══════════════════════════════════════════════════════════════════════
# F-003 — Logging and print filter
# ═══════════════════════════════════════════════════════════════════════


class LoggingFilter(EdgeFilter):
    """Filter edges to logging and print functions (F-003)."""

    name = "logging"

    def __init__(self, extra_patterns: Optional[List[str]] = None) -> None:
        patterns = [r"(^|::)(logging\.|logger\.|print$|pprint$|pprint\.)"]
        if extra_patterns:
            for p in extra_patterns:
                patterns.append(re.escape(p))
        self._re = re.compile("|".join(patterns), re.IGNORECASE)

    def should_filter(self, source: str, target: str, edge: Any) -> bool:
        return bool(self._re.search(target))


# ═══════════════════════════════════════════════════════════════════════
# F-004 — Stdlib utilities filter
# ═══════════════════════════════════════════════════════════════════════

_STDLIB_PREFIXES = (
    "os.path.", "os.", "sys.", "pathlib.", "shutil.",
    "subprocess.", "tempfile.", "glob.", "fnmatch.",
    "re.", "json.", "csv.", "io.", "collections.",
    "itertools.", "functools.", "operator.",
    "builtins.", "typing.", "abc.", "collections.abc.",
)


class StdlibFilter(EdgeFilter):
    """Filter edges targeting stdlib utility functions (F-004)."""

    name = "stdlib"

    def __init__(
        self,
        prefixes: Optional[tuple[str, ...]] = None,
        layer_map: Optional[Dict[str, int]] = None,
    ) -> None:
        self._prefixes = prefixes or _STDLIB_PREFIXES
        self._layer_map = layer_map or {}

    def should_filter(self, source: str, target: str, edge: Any) -> bool:
        # Layer-based filtering — if we know the target is layer 0
        if self._layer_map.get(target, -1) == 0:
            return True
        # Pattern-based fallback
        for prefix in self._prefixes:
            if target.startswith(prefix) or f"::{prefix}" in target:
                return True
        return False


# ═══════════════════════════════════════════════════════════════════════
# F-005 — Dataclass auto-methods filter
# ═══════════════════════════════════════════════════════════════════════

_DATACLASS_AUTO_METHODS = frozenset({
    "__init__", "__repr__", "__eq__", "__hash__",
    "__lt__", "__le__", "__gt__", "__ge__",
    "__post_init__",
})


class DataclassFilter(EdgeFilter):
    """Filter edges involving dataclass auto-generated methods (F-005)."""

    name = "dataclass"

    def __init__(self, dataclass_nodes: Optional[Set[str]] = None) -> None:
        self._dc_nodes = dataclass_nodes or set()

    def should_filter(self, source: str, target: str, edge: Any) -> bool:
        for node_id in (source, target):
            parts = node_id.rsplit("::", 1)
            if len(parts) == 2:
                method = parts[1]
                class_prefix = parts[0]
                if method in _DATACLASS_AUTO_METHODS and class_prefix in self._dc_nodes:
                    return True
        return False


# ═══════════════════════════════════════════════════════════════════════
# F-006 — Test harness internals filter
# ═══════════════════════════════════════════════════════════════════════

_TEST_HARNESS_PATTERNS = re.compile(
    r"(conftest|fixture|setup_module|teardown_module|"
    r"setup_function|teardown_function|setup_method|teardown_method|"
    r"setup_class|teardown_class|pytest_|_pytest)",
    re.IGNORECASE,
)


class TestHarnessFilter(EdgeFilter):
    """Filter edges to test harness internals (F-006)."""

    name = "test_harness"

    def should_filter(self, source: str, target: str, edge: Any) -> bool:
        for node_id in (source, target):
            parts = node_id.rsplit("::", 1)
            if len(parts) < 2:
                continue
            name = parts[-1]
            # Keep test_* functions
            if name.startswith("test_"):
                continue
            if _TEST_HARNESS_PATTERNS.search(name):
                return True
        return False


# ═══════════════════════════════════════════════════════════════════════
# F-008 — Runtime trace layer filter
# ═══════════════════════════════════════════════════════════════════════


class RuntimeTraceLayerFilter(EdgeFilter):
    """Mandatory filter for trace mode: keep only layer 3/4 edges (F-008).

    Not user-configurable — always applied to trace edges.
    """

    name = "trace_layer"

    def __init__(self, layer_map: Dict[str, int]) -> None:
        self._layer_map = layer_map

    def should_filter(self, source: str, target: str, edge: Any) -> bool:
        src_layer = self._layer_map.get(source, 3)
        tgt_layer = self._layer_map.get(target, 3)
        return src_layer < 3 or tgt_layer < 3


# ═══════════════════════════════════════════════════════════════════════
# F-007 — Configurable filter pipeline
# ═══════════════════════════════════════════════════════════════════════

_FILTER_REGISTRY: Dict[str, type] = {
    "dunder": DunderFilter,
    "logging": LoggingFilter,
    "stdlib": StdlibFilter,
    "dataclass": DataclassFilter,
    "test_harness": TestHarnessFilter,
}


@dataclass
class FilterResult:
    """Summary of filter pipeline application."""

    input_count: int = 0
    output_count: int = 0
    per_filter: Dict[str, int] = field(default_factory=dict)


class FilterPipeline:
    """Chain of edge filters, applied sequentially (F-007)."""

    def __init__(self, filters: Optional[List[EdgeFilter]] = None) -> None:
        self._filters: List[EdgeFilter] = filters or []

    @classmethod
    def from_config(
        cls,
        filter_names: List[str],
        *,
        layer_map: Optional[Dict[str, int]] = None,
        dataclass_nodes: Optional[Set[str]] = None,
        dunder_exclude: Optional[Set[str]] = None,
    ) -> "FilterPipeline":
        """Build a pipeline from config filter names."""
        filters: List[EdgeFilter] = []
        for name in filter_names:
            name_lower = name.lower()
            if name_lower == "dunder":
                filters.append(DunderFilter(exclude=dunder_exclude))
            elif name_lower == "logging":
                filters.append(LoggingFilter())
            elif name_lower == "stdlib":
                filters.append(StdlibFilter(layer_map=layer_map))
            elif name_lower == "dataclass":
                filters.append(DataclassFilter(dataclass_nodes=dataclass_nodes))
            elif name_lower == "test_harness":
                filters.append(TestHarnessFilter())
            else:
                logger.warning("Unknown filter: '%s', skipping", name)
        return cls(filters)

    def add(self, f: EdgeFilter) -> None:
        self._filters.append(f)

    def apply(self, edges: list) -> tuple[list, FilterResult]:
        """Apply all filters in sequence, returning (kept_edges, result)."""
        result = FilterResult(input_count=len(edges))
        current = edges
        for f in self._filters:
            before = len(current)
            current = f.apply(current)
            removed = before - len(current)
            result.per_filter[f.name] = removed
        result.output_count = len(current)
        return current, result

    @property
    def filter_names(self) -> List[str]:
        return [f.name for f in self._filters]

    @staticmethod
    def available_filters() -> List[str]:
        """Return names of all built-in filters."""
        return sorted(_FILTER_REGISTRY.keys())
