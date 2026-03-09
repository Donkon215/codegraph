"""codegraph.extractors — Plugin registry for language-specific extractors.

(Task A-027)
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Type

from codegraph.logging_config import get_logger
from codegraph.types import Graph0Node, LanguageExtractor, WorkflowEdge

logger = get_logger("extractors")

# Global registry mapping file extensions → extractor classes.
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
