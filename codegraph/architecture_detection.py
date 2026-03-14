"""codegraph.architecture_detection — Architecture pattern detection engine.

Detects dominant architecture styles and structural anti-pattern clusters
from the dependency graph.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

from codegraph.index import IndexStore
from codegraph.models.graph0 import Graph0


def _module_of(node_id: str) -> str:
    return node_id.split("::")[0] if "::" in node_id else node_id


def _module_graph(graph: Graph0, index: Optional[IndexStore]) -> Dict[str, Set[str]]:
    adj: Dict[str, Set[str]] = defaultdict(set)
    files = {node.file for node in graph.nodes if node.file}
    for module in files:
        adj[module]

    if index is None:
        return adj

    conn = index._get_conn()
    for source, target in conn.execute("SELECT node_id, callee_id FROM callees").fetchall():
        source_module = _module_of(source)
        target_module = _module_of(target)
        if source_module and target_module and source_module != target_module:
            adj[source_module].add(target_module)
    return adj


def detect_layered_architecture(
    graph: Graph0,
    index: Optional[IndexStore] = None,
) -> Dict[str, Any]:
    """Detect layered architecture signals from module dependency directions."""
    adj = _module_graph(graph, index)
    if not adj:
        return {
            "architecture_type": "layered",
            "confidence": 0.0,
            "violations": [],
            "details": {"reason": "no modules"},
        }

    def infer_level(module: str) -> int:
        lower = module.lower()
        if any(part in lower for part in ("ui", "cli", "api", "frontend")):
            return 0
        if any(part in lower for part in ("service", "engine", "core", "governance", "intelligence")):
            return 1
        if any(part in lower for part in ("model", "schema", "storage", "database", "db", "infrastructure")):
            return 2
        return 1

    upward_violations: List[Dict[str, str]] = []
    total_edges = 0
    for source, targets in adj.items():
        source_level = infer_level(source)
        for target in targets:
            total_edges += 1
            target_level = infer_level(target)
            if source_level > target_level:
                upward_violations.append({"source": source, "target": target})

    if total_edges == 0:
        confidence = 0.0
    else:
        confidence = 1.0 - (len(upward_violations) / total_edges)

    return {
        "architecture_type": "layered",
        "confidence": round(max(0.0, min(1.0, confidence)), 3),
        "violations": upward_violations[:25],
        "details": {
            "total_edges": total_edges,
            "upward_violations": len(upward_violations),
        },
    }


def detect_event_driven_architecture(
    graph: Graph0,
    index: Optional[IndexStore] = None,
) -> Dict[str, Any]:
    """Detect event-driven signals: publisher-like fan-out and event naming."""
    adj = _module_graph(graph, index)
    if not adj:
        return {
            "architecture_type": "event_driven",
            "confidence": 0.0,
            "violations": [],
            "details": {},
        }

    event_named = [
        module for module in adj
        if any(token in module.lower() for token in ("event", "queue", "pub", "sub", "broker", "stream"))
    ]
    broadcasters = [module for module, targets in adj.items() if len(targets) >= 3]

    density = len(event_named) / max(1, len(adj))
    broadcaster_ratio = len(broadcasters) / max(1, len(adj))
    confidence = min(1.0, density * 0.6 + broadcaster_ratio * 0.8)

    return {
        "architecture_type": "event_driven",
        "confidence": round(confidence, 3),
        "violations": [],
        "details": {
            "event_named_modules": event_named[:30],
            "broadcaster_modules": broadcasters[:30],
        },
    }


def detect_pipeline_architecture(
    graph: Graph0,
    index: Optional[IndexStore] = None,
) -> Dict[str, Any]:
    """Detect pipeline-like linear flows in module dependencies."""
    adj = _module_graph(graph, index)
    if not adj:
        return {
            "architecture_type": "pipeline",
            "confidence": 0.0,
            "violations": [],
            "details": {},
        }

    indegree: Dict[str, int] = defaultdict(int)
    outdegree: Dict[str, int] = defaultdict(int)
    for source, targets in adj.items():
        outdegree[source] += len(targets)
        for target in targets:
            indegree[target] += 1

    chain_modules = {
        module for module in adj
        if indegree.get(module, 0) <= 1 and outdegree.get(module, 0) <= 1
    }
    confidence = len(chain_modules) / max(1, len(adj))

    fragments = []
    for module in sorted(chain_modules):
        targets = sorted(adj.get(module, set()))
        if targets:
            fragments.append({"stage": module, "next": targets[0]})

    return {
        "architecture_type": "pipeline",
        "confidence": round(confidence, 3),
        "violations": [],
        "details": {
            "pipeline_fragments": fragments[:30],
            "chain_module_count": len(chain_modules),
        },
    }


def detect_bidirectional_clusters(
    graph: Graph0,
    index: Optional[IndexStore] = None,
) -> Dict[str, Any]:
    """Detect bidirectional module pairs/clusters indicating tight coupling."""
    adj = _module_graph(graph, index)
    pairs: List[Tuple[str, str]] = []
    seen: Set[Tuple[str, str]] = set()
    for source, targets in adj.items():
        for target in targets:
            if source in adj.get(target, set()):
                pair = (min(source, target), max(source, target))
                if pair not in seen:
                    seen.add(pair)
                    pairs.append(pair)

    confidence = min(1.0, len(pairs) / max(1, len(adj)))
    violations = [{"source": source, "target": target} for source, target in pairs[:30]]
    return {
        "architecture_type": "bidirectional",
        "confidence": round(confidence, 3),
        "violations": violations,
        "details": {"bidirectional_pairs": len(pairs)},
    }


def detect_architecture_patterns(
    graph: Graph0,
    index: Optional[IndexStore] = None,
) -> Dict[str, Any]:
    """Run all architecture detectors and select dominant architecture type."""
    layered = detect_layered_architecture(graph, index)
    event_driven = detect_event_driven_architecture(graph, index)
    pipeline = detect_pipeline_architecture(graph, index)
    bidirectional = detect_bidirectional_clusters(graph, index)

    reports = [layered, event_driven, pipeline, bidirectional]
    dominant = max(reports, key=lambda report: report.get("confidence", 0.0))

    return {
        "architecture_type": dominant.get("architecture_type", "unknown"),
        "confidence": dominant.get("confidence", 0.0),
        "violations": dominant.get("violations", []),
        "reports": {
            "layered": layered,
            "event_driven": event_driven,
            "pipeline": pipeline,
            "bidirectional": bidirectional,
        },
    }
