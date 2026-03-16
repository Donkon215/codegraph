from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from codegraph.architecture_smells import ArchitectureSmellIndex


@dataclass
class ReasoningItem:
    issue: str
    cause: str
    recommendation: str
    confidence: float = 0.8

    def to_dict(self) -> Dict[str, Any]:
        return {
            "issue": self.issue,
            "cause": self.cause,
            "recommendation": self.recommendation,
            "confidence": round(self.confidence, 4),
        }


@dataclass
class ArchitectureReasoningReport:
    items: List[ReasoningItem] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"items": [i.to_dict() for i in self.items]}


def explain_architecture_problems(smells: ArchitectureSmellIndex) -> ArchitectureReasoningReport:
    items: List[ReasoningItem] = []

    for smell in smells.smells:
        if smell.smell_type == "dependency_cycles":
            items.append(ReasoningItem(
                issue="Dependency cycle detected",
                cause=smell.description,
                recommendation="Break bidirectional dependency with an event bus or interface inversion.",
                confidence=0.92,
            ))
        elif smell.smell_type == "cross_layer_dependencies":
            items.append(ReasoningItem(
                issue="Cross-layer dependency violation",
                cause=smell.description,
                recommendation="Move orchestration to the service layer and use adapters in upper layers.",
                confidence=0.9,
            ))
        elif smell.smell_type == "fan_in_hotspot":
            items.append(ReasoningItem(
                issue="Fan-in hotspot",
                cause=smell.description,
                recommendation="Introduce façade/service contracts and split responsibilities to reduce direct callers.",
                confidence=0.86,
            ))
        elif smell.smell_type == "god_module":
            items.append(ReasoningItem(
                issue="God module",
                cause=smell.description,
                recommendation="Extract coherent components and keep compatibility wrappers to preserve API stability.",
                confidence=0.85,
            ))
        elif smell.smell_type == "orphan_services":
            items.append(ReasoningItem(
                issue="Orphan service",
                cause=smell.description,
                recommendation="Either wire service to real call paths or remove dead service code.",
                confidence=0.82,
            ))

    return ArchitectureReasoningReport(items=items)
