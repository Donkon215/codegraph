"""codegraph.services — Service facades for high fan-in hotspots.

These facades keep call-sites stable while reducing direct coupling to
implementation modules.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from codegraph.architecture_graph import ArchitectureGraph
from codegraph.config import find_project_root
from codegraph.models.graph0 import Graph0
from codegraph.models.graph1 import Graph1
from codegraph.models.workflow import Workflow


class ConfigService:
    """Facade for configuration and project-root resolution."""

    def find_project_root(self, start_path: Optional[Path] = None) -> Path:
        return find_project_root(start_path)


class GraphStore:
    """Facade for graph artifact load/save operations."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root

    def load_graph0(self) -> Graph0:
        from codegraph.extractor import load_graph0

        return load_graph0(self.project_root)

    def save_graph0(self, graph0: Graph0) -> None:
        from codegraph.extractor import save_graph0

        save_graph0(graph0, self.project_root)

    def load_graph1(self) -> Graph1:
        from codegraph.annotator import load_graph1

        return load_graph1(self.project_root)

    def save_graph1(self, graph1: Graph1) -> None:
        from codegraph.annotator import save_graph1

        save_graph1(graph1, self.project_root)

    def load_workflow(self) -> Workflow:
        from codegraph.workflow import load_workflow

        return load_workflow(self.project_root)

    def load_architecture_graph(self) -> ArchitectureGraph:
        return ArchitectureGraph.load(self.project_root)


class IndexService:
    """Facade around IndexStore with lazy initialization."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self._store = None

    def _get_store(self):
        if self._store is None:
            from codegraph.index import IndexStore

            self._store = IndexStore(self.project_root)
        return self._store

    def close(self) -> None:
        if self._store is not None:
            self._store.close()
            self._store = None

    def get_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        return self._get_store().get_node(node_id)

    def get_callers(self, node_id: str) -> List[str]:
        return self._get_store().get_callers(node_id)

    def get_callees(self, node_id: str) -> List[str]:
        return self._get_store().get_callees(node_id)

    def _get_conn(self):
        return self._get_store()._get_conn()
