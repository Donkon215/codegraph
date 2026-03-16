"""codegraph.architecture_health — Architecture health metrics.

Computes core architectural distributions and diagnostic statistics over the
canonical ArchitectureGraph model.
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from codegraph.architecture_graph import ArchitectureGraph
from codegraph.logging_config import get_logger
from codegraph.storage import resolve_path

logger = get_logger("architecture_health")


@dataclass
class ArchitectureHealthReport:
    fan_in_distribution: Dict[int, int]
    fan_out_distribution: Dict[int, int]
    module_size_distribution: Dict[str, int]
    cycle_count: int
    layer_violation_count: int
    orphan_nodes: int
    unused_services: int
    fan_in_entropy: float
    fan_out_variance: float
    module_complexity_variance: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fan_in_distribution": self.fan_in_distribution,
            "fan_out_distribution": self.fan_out_distribution,
            "module_size_distribution": self.module_size_distribution,
            "cycle_count": self.cycle_count,
            "layer_violations": self.layer_violation_count,
            "layer_violation_count": self.layer_violation_count,
            "orphan_nodes": self.orphan_nodes,
            "unused_services": self.unused_services,
            "fan_in_entropy": round(self.fan_in_entropy, 6),
            "fan_out_variance": round(self.fan_out_variance, 6),
            "module_complexity_variance": round(self.module_complexity_variance, 6),
        }

    def save(self, project_root: Path) -> Path:
        out = resolve_path(project_root, "architecture", "architecture_health.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        logger.info("Saved architecture health report -> %s", out)
        return out


def _count_cycles(adjacency: Dict[str, List[str]]) -> int:
    visited: set[str] = set()
    in_stack: set[str] = set()
    cycles = 0

    def _visit(node: str) -> None:
        nonlocal cycles
        visited.add(node)
        in_stack.add(node)
        for nxt in adjacency.get(node, []):
            if nxt == node:
                continue  # skip self-loops (recursive calls)
            if nxt not in visited:
                _visit(nxt)
            elif nxt in in_stack:
                cycles += 1
        in_stack.remove(node)

    for node in adjacency:
        if node not in visited:
            _visit(node)

    return cycles


def _variance(values: List[int]) -> float:
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    return sum((v - mean) ** 2 for v in values) / len(values)


def _entropy(distribution: Dict[int, int]) -> float:
    total = sum(distribution.values())
    if total <= 0:
        return 0.0
    entropy = 0.0
    for count in distribution.values():
        if count <= 0:
            continue
        p = count / total
        entropy -= p * math.log2(p)
    return entropy


def compute_architecture_health(architecture_graph: ArchitectureGraph) -> ArchitectureHealthReport:
    nodes = architecture_graph.structure_graph.nodes
    edges = architecture_graph.workflow_graph.edges

    fan_in: Dict[str, int] = defaultdict(int)
    fan_out: Dict[str, int] = defaultdict(int)
    adjacency: Dict[str, List[str]] = defaultdict(list)

    for edge in edges:
        fan_out[edge.source] += 1
        fan_in[edge.target] += 1
        adjacency[edge.source].append(edge.target)

    module_sizes: Counter[str] = Counter()
    for node in nodes:
        module_sizes[node.file] += 1

    node_ids = {n.id for n in nodes}
    fan_in_values: List[int] = []
    fan_out_values: List[int] = []
    orphan_nodes = 0

    for node_id in node_ids:
        fi = fan_in.get(node_id, 0)
        fo = fan_out.get(node_id, 0)
        fan_in_values.append(fi)
        fan_out_values.append(fo)
        if fi == 0 and fo == 0:
            orphan_nodes += 1

    fan_in_distribution = dict(sorted(Counter(fan_in_values).items()))
    fan_out_distribution = dict(sorted(Counter(fan_out_values).items()))

    layer_violations = 0
    for edge in edges:
        src = architecture_graph.intent_graph.get_node(edge.source)
        tgt = architecture_graph.intent_graph.get_node(edge.target)
        if src and tgt and src.layer < tgt.layer:
            layer_violations += 1

    service_nodes = [
        n.id for n in nodes
        if n.type in ("class", "function", "method")
        and (n.id.endswith("Service") or "::" in n.id and n.id.split("::")[-1].endswith("Service"))
    ]
    # A class service is used if any of its methods have external callers
    def _is_service_used(sid: str) -> bool:
        if fan_in.get(sid, 0) > 0:
            return True
        prefix = sid + "::"
        for e in edges:
            if e.target.startswith(prefix) and not e.source.startswith(prefix):
                return True
        return False

    unused_services = sum(1 for sid in service_nodes if not _is_service_used(sid))

    return ArchitectureHealthReport(
        fan_in_distribution=fan_in_distribution,
        fan_out_distribution=fan_out_distribution,
        module_size_distribution={k: v for k, v in module_sizes.most_common()},
        cycle_count=_count_cycles(adjacency),
        layer_violation_count=layer_violations,
        orphan_nodes=orphan_nodes,
        unused_services=unused_services,
        fan_in_entropy=_entropy(fan_in_distribution),
        fan_out_variance=_variance(fan_out_values),
        module_complexity_variance=_variance(list(module_sizes.values())),
    )


def build_health_report(project_root: Path) -> ArchitectureHealthReport:
    architecture_graph = ArchitectureGraph.load(project_root)
    return compute_architecture_health(architecture_graph)
