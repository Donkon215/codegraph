from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, List

from codegraph.subsystem_graph import SubsystemGraph


@dataclass
class SubsystemSandbox:
    subsystem_graph: SubsystemGraph
    _baseline: SubsystemGraph = field(init=False)

    def __post_init__(self) -> None:
        self._baseline = copy.deepcopy(self.subsystem_graph)

    def apply_change(self, change_spec: Dict[str, Any]) -> None:
        action = str(change_spec.get("action", "")).lower()

        if action == "split_node":
            self._split_node(change_spec)
        elif action == "merge_nodes":
            self._merge_nodes(change_spec)
        elif action == "redirect_edge":
            self._redirect_edge(change_spec)
        elif action == "insert_service_layer":
            self._insert_service_layer(change_spec)
        else:
            raise ValueError(f"Unsupported sandbox action: {action}")

    def simulate(self) -> Dict[str, Any]:
        before = self._baseline.compute_metrics()
        after = self.subsystem_graph.compute_metrics()

        violations: List[str] = []
        if after["cycle_count"] > before["cycle_count"]:
            violations.append("new_cycles_detected")
        if after["layer_violations"] > before["layer_violations"]:
            violations.append("new_layer_violations")

        score_before = _score_from_metrics(before)
        score_after = _score_from_metrics(after)

        return {
            "score_before": round(score_before, 3),
            "score_after": round(score_after, 3),
            "new_cycles": max(0, after["cycle_count"] - before["cycle_count"]),
            "violations": violations,
        }

    def get_metrics(self) -> Dict[str, Any]:
        return self.subsystem_graph.compute_metrics()

    def _split_node(self, spec: Dict[str, Any]) -> None:
        source_node = str(spec.get("node", "")).strip()
        new_nodes = spec.get("new_nodes", [])
        if not source_node or len(new_nodes) < 2:
            raise ValueError("split_node requires node and at least two new_nodes")

        node_index = {str(node.get("id", "")): node for node in self.subsystem_graph.nodes}
        original = node_index.get(source_node)
        if not original:
            raise ValueError(f"Node not found in subsystem: {source_node}")

        self.subsystem_graph.nodes = [node for node in self.subsystem_graph.nodes if str(node.get("id", "")) != source_node]
        self.subsystem_graph.edges = [
            edge for edge in self.subsystem_graph.edges
            if str(edge.get("source", "")) != source_node and str(edge.get("target", "")) != source_node
        ]

        for new_node in new_nodes:
            cloned = dict(original)
            cloned["id"] = new_node
            self.subsystem_graph.nodes.append(cloned)

    def _merge_nodes(self, spec: Dict[str, Any]) -> None:
        nodes = [str(node) for node in spec.get("nodes", [])]
        merged_id = str(spec.get("merged_id", "")).strip()
        if len(nodes) < 2 or not merged_id:
            raise ValueError("merge_nodes requires nodes and merged_id")

        keep_template = None
        for node in self.subsystem_graph.nodes:
            if str(node.get("id", "")) in nodes:
                keep_template = dict(node)
                break
        if keep_template is None:
            raise ValueError("No merge candidate nodes found")

        keep_template["id"] = merged_id
        self.subsystem_graph.nodes = [
            node for node in self.subsystem_graph.nodes if str(node.get("id", "")) not in nodes
        ]
        self.subsystem_graph.nodes.append(keep_template)

        rewritten: List[Dict[str, Any]] = []
        for edge in self.subsystem_graph.edges:
            source = str(edge.get("source", ""))
            target = str(edge.get("target", ""))
            if source in nodes:
                source = merged_id
            if target in nodes:
                target = merged_id
            if source == target:
                continue
            rewritten.append({**edge, "source": source, "target": target})
        self.subsystem_graph.edges = rewritten

    def _redirect_edge(self, spec: Dict[str, Any]) -> None:
        source = str(spec.get("source", "")).strip()
        old_target = str(spec.get("old_target", "")).strip()
        new_target = str(spec.get("new_target", "")).strip()
        if not source or not old_target or not new_target:
            raise ValueError("redirect_edge requires source, old_target, new_target")

        updated = False
        for edge in self.subsystem_graph.edges:
            if str(edge.get("source", "")) == source and str(edge.get("target", "")) == old_target:
                edge["target"] = new_target
                updated = True
        if not updated:
            self.subsystem_graph.edges.append(
                {"source": source, "target": new_target, "edge_type": "call", "confidence": "ai_inferred"}
            )

    def _insert_service_layer(self, spec: Dict[str, Any]) -> None:
        source = str(spec.get("source", "")).strip()
        target = str(spec.get("target", "")).strip()
        service_node = str(spec.get("service_node", "")).strip()
        if not source or not target or not service_node:
            raise ValueError("insert_service_layer requires source, target, service_node")

        if not any(str(node.get("id", "")) == service_node for node in self.subsystem_graph.nodes):
            self.subsystem_graph.nodes.append({
                "id": service_node,
                "file": service_node.split("::", 1)[0],
                "type": "class",
                "layer": 3,
            })

        self.subsystem_graph.edges = [
            edge for edge in self.subsystem_graph.edges
            if not (str(edge.get("source", "")) == source and str(edge.get("target", "")) == target)
        ]
        self.subsystem_graph.edges.append({"source": source, "target": service_node, "edge_type": "call", "confidence": "ai_inferred"})
        self.subsystem_graph.edges.append({"source": service_node, "target": target, "edge_type": "call", "confidence": "ai_inferred"})


def _score_from_metrics(metrics: Dict[str, Any]) -> float:
    cycle_penalty = min(1.0, metrics.get("cycle_count", 0) / 5.0)
    layer_penalty = min(1.0, metrics.get("layer_violations", 0) / max(1, metrics.get("edges", 1)))
    fanout_penalty = min(1.0, metrics.get("fan_out_max", 0) / 25.0)
    return max(0.0, 1.0 - (0.45 * cycle_penalty + 0.35 * layer_penalty + 0.20 * fanout_penalty))
