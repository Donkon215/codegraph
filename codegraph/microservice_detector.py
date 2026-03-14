"""codegraph.microservice_detector — Microservice candidate detection engine."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from codegraph.index import IndexStore
from codegraph.models.graph0 import Graph0
from codegraph.subsystem import detect_subsystems


def _module_of(node_id: str) -> str:
    return node_id.split("::")[0] if "::" in node_id else node_id


@dataclass
class MicroserviceCandidate:
    subsystem_name: str
    nodes: List[str]
    cohesion_score: float
    coupling_score: float
    api_surface: List[str]
    confidence: float
    expected_score_delta: float
    metrics: Dict[str, float]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "subsystem_name": self.subsystem_name,
            "nodes": self.nodes,
            "cohesion_score": round(self.cohesion_score, 3),
            "coupling_score": round(self.coupling_score, 3),
            "api_surface": self.api_surface,
            "confidence": round(self.confidence, 3),
            "expected_score_delta": round(self.expected_score_delta, 4),
            "metrics": {k: round(v, 4) for k, v in self.metrics.items()},
            "recommendation": "extract_as_microservice",
        }


def _collect_module_metrics(index: IndexStore) -> Tuple[Dict[str, int], Dict[str, int], Dict[str, int]]:
    conn = index._get_conn()
    fan_in: Dict[str, int] = {}
    fan_out: Dict[str, int] = {}
    test_coverage: Dict[str, int] = {}

    for source, target in conn.execute("SELECT node_id, callee_id FROM callees").fetchall():
        source_module = _module_of(source)
        target_module = _module_of(target)
        if source_module == target_module:
            continue
        fan_out[source_module] = fan_out.get(source_module, 0) + 1
        fan_in[target_module] = fan_in.get(target_module, 0) + 1

    try:
        for _, node_id in conn.execute("SELECT test_id, node_id FROM tests").fetchall():
            module = _module_of(node_id)
            test_coverage[module] = test_coverage.get(module, 0) + 1
    except Exception:
        pass

    return fan_in, fan_out, test_coverage


def _api_surface_for_modules(graph: Graph0, modules: Set[str]) -> List[str]:
    api_nodes: List[str] = []
    for node in graph.nodes:
        if node.file not in modules:
            continue
        symbol = node.id.split("::")[-1]
        if node.type in ("function", "class") and symbol and not symbol.startswith("_"):
            api_nodes.append(node.id)
    return sorted(api_nodes)[:30]


def detect_microservice_candidates(
    graph: Graph0,
    index: IndexStore,
    *,
    cluster_size_threshold: int = 2,
    cohesion_threshold: float = 0.8,
    coupling_threshold: float = 0.2,
    project_root: Optional[Path] = None,
) -> List[MicroserviceCandidate]:
    """Detect subsystems that are good microservice extraction candidates."""
    subsystem_report = detect_subsystems(graph, index)
    fan_in, fan_out, test_coverage = _collect_module_metrics(index)

    candidates: List[MicroserviceCandidate] = []
    for subsystem in subsystem_report.subsystems:
        cluster_size = len(subsystem.files)
        if cluster_size <= cluster_size_threshold:
            continue

        internal_edges = float(subsystem.internal_edges)
        external_edges = float(subsystem.external_edges)
        cohesion = internal_edges / max(1.0, internal_edges + external_edges)
        coupling = external_edges / max(1.0, float(cluster_size))

        modules = set(subsystem.files)
        api_surface = _api_surface_for_modules(graph, modules)
        if not api_surface:
            continue

        if cohesion < cohesion_threshold:
            continue
        if coupling > coupling_threshold:
            continue

        total_fan_in = sum(fan_in.get(module, 0) for module in modules)
        total_fan_out = sum(fan_out.get(module, 0) for module in modules)
        total_test_coverage = sum(test_coverage.get(module, 0) for module in modules)

        confidence = min(
            1.0,
            0.5 + min(0.3, cohesion * 0.3) + min(0.2, max(0.0, 0.2 - coupling)),
        )
        expected_score_delta = max(0.0, (cohesion - coupling) * 0.15)

        candidates.append(
            MicroserviceCandidate(
                subsystem_name=subsystem.name,
                nodes=sorted(subsystem.files),
                cohesion_score=cohesion,
                coupling_score=coupling,
                api_surface=api_surface,
                confidence=confidence,
                expected_score_delta=expected_score_delta,
                metrics={
                    "internal_edges": internal_edges,
                    "external_edges": external_edges,
                    "cluster_size": float(cluster_size),
                    "fan_in": float(total_fan_in),
                    "fan_out": float(total_fan_out),
                    "test_coverage": float(total_test_coverage),
                },
            )
        )

    candidates.sort(
        key=lambda candidate: (candidate.confidence, candidate.expected_score_delta),
        reverse=True,
    )
    return candidates
