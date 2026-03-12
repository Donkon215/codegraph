"""codegraph.extraction_types — Shared extraction data types.

Shared between codegraph.extractor and codegraph.extractors.javascript
to break the import cycle (C-016, C-008).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ImportInfo:
    """A single import statement extracted from a source file.  (C-016)"""

    module: str
    names: List[str] = field(default_factory=list)
    alias: Optional[str] = None
    is_relative: bool = False
    level: int = 0
    line: int = 0

    def resolved_name(self, current_package: str = "") -> str:
        """Return the fully-qualified module name, resolving relative imports."""
        if not self.is_relative or not current_package:
            return self.module
        parts = current_package.split(".")
        up = self.level - 1
        if up < len(parts):
            base = ".".join(parts[: len(parts) - up])
        else:
            base = ""
        if self.module:
            return f"{base}.{self.module}" if base else self.module
        return base


@dataclass
class FileExtractionResult:
    """All data extracted from a single file."""

    nodes: List[Any] = field(default_factory=list)
    imports: List[ImportInfo] = field(default_factory=list)
    globals: List[Any] = field(default_factory=list)
    class_infos: List[Any] = field(default_factory=list)
    call_sites: Dict[str, List[Any]] = field(default_factory=dict)
    dynamic_calls: List[Any] = field(default_factory=list)
    warnings: List[Any] = field(default_factory=list)
