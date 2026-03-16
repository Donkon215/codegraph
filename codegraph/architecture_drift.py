from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from codegraph.architecture_graph import ArchitectureGraph
from codegraph.architecture_intent import ArchitectureIntent
from codegraph.intent_validator import validate_architecture_intent


@dataclass
class ArchitectureDriftReport:
    rule_drift: float = 0.0
    edge_drift: float = 0.0
    drift_score: float = 0.0
    violated_rules: int = 0
    total_rules: int = 0
    changed_edges: int = 0
    total_edges: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_drift": round(self.rule_drift, 4),
            "edge_drift": round(self.edge_drift, 4),
            "drift_score": round(self.drift_score, 4),
            "violated_rules": self.violated_rules,
            "total_rules": self.total_rules,
            "changed_edges": self.changed_edges,
            "total_edges": self.total_edges,
        }


def compute_architecture_drift(
    architecture_graph: ArchitectureGraph,
    intent: ArchitectureIntent,
) -> ArchitectureDriftReport:
    validation = validate_architecture_intent(architecture_graph, intent)

    total_edges = max(len(architecture_graph.edges), 1)
    changed_edges = len(validation.violations)
    edge_drift = changed_edges / total_edges

    total_rules = max(validation.checked_edges, 1)
    rule_drift = validation.rule_violations / total_rules

    drift_score = (rule_drift * 0.7) + (edge_drift * 0.3)

    return ArchitectureDriftReport(
        rule_drift=rule_drift,
        edge_drift=edge_drift,
        drift_score=drift_score,
        violated_rules=validation.rule_violations,
        total_rules=validation.checked_edges,
        changed_edges=changed_edges,
        total_edges=len(architecture_graph.edges),
    )
