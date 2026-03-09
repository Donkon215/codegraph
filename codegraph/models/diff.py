"""codegraph.models.diff — DiffResult data model.

Task B-015.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from codegraph.utils.formatting import format_json


@dataclass
class DiffResult:
    """Output of ``codegraph diff``."""

    new_nodes: int = 0
    removed_nodes: int = 0
    changed_signatures: int = 0
    new_workflow_edges: int = 0
    removed_workflow_edges: int = 0
    stale_intents: int = 0
    new_node_ids: List[str] = field(default_factory=list)
    removed_node_ids: List[str] = field(default_factory=list)

    def to_text(self) -> str:
        lines = [
            f"new_nodes:              {self.new_nodes}",
            f"removed_nodes:          {self.removed_nodes}",
            f"changed_signatures:     {self.changed_signatures}",
            f"new_workflow_edges:     {self.new_workflow_edges}",
            f"removed_workflow_edges: {self.removed_workflow_edges}",
            f"stale_intents:          {self.stale_intents}",
        ]
        if self.new_node_ids:
            lines.append(f"\nNew nodes:")
            for nid in self.new_node_ids:
                lines.append(f"  + {nid}")
        if self.removed_node_ids:
            lines.append(f"\nRemoved nodes:")
            for nid in self.removed_node_ids:
                lines.append(f"  - {nid}")
        return "\n".join(lines)

    def to_json(self) -> str:
        return format_json(self._to_dict())

    def _to_dict(self) -> Dict[str, Any]:
        return {
            "new_nodes": self.new_nodes,
            "removed_nodes": self.removed_nodes,
            "changed_signatures": self.changed_signatures,
            "new_workflow_edges": self.new_workflow_edges,
            "removed_workflow_edges": self.removed_workflow_edges,
            "stale_intents": self.stale_intents,
            "new_node_ids": self.new_node_ids,
            "removed_node_ids": self.removed_node_ids,
        }
