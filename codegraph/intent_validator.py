from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from codegraph.architecture_graph import ArchitectureGraph
from codegraph.architecture_intent import ArchitectureIntent


@dataclass
class ArchitectureIntentReport:
    violations: List[Dict[str, Any]] = field(default_factory=list)
    drift_score: float = 0.0
    rule_violations: int = 0
    layer_integrity_score: float = 1.0
    checked_edges: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "violations": self.violations,
            "drift_score": round(self.drift_score, 4),
            "rule_violations": int(self.rule_violations),
            "layer_integrity_score": round(self.layer_integrity_score, 4),
            "checked_edges": int(self.checked_edges),
        }


def _module_of_node(node: Dict[str, Any]) -> str:
    file_path = str(node.get("file", "")).replace("\\", "/")
    if file_path:
        return file_path
    node_id = str(node.get("id", ""))
    return node_id.split("::", 1)[0] if "::" in node_id else node_id


def _resolve_layer(module_path: str, intent: ArchitectureIntent) -> Optional[str]:
    normalized = module_path.replace("\\", "/")
    for layer_name, patterns in intent.layers.items():
        for pattern in patterns:
            p = str(pattern).replace("\\", "/").strip("/")
            if not p:
                continue
            if normalized == p or normalized.startswith(f"{p}/") or f"/{p}/" in f"/{normalized}/":
                return layer_name
    return None


def _build_rule_map(intent: ArchitectureIntent) -> Dict[Tuple[str, str], bool]:
    mapping: Dict[Tuple[str, str], bool] = {}
    for rule in intent.rules:
        src = str(rule.get("from", "")).strip()
        tgt = str(rule.get("to", "")).strip()
        if not src or not tgt:
            continue
        mapping[(src, tgt)] = bool(rule.get("allowed", False))
    return mapping


def validate_architecture_intent(
    architecture_graph: ArchitectureGraph,
    intent: ArchitectureIntent,
) -> ArchitectureIntentReport:
    report = ArchitectureIntentReport()
    if not intent.layers or not intent.rules:
        return report

    node_map = {str(node.get("id", "")): node for node in architecture_graph.nodes}
    rule_map = _build_rule_map(intent)

    checked = 0
    violations: List[Dict[str, Any]] = []

    for edge in architecture_graph.edges:
        source = str(edge.get("source", ""))
        target = str(edge.get("target", ""))
        src_node = node_map.get(source)
        tgt_node = node_map.get(target)
        if not src_node or not tgt_node:
            continue

        src_layer = _resolve_layer(_module_of_node(src_node), intent)
        tgt_layer = _resolve_layer(_module_of_node(tgt_node), intent)
        if not src_layer or not tgt_layer:
            continue

        checked += 1
        allowed = rule_map.get((src_layer, tgt_layer), True)
        if not allowed:
            violations.append({
                "from_node": source,
                "to_node": target,
                "from_layer": src_layer,
                "to_layer": tgt_layer,
                "edge_type": str(edge.get("edge_type", "call")),
                "message": f"{src_layer} cannot depend on {tgt_layer}",
            })

    report.violations = violations
    report.checked_edges = checked
    report.rule_violations = len(violations)
    if checked > 0:
        report.drift_score = len(violations) / checked
        report.layer_integrity_score = max(0.0, 1.0 - report.drift_score)
    else:
        report.drift_score = 0.0
        report.layer_integrity_score = 1.0

    return report
