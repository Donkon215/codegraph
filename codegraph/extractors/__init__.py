"""codegraph.extractors — Plugin registry for language-specific extractors.

(Task A-027)
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Type

from codegraph.logging_config import get_logger
from codegraph.types import Graph0Node, LanguageExtractor, WorkflowEdge

logger = get_logger("extractors")

# Global registry mapping file extensions → extractor instances.
_registry: Dict[str, "LanguageExtractor"] = {}


def register_extractor(extractor: "LanguageExtractor") -> None:
    """Register a :class:`LanguageExtractor` for its declared extensions."""
    for ext in extractor.supported_extensions():
        _registry[ext] = extractor
        logger.debug("Registered extractor for '%s': %s", ext, type(extractor).__name__)


def get_extractor(file_path: Path) -> Optional["LanguageExtractor"]:
    """Return the extractor that handles *file_path*'s extension, or ``None``."""
    return _registry.get(file_path.suffix)


def supported_extensions() -> List[str]:
    """Return all extensions that have a registered extractor."""
    return sorted(_registry.keys())


def setup(project_root: Path) -> None:
    """Register all built-in language extractors for *project_root*.

    Call this once at build time to make :func:`get_extractor` return the
    correct extractor for every supported file extension:

    - ``.py``                       → :class:`~codegraph.extractors.python.PythonExtractor`
    - ``.js / .jsx / .ts / .tsx``   → :class:`~codegraph.extractors.javascript.JavaScriptExtractor`
    - ``.mjs / .cjs``               → :class:`~codegraph.extractors.javascript.JavaScriptExtractor`
    """
    from codegraph.extractors.javascript import JavaScriptExtractor
    from codegraph.extractors.python import PythonExtractor

    register_extractor(PythonExtractor(project_root))
    register_extractor(JavaScriptExtractor(project_root))
