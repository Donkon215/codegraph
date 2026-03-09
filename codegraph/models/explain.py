"""codegraph.models.explain — ExplainResult data model.

Tasks B-014, B-043, B-045.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from codegraph.utils.formatting import format_json


@dataclass
class ExplainResult:
    """Output of ``codegraph explain <node>``."""

    node_id: str = ""
    body_hash: str = ""
    body_hash_status: str = "unchanged"  # unchanged | changed
    line: int = 0
    intent: Optional[str] = None
    layer: int = 3
    arch_layer: Optional[str] = None
    called_by: List[str] = field(default_factory=list)
    calls: List[str] = field(default_factory=list)
    dynamic_edges: List[str] = field(default_factory=list)
    tests_covering: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)

    # B-043 — CAS fields
    dependency_hash: Optional[str] = None
    dependency_chain: List[str] = field(default_factory=list)
    dependent_count: int = 0
    would_invalidate: List[str] = field(default_factory=list)

    # B-045 — Semantic / Graph_2 fields
    actions: List[Dict[str, Any]] = field(default_factory=list)
    guards: List[Dict[str, Any]] = field(default_factory=list)
    side_effects: List[Dict[str, Any]] = field(default_factory=list)
    domain_tags: List[str] = field(default_factory=list)
    behavior_hash: Optional[str] = None
    semantic_confidence: Optional[float] = None

    _MAX_INVALIDATE_TEXT = 20  # show top N in text output

    def to_text(self) -> str:
        """Formatted multi-section text matching the README layout."""
        lines = [
            f"Node:          {self.node_id}",
            f"Body Hash:     {self.body_hash} ({self.body_hash_status})",
            f"Line:          {self.line}",
            f"Intent:        {self.intent or '(none)'}",
            f"Layer:         {self.layer}",
        ]
        if self.arch_layer:
            lines.append(f"Arch Layer:    {self.arch_layer}")
        if self.tags:
            lines.append(f"Tags:          {', '.join(self.tags)}")
        lines.append(f"Called By:     {', '.join(self.called_by) or '(none)'}")
        lines.append(f"Calls:         {', '.join(self.calls) or '(none)'}")
        if self.dynamic_edges:
            lines.append(f"Dynamic:       {', '.join(self.dynamic_edges)}")
        if self.tests_covering:
            lines.append(f"Tests:         {', '.join(self.tests_covering)}")

        # CAS section (B-043)
        if self.dependency_hash is not None:
            lines.append("")
            lines.append("── Content Address ──")
            lines.append(f"Dep Hash:      {self.dependency_hash}")
            if self.dependency_chain:
                lines.append(f"Dep Chain:     {', '.join(self.dependency_chain)}")
            lines.append(f"Dependents:    {self.dependent_count}")
            if self.would_invalidate:
                shown = self.would_invalidate[: self._MAX_INVALIDATE_TEXT]
                lines.append(f"Invalidates:   {', '.join(shown)}")
                if len(self.would_invalidate) > self._MAX_INVALIDATE_TEXT:
                    lines.append(f"  … and {len(self.would_invalidate) - self._MAX_INVALIDATE_TEXT} more")

        # Semantic section (B-045)
        if self.actions or self.side_effects or self.behavior_hash:
            lines.append("")
            lines.append("── Behavior ──")
            if self.behavior_hash:
                lines.append(f"Behavior Hash: {self.behavior_hash}")
            if self.semantic_confidence is not None:
                conf_pct = f"{self.semantic_confidence * 100:.0f}%"
                if self.semantic_confidence < 0.5:
                    conf_pct += " ⚠ low confidence"
                lines.append(f"Confidence:    {conf_pct}")
            if self.actions:
                lines.append(f"Actions:       {len(self.actions)}")
                for a in self.actions:
                    lines.append(f"  - {a.get('verb', '?')} {a.get('object', '?')}")
            if self.guards:
                lines.append(f"Guards:        {len(self.guards)}")
            if self.side_effects:
                lines.append(f"Side Effects:  {len(self.side_effects)}")
                for se in self.side_effects:
                    lines.append(f"  - {se.get('type', '?')}: {se.get('target', '?')}")
            if self.domain_tags:
                lines.append(f"Domain Tags:   {', '.join(self.domain_tags)}")

        return "\n".join(lines)

    def to_json(self) -> str:
        return format_json(self._to_dict())

    def _to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "node_id": self.node_id,
            "body_hash": self.body_hash,
            "body_hash_status": self.body_hash_status,
            "line": self.line,
            "intent": self.intent,
            "layer": self.layer,
            "called_by": self.called_by,
            "calls": self.calls,
            "dynamic_edges": self.dynamic_edges,
            "tests_covering": self.tests_covering,
            "tags": self.tags,
        }
        if self.arch_layer:
            d["arch_layer"] = self.arch_layer
        # CAS
        if self.dependency_hash is not None:
            d["dependency_hash"] = self.dependency_hash
            d["dependency_chain"] = self.dependency_chain
            d["dependent_count"] = self.dependent_count
            d["would_invalidate"] = self.would_invalidate
        # Semantic
        if self.actions or self.side_effects or self.behavior_hash:
            d["actions"] = self.actions
            d["guards"] = self.guards
            d["side_effects"] = self.side_effects
            d["domain_tags"] = self.domain_tags
            d["behavior_hash"] = self.behavior_hash
            d["semantic_confidence"] = self.semantic_confidence
        return d
