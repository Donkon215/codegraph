"""codegraph.architecture_graph — Canonical architecture model.

Provides a unified in-memory representation for architecture state while
remaining compatible with existing graph artifacts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from codegraph.constants import GRAPHS_DIR
from codegraph.models.graph0 import Graph0
from codegraph.models.graph1 import Graph1
from codegraph.models.workflow import Workflow
from codegraph.storage import resolve_path


@dataclass
class ArchitectureGraph:
    """Canonical architecture state.

    `structure_graph` maps to Graph_0, `intent_graph` maps to Graph_1,
    `workflow_graph` maps to workflow.json, and `semantic_graph` carries
    semantic-layer data (Graph_2/derived semantics) as JSON-like data.
    """

    structure_graph: Graph0 = field(default_factory=Graph0)
    intent_graph: Graph1 = field(default_factory=Graph1)
    semantic_graph: Dict[str, Any] = field(default_factory=dict)
    workflow_graph: Workflow = field(default_factory=Workflow)

    @classmethod
    def from_views(
        cls,
        *,
        structure_graph: Optional[Graph0] = None,
        intent_graph: Optional[Graph1] = None,
        semantic_graph: Optional[Dict[str, Any]] = None,
        workflow_graph: Optional[Workflow] = None,
    ) -> "ArchitectureGraph":
        return cls(
            structure_graph=structure_graph or Graph0(),
            intent_graph=intent_graph or Graph1(),
            semantic_graph=semantic_graph or {},
            workflow_graph=workflow_graph or Workflow(),
        )

    @classmethod
    def load(cls, project_root: Path) -> "ArchitectureGraph":
        from codegraph.annotator import load_graph1
        from codegraph.extractor import load_graph0
        from codegraph.workflow import load_workflow

        graph0 = load_graph0(project_root)
        graph1 = load_graph1(project_root)
        workflow = load_workflow(project_root)

        graph2_path = resolve_path(project_root, GRAPHS_DIR, "graph2.json")
        semantics: Dict[str, Any] = {}
        if graph2_path.exists():
            try:
                semantics = json.loads(graph2_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                semantics = {}

        return cls.from_views(
            structure_graph=graph0,
            intent_graph=graph1,
            semantic_graph=semantics,
            workflow_graph=workflow,
        )

    def to_views(self) -> Dict[str, Any]:
        return {
            "graph0": self.structure_graph,
            "graph1": self.intent_graph,
            "graph2": self.semantic_graph,
            "workflow": self.workflow_graph,
        }

    def save_derived_views(self, project_root: Path) -> None:
        from codegraph.annotator import save_graph1
        from codegraph.extractor import save_graph0
        from codegraph.storage import atomic_write
        from codegraph.workflow import write_workflow

        save_graph0(self.structure_graph, project_root)
        save_graph1(self.intent_graph, project_root)
        write_workflow(self.workflow_graph, project_root)

        graph2_path = resolve_path(project_root, GRAPHS_DIR, "graph2.json")
        atomic_write(graph2_path, self.semantic_graph or {})
