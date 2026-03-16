from __future__ import annotations

import fnmatch
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Tuple

from codegraph.architecture_graph import ArchitectureGraph
from codegraph.architecture_drift import compute_architecture_drift
from codegraph.architecture_health import build_health_report
from codegraph.architecture_intent import load_architecture_intent
from codegraph.architecture_patterns import detect_patterns
from codegraph.architecture_smells import detect_architecture_smells
from codegraph.intent_validator import validate_architecture_intent


@dataclass
class MultiAxisArchitectureScore:
    score: float
    grade: str
    dimensions: Dict[str, float] = field(default_factory=dict)
    penalties: Dict[str, float] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": round(self.score, 4),
            "grade": self.grade,
            "dimensions": {k: round(v, 4) for k, v in self.dimensions.items()},
            "penalties": {k: round(v, 4) for k, v in self.penalties.items()},
            "metadata": self.metadata,
        }


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def _grade(score: float) -> str:
    if score >= 0.90:
        return "A"
    if score >= 0.80:
        return "B"
    if score >= 0.65:
        return "C"
    if score >= 0.50:
        return "D"
    return "F"


def _module_of(node_id: str) -> str:
    return node_id.split("::", 1)[0] if "::" in node_id else node_id


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _variance(values: List[int]) -> float:
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    return sum((v - mean) ** 2 for v in values) / len(values)


