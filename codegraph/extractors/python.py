"""codegraph.extractors.python — Python-specific AST extractor.

Delegates to :mod:`codegraph.extractor` for the heavy lifting.
(Task A-027, wired up in Group C)
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from codegraph.extraction_types import FileExtractionResult
from codegraph.extractor import extract_file
from codegraph.models.graph0 import Graph0Node


class PythonExtractor:
    """Extract Graph_0 nodes and Workflow edges from Python source files."""

    def __init__(self, project_root: Path) -> None:
        self._root = project_root

    def supported_extensions(self) -> List[str]:
        return [".py"]

    def extract_nodes(self, file_path: Path) -> List[Graph0Node]:
        """Extract all function/class/method nodes from a Python file."""
        result = extract_file(file_path, self._root)
        return result.nodes

    def extract_all(self, file_path: Path) -> FileExtractionResult:
        """Extract nodes, imports, call sites, etc."""
        return extract_file(file_path, self._root)

    def extract_edges(self, file_path: Path, nodes: List[Graph0Node]) -> list:
        """Extract call-graph edges from a Python file.

        Full implementation in Group F tasks.
        """
        # Stub — implemented by F-001 through F-036
        return []
