"""codegraph.subsystem_extractor — Subsystem extraction suggestion engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from codegraph.architecture_decay import ArchitectureDecayReport, detect_architecture_decay
from codegraph.architecture_detection import detect_bidirectional_clusters
from codegraph.architecture_score import compute_score
from codegraph.index import IndexStore
from codegraph.models.graph0 import Graph0
from codegraph.simulator import SimulatedChange, simulate_changes
from codegraph.subsystem_graph import SubsystemGraph


_SUBSYSTEM_CACHE: Dict[Tuple[str, int, int, int], SubsystemGraph] = {}


def extract_subsystem(
    architecture_graph: Any,
    root_node: str,
    depth: int = 2,
    max_nodes: int = 200,
) -> SubsystemGraph:
    """Extract a connected subsystem slice around ``root_node``.

    Traverses call/dependency/runtime style edges breadth-first up to ``depth``
    and returns a temporary `SubsystemGraph` view derived from the canonical
    architecture graph.
    """
    if depth < 0:
        raise ValueError("depth must be >= 0")
    if max_nodes < 1:
        raise ValueError("max_nodes must be >= 1")

    node_ids = {str(node.get("id", "")) for node in architecture_graph.nodes}
    if root_node not in node_ids:
        raise ValueError(f"Root node not found in architecture graph: {root_node}")

    graph_version = int(architecture_graph.metadata.get("graph_version", 0))
    cache_key = (root_node, depth, max_nodes, graph_version)
    cached = _SUBSYSTEM_CACHE.get(cache_key)
    if cached is not None:
        return cached

    allowed_edge_types = {
        "call",
        "dependency",
        "depends",
        "dataflow",
        "data_flow",
        "runtime",
        "http_call",
        "rpc_call",
        "event",
        "event_produce",
        "event_consume",
        "queue_task",
        "frontend_to_backend",
    }

    adjacency: Dict[str, Set[str]] = {node_id: set() for node_id in node_ids}
    for edge in architecture_graph.edges:
        source = str(edge.get("source", ""))
        target = str(edge.get("target", ""))
        edge_type = str(edge.get("edge_type", "call")).lower()
        if source not in adjacency or target not in adjacency:
            continue
        if edge_type in allowed_edge_types:
            adjacency[source].add(target)
            adjacency[target].add(source)

    selected_nodes: Set[str] = {root_node}
    frontier: Set[str] = {root_node}
    for _ in range(depth):
        if len(selected_nodes) >= max_nodes:
            break
        next_frontier: Set[str] = set()
        for node in frontier:
            for nxt in adjacency.get(node, set()):
                if nxt in selected_nodes:
                    continue
                selected_nodes.add(nxt)
                next_frontier.add(nxt)
                if len(selected_nodes) >= max_nodes:
                    break
            if len(selected_nodes) >= max_nodes:
                break
        frontier = next_frontier
        if not frontier:
            break

    internal_edges: List[Dict[str, Any]] = []
    external_edges: List[Dict[str, Any]] = []
    for edge in architecture_graph.edges:
        source = str(edge.get("source", ""))
        target = str(edge.get("target", ""))
        if source in selected_nodes and target in selected_nodes:
            internal_edges.append(dict(edge))
        elif (source in selected_nodes) ^ (target in selected_nodes):
            external_edges.append(dict(edge))

    subsystem = SubsystemGraph.from_architecture_graph(
        architecture_graph,
        selected_nodes,
        internal_edges,
        external_edges,
        root_node=root_node,
    )

    boundary_nodes = set(subsystem.boundary_nodes)
    for edge in internal_edges:
        source = str(edge.get("source", ""))
        target = str(edge.get("target", ""))
        source_module = source.split("::", 1)[0]
        target_module = target.split("::", 1)[0]
        if source_module != target_module:
            boundary_nodes.add(source)
            boundary_nodes.add(target)
    subsystem.boundary_nodes = sorted(boundary_nodes)

    subsystem.metadata["depth"] = depth
    subsystem.metadata["max_nodes"] = max_nodes
    subsystem.metadata["external_dependencies"] = sorted({
        str(edge.get("target", ""))
        if str(edge.get("source", "")) in selected_nodes
        else str(edge.get("source", ""))
        for edge in external_edges
    })
    subsystem.metadata["original_edges"] = list(internal_edges)

    if len(_SUBSYSTEM_CACHE) > 256:
        _SUBSYSTEM_CACHE.clear()
    _SUBSYSTEM_CACHE[cache_key] = subsystem
    return subsystem


@dataclass
class RefactorSuggestion:
    type: str
    affected_nodes: List[str] = field(default_factory=list)
    description: str = ""
    confidence: float = 0.0
    expected_score_delta: float = 0.0
    simulation_risk_level: str = "UNTESTED"
    simulation_summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "affected_nodes": self.affected_nodes,
            "description": self.description,
            "confidence": round(self.confidence, 3),
            "expected_score_delta": round(self.expected_score_delta, 3),
            "simulation_risk_level": self.simulation_risk_level,
            "simulation_summary": self.simulation_summary,
        }


def _build_module_edge_examples(index: IndexStore) -> Dict[Tuple[str, str], Tuple[str, str]]:
    examples: Dict[Tuple[str, str], Tuple[str, str]] = {}
    conn = index._get_conn()
    for source, target in conn.execute("SELECT node_id, callee_id FROM callees").fetchall():
        source_module = source.split("::")[0] if "::" in source else source
        target_module = target.split("::")[0] if "::" in target else target
        if source_module == target_module:
            continue
        key = (source_module, target_module)
        if key not in examples:
            examples[key] = (source, target)
    return examples


def _estimate_score_delta_from_simulation(simulation_result) -> float:
    delta = 0.0
    if simulation_result.coupling_delta < 0:
        delta += abs(simulation_result.coupling_delta) * 10.0
    if simulation_result.new_cycle_count > 0:
        delta -= simulation_result.new_cycle_count * 2.0
    delta -= len([v for v in simulation_result.violations if v.severity == "warning"]) * 0.5
    delta -= len([v for v in simulation_result.violations if v.severity == "error"]) * 2.0
    return delta


def _simulate_suggestion(
    suggestion: RefactorSuggestion,
    index: IndexStore,
    module_edges: Dict[Tuple[str, str], Tuple[str, str]],
) -> RefactorSuggestion:
    changes: List[SimulatedChange] = []
    modules = suggestion.affected_nodes

    if suggestion.type == "split_module" and modules:
        source_module = modules[0]
        for (source, target), edge in module_edges.items():
            if source == source_module:
                changes.append(
                    SimulatedChange(
                        action="remove_edge",
                        source=edge[0],
                        target=edge[1],
                        reason=f"simulate split of {source_module}",
                    )
                )
                break

    elif suggestion.type in ("extract_subsystem", "remove_dead_code_cluster") and modules:
        subsystem_set = set(modules)
        for (source, target), edge in module_edges.items():
            inside_source = source in subsystem_set
            inside_target = target in subsystem_set
            if inside_source != inside_target:
                changes.append(
                    SimulatedChange(
                        action="remove_edge",
                        source=edge[0],
                        target=edge[1],
                        reason=f"simulate subsystem extraction boundary for {suggestion.type}",
                    )
                )
                break

    elif suggestion.type in ("invert_dependency", "introduce_interface") and len(modules) >= 2:
        source_module = modules[0]
        target_module = modules[1]
        edge = module_edges.get((source_module, target_module))
        if edge:
            changes.append(
                SimulatedChange(
                    action="remove_edge",
                    source=edge[0],
                    target=edge[1],
                    reason="simulate dependency inversion",
                )
            )

    simulation_result = simulate_changes(changes, index) if changes else simulate_changes([], index)
    suggestion.simulation_risk_level = simulation_result.risk_level
    suggestion.simulation_summary = simulation_result.summary
    suggestion.expected_score_delta = _estimate_score_delta_from_simulation(simulation_result)
    return suggestion


def propose_refactor_suggestions(
    graph: Graph0,
    index: IndexStore,
    *,
    decay_report: Optional[ArchitectureDecayReport] = None,
) -> List[RefactorSuggestion]:
    """Propose structured refactor suggestions from decay signals."""
    report = decay_report or detect_architecture_decay(graph, index)
    suggestions: List[RefactorSuggestion] = []

    for warning in report.god_modules[:20]:
        suggestions.append(
            RefactorSuggestion(
                type="split_module",
                affected_nodes=[warning.module],
                description=(
                    f"Split high-coupling module {warning.module} "
                    f"(fan_in={warning.fan_in}, fan_out={warning.fan_out})"
                ),
                confidence=0.8,
            )
        )

    for cluster in report.cyclic_subsystems[:10]:
        suggestions.append(
            RefactorSuggestion(
                type="invert_dependency",
                affected_nodes=cluster.modules,
                description=(
                    f"Break cyclic subsystem of size {cluster.size} "
                    f"by inverting dependency directions"
                ),
                confidence=0.75,
            )
        )

    for subsystem in report.dead_subsystems[:10]:
        suggestions.append(
            RefactorSuggestion(
                type="remove_dead_code_cluster",
                affected_nodes=subsystem.modules,
                description=(
                    f"Dead subsystem '{subsystem.name}' has fan_in={subsystem.fan_in} "
                    f"and test_links={subsystem.test_links}"
                ),
                confidence=0.85,
            )
        )

    for subsystem in sorted(
        report.extractable_subsystems,
        key=lambda item: item.confidence,
        reverse=True,
    )[:10]:
        suggestions.append(
            RefactorSuggestion(
                type="extract_subsystem",
                affected_nodes=subsystem.modules,
                description=(
                    f"Extract cohesive subsystem '{subsystem.name}' "
                    f"(internal_edges={subsystem.internal_edges}, external_edges={subsystem.external_edges})"
                ),
                confidence=subsystem.confidence,
            )
        )

    bidirectional = detect_bidirectional_clusters(graph, index)
    for pair in bidirectional.get("violations", [])[:10]:
        suggestions.append(
            RefactorSuggestion(
                type="introduce_interface",
                affected_nodes=[pair["source"], pair["target"]],
                description=(
                    f"Introduce interface between bidirectional pair "
                    f"{pair['source']} and {pair['target']}"
                ),
                confidence=0.7,
            )
        )

    return suggestions


def simulate_refactor_suggestions(
    suggestions: List[RefactorSuggestion],
    index: IndexStore,
    *,
    project_root: Optional[Path] = None,
) -> List[RefactorSuggestion]:
    """Simulate suggestions with the existing simulator and score deltas."""
    module_edges = _build_module_edge_examples(index)
    baseline_score = compute_score(project_root).score if project_root is not None else 0.0

    simulated: List[RefactorSuggestion] = []
    for suggestion in suggestions:
        updated = _simulate_suggestion(suggestion, index, module_edges)
        if project_root is not None:
            updated.expected_score_delta = max(
                updated.expected_score_delta,
                round((baseline_score + (updated.expected_score_delta / 100.0)) - baseline_score, 4),
            )
        simulated.append(updated)

    simulated.sort(
        key=lambda item: (item.expected_score_delta, item.confidence),
        reverse=True,
    )
    return simulated


def generate_subsystem_extraction_report(
    graph: Graph0,
    index: IndexStore,
    *,
    project_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Detect boundaries, propose extraction refactors, and simulate outcomes."""
    decay_report = detect_architecture_decay(graph, index)
    suggestions = propose_refactor_suggestions(graph, index, decay_report=decay_report)
    simulated = simulate_refactor_suggestions(suggestions, index, project_root=project_root)

    return {
        "decay_report": decay_report.to_dict(),
        "suggestions": [suggestion.to_dict() for suggestion in simulated],
    }
