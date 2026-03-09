"""codegraph.models.status — StatusReport data model.

Task B-013.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from codegraph.utils.formatting import format_json


@dataclass
class StatusReport:
    """Output of ``codegraph status``."""

    nodes: int = 0
    edges: int = 0
    nodes_missing_intent: int = 0
    orphan_nodes: int = 0
    workflow_edges: int = 0
    suggested_workflow_edges: int = 0
    policy_violations: int = 0
    stale_intents: int = 0
    graph_version: int = 0
    cycle: int = 0

    def to_text(self) -> str:
        """Aligned key-value format matching the README specification."""
        lines = [
            f"nodes:                    {self.nodes}",
            f"edges:                    {self.edges}",
            f"nodes_missing_intent:     {self.nodes_missing_intent}",
            f"orphan_nodes:             {self.orphan_nodes}",
            f"workflow_edges:           {self.workflow_edges}",
            f"suggested_workflow_edges: {self.suggested_workflow_edges}",
            f"policy_violations:        {self.policy_violations}",
            f"stale_intents:            {self.stale_intents}",
            f"graph_version:            {self.graph_version}",
            f"cycle:                    {self.cycle}",
        ]
        return "\n".join(lines)

    def to_json(self) -> str:
        return format_json(self._to_dict())

    def _to_dict(self) -> Dict[str, Any]:
        return {
            "nodes": self.nodes,
            "edges": self.edges,
            "nodes_missing_intent": self.nodes_missing_intent,
            "orphan_nodes": self.orphan_nodes,
            "workflow_edges": self.workflow_edges,
            "suggested_workflow_edges": self.suggested_workflow_edges,
            "policy_violations": self.policy_violations,
            "stale_intents": self.stale_intents,
            "graph_version": self.graph_version,
            "cycle": self.cycle,
        }
