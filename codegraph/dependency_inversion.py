"""codegraph.dependency_inversion — Dependency inversion suggestion engine."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from codegraph.architecture_score import compute_score
from codegraph.index import IndexStore


def _module_of(node_id: str) -> str:
    return node_id.split("::")[0] if "::" in node_id else node_id


def _infer_layer(module: str) -> int:
    lower = module.lower()
    if any(token in lower for token in ("controller", "api", "ui", "cli", "frontend")):
        return 3
    if any(token in lower for token in ("service", "engine", "usecase", "application")):
        return 2
    if any(token in lower for token in ("repo", "repository", "db", "database", "storage", "infra")):
        return 1
    return 2


def _interface_name_for(module: str) -> str:
    name = Path(module).stem
    normalized = "".join(ch for ch in name.title() if ch.isalnum())
    if not normalized:
        normalized = "Dependency"
    return f"I{normalized}"


@dataclass
class DependencyInversionSuggestion:
    source_node: str
    target_node: str
    interface_name: str
    affected_nodes: List[str]
    score_delta: float
    confidence: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_node": self.source_node,
            "target_node": self.target_node,
            "interface_name": self.interface_name,
            "affected_nodes": self.affected_nodes,
            "score_delta": round(self.score_delta, 4),
            "confidence": round(self.confidence, 3),
        }


def suggest_dependency_inversions(
    index: IndexStore,
    *,
    fan_in_threshold: int = 10,
    fan_out_threshold: int = 3,
    project_root: Optional[Path] = None,
) -> List[DependencyInversionSuggestion]:
    """Suggest dependency inversions where higher-layer modules depend on lower-layer modules."""
    conn = index._get_conn()
    rows = conn.execute("SELECT node_id, callee_id FROM callees").fetchall()

    module_out: Dict[str, Set[str]] = {}
    module_in: Dict[str, Set[str]] = {}
    module_edges: List[Tuple[str, str]] = []

    for source, target in rows:
        source_module = _module_of(source)
        target_module = _module_of(target)
        if source_module == target_module:
            continue
        module_edges.append((source_module, target_module))
        module_out.setdefault(source_module, set()).add(target_module)
        module_in.setdefault(target_module, set()).add(source_module)
        module_in.setdefault(source_module, module_in.get(source_module, set()))
        module_out.setdefault(target_module, module_out.get(target_module, set()))

    baseline_score = compute_score(project_root).score if project_root is not None else 0.0
    suggestions: List[DependencyInversionSuggestion] = []

    for source_module, target_module in sorted(set(module_edges)):
        source_layer = _infer_layer(source_module)
        target_layer = _infer_layer(target_module)

        if source_layer <= target_layer:
            continue

        target_fan_in = len(module_in.get(target_module, set()))
        source_fan_out = len(module_out.get(source_module, set()))
        if target_fan_in < fan_in_threshold and source_fan_out < fan_out_threshold:
            continue

        interface_name = _interface_name_for(target_module)
        confidence = min(
            1.0,
            0.5
            + min(0.25, target_fan_in / max(1, fan_in_threshold * 4))
            + min(0.25, source_fan_out / max(1, fan_out_threshold * 4)),
        )
        score_delta = max(0.0, (confidence - 0.5) * 0.2)
        if project_root is not None:
            score_delta = max(score_delta, max(0.0, (baseline_score + score_delta) - baseline_score))

        suggestions.append(
            DependencyInversionSuggestion(
                source_node=source_module,
                target_node=target_module,
                interface_name=interface_name,
                affected_nodes=[source_module, target_module, interface_name],
                score_delta=score_delta,
                confidence=confidence,
            )
        )

    suggestions.sort(key=lambda suggestion: (suggestion.confidence, suggestion.score_delta), reverse=True)
    return suggestions
