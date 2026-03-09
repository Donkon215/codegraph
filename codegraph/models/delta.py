"""codegraph.models.delta — Delta result data model.

Tasks B-012, B-042.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

from codegraph.utils.formatting import format_json, iso_now


@dataclass
class DeltaResult:
    """Records incremental changes between two graph versions."""

    computed_at: str = ""
    previous_graph_version: int = 0
    current_graph_version: int = 0
    files_changed: List[str] = field(default_factory=list)
    nodes_added: List[str] = field(default_factory=list)
    nodes_removed: List[str] = field(default_factory=list)
    nodes_modified: List[str] = field(default_factory=list)
    workflow_edges_added: List[Tuple[str, str]] = field(default_factory=list)
    workflow_edges_removed: List[Tuple[str, str]] = field(default_factory=list)
    stale_intents: List[str] = field(default_factory=list)

    # B-042 — CAS statistics
    cas_enabled: bool = False
    cas_body_changed_nodes: int = 0
    cas_affected_nodes: int = 0
    cas_propagation_factor: float = 0.0
    cas_nodes_skipped: int = 0
    cas_scc_count: int = 0

    def __post_init__(self) -> None:
        if not self.computed_at:
            self.computed_at = iso_now()

    def is_empty(self) -> bool:
        """True when no changes were detected."""
        return not any([
            self.files_changed,
            self.nodes_added,
            self.nodes_removed,
            self.nodes_modified,
            self.workflow_edges_added,
            self.workflow_edges_removed,
            self.stale_intents,
        ])

    def summary(self) -> str:
        """Human-readable summary string."""
        lines = [
            f"Delta  v{self.previous_graph_version} → v{self.current_graph_version}",
            f"  files changed:          {len(self.files_changed)}",
            f"  nodes added:            {len(self.nodes_added)}",
            f"  nodes removed:          {len(self.nodes_removed)}",
            f"  nodes modified:         {len(self.nodes_modified)}",
            f"  workflow edges added:   {len(self.workflow_edges_added)}",
            f"  workflow edges removed: {len(self.workflow_edges_removed)}",
            f"  stale intents:          {len(self.stale_intents)}",
        ]
        if self.cas_enabled:
            lines += [
                "  ── CAS ──",
                f"  body changed nodes:     {self.cas_body_changed_nodes}",
                f"  affected nodes (total): {self.cas_affected_nodes}",
                f"  propagation factor:     {self.cas_propagation_factor:.2f}x",
                f"  nodes skipped:          {self.cas_nodes_skipped}",
                f"  SCC count:              {self.cas_scc_count}",
            ]
        return "\n".join(lines)

    # ── Serialization ─────────────────────────────────────────────────

    def to_json(self, compact: bool = False) -> str:
        data: Dict[str, Any] = {
            "computed_at": self.computed_at,
            "previous_graph_version": self.previous_graph_version,
            "current_graph_version": self.current_graph_version,
            "files_changed": self.files_changed,
            "nodes_added": self.nodes_added,
            "nodes_removed": self.nodes_removed,
            "nodes_modified": self.nodes_modified,
            "workflow_edges_added": [list(t) for t in self.workflow_edges_added],
            "workflow_edges_removed": [list(t) for t in self.workflow_edges_removed],
            "stale_intents": self.stale_intents,
        }
        if self.cas_enabled:
            data["cas"] = {
                "enabled": True,
                "body_changed_nodes": self.cas_body_changed_nodes,
                "affected_nodes": self.cas_affected_nodes,
                "propagation_factor": self.cas_propagation_factor,
                "nodes_skipped": self.cas_nodes_skipped,
                "scc_count": self.cas_scc_count,
            }
        return format_json(data, compact=compact)

    @classmethod
    def from_json(cls, text: str) -> DeltaResult:
        d = json.loads(text)
        cas = d.get("cas", {})
        return cls(
            computed_at=d.get("computed_at", ""),
            previous_graph_version=d.get("previous_graph_version", 0),
            current_graph_version=d.get("current_graph_version", 0),
            files_changed=d.get("files_changed", []),
            nodes_added=d.get("nodes_added", []),
            nodes_removed=d.get("nodes_removed", []),
            nodes_modified=d.get("nodes_modified", []),
            workflow_edges_added=[tuple(e) for e in d.get("workflow_edges_added", [])],
            workflow_edges_removed=[tuple(e) for e in d.get("workflow_edges_removed", [])],
            stale_intents=d.get("stale_intents", []),
            cas_enabled=cas.get("enabled", False),
            cas_body_changed_nodes=cas.get("body_changed_nodes", 0),
            cas_affected_nodes=cas.get("affected_nodes", 0),
            cas_propagation_factor=cas.get("propagation_factor", 0.0),
            cas_nodes_skipped=cas.get("nodes_skipped", 0),
            cas_scc_count=cas.get("scc_count", 0),
        )