def _p95(values: List[int]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = int((len(ordered) - 1) * 0.95)
    return float(ordered[idx])


def _load_subsystem_mapping(project_root: Path) -> Dict[str, str]:
    system = _load_json(project_root / ".codegraph" / "architecture" / "system.json", {})
    mapping: Dict[str, str] = {}
    for sub in system.get("subsystems", []):
        name = sub.get("name", "")
        for comp in sub.get("components", []):
            mod = comp.get("module", "")
            if mod:
                mapping[mod] = name
    return mapping


def _forbidden_rule_violations(project_root: Path, edges: List[Tuple[str, str]]) -> int:
    rules = _load_json(project_root / ".codegraph" / "workflow" / "suggested_workflow.json", {}).get("rules", [])
    violations = 0
    for rule in rules:
        if rule.get("type") != "forbidden_call":
            continue
        src_pat = rule.get("source", "")
        tgt_pat = rule.get("target", "")
        for src, tgt in edges:
            if fnmatch.fnmatch(src, src_pat) and fnmatch.fnmatch(tgt, tgt_pat):
                violations += 1
    return violations


def _duplicate_artifact_penalty(project_root: Path) -> float:
    files = [
        project_root / ".codegraph" / "graphs" / "graph0.json",
        project_root / ".codegraph" / "graphs" / "graph1.json",
        project_root / ".codegraph" / "graphs" / "graph2.json",
        project_root / ".codegraph" / "workflow" / "workflow.json",
    ]
    seen: set[str] = set()
    duplicates = 0
    for path in files:
        if not path.exists():
            continue
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if digest in seen:
            duplicates += 1
        seen.add(digest)
    return min(0.08, duplicates * 0.02)


def _load_objective_targets(project_root: Path) -> Dict[str, Any]:
    return _load_json(project_root / ".codegraph" / "architecture" / "architecture_objectives.json", {})


def compute_architecture_index(project_root: Path) -> MultiAxisArchitectureScore:
    graph = ArchitectureGraph.load(project_root)
    health = build_health_report(project_root)
    smell_index = detect_architecture_smells(graph, project_root)

    # Pattern consistency influence
    try:
        from codegraph.index import IndexStore

        with IndexStore(project_root) as index:
            pattern_report = detect_patterns(project_root, graph.structure_graph, index)
        pattern_consistency = sum(p.consistency for p in pattern_report.patterns) / max(1, len(pattern_report.patterns))
    except Exception:
        pattern_consistency = 0.5

    nodes = graph.structure_graph.nodes
    edges = [(e.source, e.target) for e in graph.workflow_graph.edges]
    total_nodes = len(nodes)
    total_edges = len(edges)

    fan_in: Dict[str, int] = {}
    fan_out: Dict[str, int] = {}
    node_ids = {n.id for n in nodes}
    for src, tgt in edges:
        fan_out[src] = fan_out.get(src, 0) + 1
        fan_in[tgt] = fan_in.get(tgt, 0) + 1

    fan_in_vals = [fan_in.get(nid, 0) for nid in node_ids]
    fan_out_vals = [fan_out.get(nid, 0) for nid in node_ids]

    module_sizes: Dict[str, int] = {}
    for node in nodes:
        module_sizes[node.file] = module_sizes.get(node.file, 0) + 1

    # Structural Health
    p95_fan_in = _p95(fan_in_vals)
    p95_fan_out = _p95(fan_out_vals)
    p95_module = _p95(list(module_sizes.values()))
    god_modules = sum(1 for size in module_sizes.values() if size > 30)

    structural_health = (
        (1.0 - min(1.0, p95_fan_in / 30.0))
        + (1.0 - min(1.0, p95_fan_out / 20.0))
        + (1.0 - min(1.0, p95_module / 40.0))
        + (1.0 - min(1.0, health.cycle_count / 5.0))
        + (1.0 - min(1.0, god_modules / 10.0))
    ) / 5.0

    # Dependency Correctness
    subsystem_map = _load_subsystem_mapping(project_root)
    classified = 0
    cross_subsystem = 0
    inversion_classified = 0
    inversion_good = 0
    for src, tgt in edges:
        src_mod = _module_of(src)
        tgt_mod = _module_of(tgt)
        src_sub = subsystem_map.get(src_mod)
        tgt_sub = subsystem_map.get(tgt_mod)
        if src_sub and tgt_sub:
            classified += 1
            if src_sub != tgt_sub:
                cross_subsystem += 1

        src_g1 = graph.intent_graph.get_node(src)
        tgt_g1 = graph.intent_graph.get_node(tgt)
        if src_g1 and tgt_g1:
            inversion_classified += 1
            if src_g1.layer >= tgt_g1.layer:
                inversion_good += 1

    layer_score = 1.0 - min(1.0, health.layer_violation_count / max(1, total_edges))
    forbidden_violations = _forbidden_rule_violations(project_root, edges)
    forbidden_score = 1.0 - min(1.0, forbidden_violations / max(1, total_edges))
    cross_subsystem_ratio = (cross_subsystem / classified) if classified else 0.0
    cross_subsystem_score = 1.0 - _clamp01(cross_subsystem_ratio)
    dependency_inversion_ratio = (inversion_good / inversion_classified) if inversion_classified else 1.0

    dependency_correctness = (
        layer_score + forbidden_score + cross_subsystem_score + dependency_inversion_ratio
    ) / 4.0

    # Behavioral Integrity
    orphan_workflow_ratio = health.orphan_nodes / max(1, total_nodes)
    dead_execution_edges = sum(1 for src, tgt in edges if src not in node_ids or tgt not in node_ids)
    dead_execution_ratio = dead_execution_edges / max(1, total_edges)
    service_nodes = [
        n.id for n in nodes
        if n.type in ("class", "function", "method") and n.id.endswith("Service")
    ]
    unused_service_ratio = health.unused_services / max(1, len(service_nodes)) if service_nodes else 0.0
    cyclic_execution_score = 1.0 - min(1.0, health.cycle_count / 8.0)

    behavioral_integrity = (
        (1.0 - min(1.0, orphan_workflow_ratio * 4.0))
        + (1.0 - min(1.0, dead_execution_ratio * 5.0))
        + (1.0 - min(1.0, unused_service_ratio))
        + cyclic_execution_score
    ) / 4.0

    # Architecture Stability
    history = _load_json(project_root / ".codegraph" / "architecture" / "architecture_history.json", {}).get("entries", [])
    churn_penalty = 0.0
    dep_volatility_penalty = 0.0
    if len(history) >= 2:
        prev = history[-2]
        curr = history[-1]
        prev_cycles = float(prev.get("cycles_count", 0.0))
        curr_cycles = float(curr.get("cycles_count", 0.0))
        prev_coupling = float(prev.get("coupling_index", 0.0))
        curr_coupling = float(curr.get("coupling_index", 0.0))
        churn_penalty = min(1.0, abs(curr_cycles - prev_cycles) / 5.0)
        dep_volatility_penalty = min(1.0, abs(curr_coupling - prev_coupling) / 2.0)

    unstable_modules = 0
    g0_by_id = {n.id: n for n in nodes}
    for g1 in graph.intent_graph.nodes:
        g0 = g0_by_id.get(g1.id)
        if not g0:
            continue
        if g1.intent_body_hash and g1.intent_body_hash != g0.body_hash:
            unstable_modules += 1
    unstable_ratio = unstable_modules / max(1, len(graph.intent_graph.nodes))

    architecture_stability = (
        (1.0 - churn_penalty)
        + (1.0 - dep_volatility_penalty)
        + (1.0 - min(1.0, unstable_ratio))
    ) / 3.0

    # Intent Alignment
    stale_intents = unstable_modules
    missing_intents = 0
    graph1_map = {n.id: n for n in graph.intent_graph.nodes}
    for node in nodes:
        g1 = graph1_map.get(node.id)
        if g1 is None or not (g1.intent or "").strip():
            missing_intents += 1

    mismatch_ratio = stale_intents / max(1, len(graph.intent_graph.nodes))
    missing_ratio = missing_intents / max(1, total_nodes)
    layer_annotation_ratio = health.layer_violation_count / max(1, total_edges)
    drift_ratio = float(smell_index.critical_smell_count) / max(1, smell_index.smell_count)

    intent_alignment = (
        (1.0 - min(1.0, mismatch_ratio))
        + (1.0 - min(1.0, missing_ratio * 2.0))
        + (1.0 - min(1.0, layer_annotation_ratio * 2.0))
        + (1.0 - min(1.0, drift_ratio))
    ) / 4.0

    # Requested enhanced score components
    internal_edges = sum(1 for src, tgt in edges if _module_of(src) == _module_of(tgt))
    cohesion_score = internal_edges / max(1, total_edges)

    node_couplings: Dict[str, int] = {}
    for src, tgt in edges:
        node_couplings[src] = node_couplings.get(src, 0) + 1
        node_couplings[tgt] = node_couplings.get(tgt, 0) + 1
    # Use 95th percentile coupling instead of raw max to avoid outlier
    # utility functions (e.g. find_project_root) zeroing the entire metric.
    coupling_values = sorted(node_couplings.values(), reverse=True)
    if coupling_values:
        p95_idx = max(0, int(len(coupling_values) * 0.05))
        representative_coupling = coupling_values[p95_idx]
    else:
        representative_coupling = 0
    coupling_score = 1.0 - min(1.0, representative_coupling / 50.0)

    intent = load_architecture_intent(project_root)
    if intent.layers and intent.rules:
        intent_report = validate_architecture_intent(graph, intent)
        layer_integrity = intent_report.layer_integrity_score
        drift_report = compute_architecture_drift(graph, intent)
        architecture_drift = 1.0 - drift_report.drift_score
    else:
        layer_integrity = 1.0 - min(1.0, health.layer_violation_count / max(1, total_edges))
        architecture_drift = 1.0 - min(1.0, mismatch_ratio)

    cycle_penalty = 1.0 - min(1.0, health.cycle_count / 5.0)

    test_edges = sum(1 for e in graph.workflow_graph.edges if e.edge_type == "test")
    test_coverage = min(1.0, test_edges / max(1, total_nodes))
    dead_code_ratio = health.orphan_nodes / max(1, total_nodes)

    weighted_score = (
        0.25 * cohesion_score
        + 0.25 * coupling_score
        + 0.20 * layer_integrity
        + 0.20 * cycle_penalty
        + 0.10 * architecture_drift
    )

    # Pattern consistency can boost or reduce by up to ±0.05 around neutral 0.5
    weighted_score = _clamp01(weighted_score + ((pattern_consistency - 0.5) * 0.10))

    # Fitness penalties
    fitness_penalties: Dict[str, float] = {}
    if health.cycle_count > 0:
        fitness_penalties["no_dependency_cycles"] = min(0.08, health.cycle_count * 0.01)
    if p95_fan_in >= 30:
        fitness_penalties["max_fan_in"] = min(0.08, (p95_fan_in - 30) / 100.0)
    if health.layer_violation_count > 0:
        fitness_penalties["no_layer_violations"] = min(0.10, health.layer_violation_count / max(50.0, total_edges))
    if health.unused_services > 0:
        fitness_penalties["no_orphan_services"] = min(0.06, health.unused_services / 50.0)

    # Anti-gaming penalties
    anti_gaming: Dict[str, float] = {}
    baseline = _load_json(project_root / ".codegraph" / "architecture_score.json", {})
    baseline_metrics = baseline.get("metrics", {}) if isinstance(baseline, dict) else {}
    prev_coupling = float(baseline_metrics.get("coupling", 0.0))
    current_coupling = 1.0 - cross_subsystem_score
    module_count = len(module_sizes)
    prev_module_count = float((baseline.get("metadata", {}) or {}).get("module_count", module_count))
    if module_count > prev_module_count * 1.10 and current_coupling >= prev_coupling:
        anti_gaming["module_split_without_dependency_improvement"] = 0.03

    wrapper_like = sum(1 for n in nodes if "::wrapper" in n.id or n.id.endswith("::wrap"))
    if wrapper_like > 0:
        anti_gaming["excessive_wrapper_chains"] = min(0.04, wrapper_like / max(100.0, total_nodes))

    if health.unused_services > 0:
        anti_gaming["unused_services"] = min(0.03, health.unused_services / 80.0)

    duplicate_pen = _duplicate_artifact_penalty(project_root)
    if duplicate_pen > 0:
        anti_gaming["duplicate_architecture_artifacts"] = duplicate_pen

    # Objective integration: reward objective progress, penalize misses
    objective_targets = _load_objective_targets(project_root)
    objective_penalty = 0.0
    if objective_targets:
        targets = objective_targets.get("targets", {})
        max_fan_in_target = float(targets.get("max_fan_in", 30))
        max_cycles_target = float(targets.get("max_cycles", targets.get("cycle_count", 0)))
        if p95_fan_in > max_fan_in_target:
            objective_penalty += min(0.03, (p95_fan_in - max_fan_in_target) / 200.0)
        if health.cycle_count > max_cycles_target:
            objective_penalty += min(0.03, (health.cycle_count - max_cycles_target) / 20.0)

    total_penalty = sum(fitness_penalties.values()) + sum(anti_gaming.values()) + objective_penalty
    score = _clamp01(weighted_score - total_penalty)

    dimensions = {
        "coupling_score": _clamp01(coupling_score),
        "cohesion_score": _clamp01(cohesion_score),
        "layer_integrity": _clamp01(layer_integrity),
        "cycle_penalty": _clamp01(cycle_penalty),
        "architecture_drift": _clamp01(architecture_drift),
        "test_coverage": _clamp01(test_coverage),
        "dead_code_ratio": _clamp01(dead_code_ratio),
        "pattern_consistency": _clamp01(pattern_consistency),
        "structural_health": _clamp01(structural_health),
        "dependency_correctness": _clamp01(dependency_correctness),
        "behavioral_integrity": _clamp01(behavioral_integrity),
        "architecture_stability": _clamp01(architecture_stability),
        "intent_alignment": _clamp01(intent_alignment),
    }

    penalties = {
        **fitness_penalties,
        **anti_gaming,
    }
    if objective_penalty > 0:
        penalties["objective_miss_penalty"] = objective_penalty

    return MultiAxisArchitectureScore(
        score=score,
        grade=_grade(score),
        dimensions=dimensions,
        penalties=penalties,
        metadata={
            "total_nodes": total_nodes,
            "total_edges": total_edges,
            "module_count": module_count,
            "smell_count": smell_index.smell_count,
            "critical_smell_count": smell_index.critical_smell_count,
            "unused_services": health.unused_services,
            "fan_in_entropy": health.fan_in_entropy,
            "fan_out_variance": health.fan_out_variance,
            "module_complexity_variance": health.module_complexity_variance,
            "pattern_consistency": round(pattern_consistency, 4),
        },
    )
