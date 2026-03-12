"""codegraph.architecture_score — Architecture quality scoring engine.

Computes a deterministic architecture score using a weighted formula:

    score =
        0.30 * modularity
      + 0.25 * subsystem_isolation
      + 0.20 * (1 - coupling)
      + 0.15 * fanout_penalty
      + 0.10 * cycle_penalty

Individual metrics:
    modularity:          ratio of intra-module edges to total edges  [0..1]
    subsystem_isolation: ratio of intra-subsystem edges to total     [0..1]
    coupling:            ratio of cross-module edges to total         [0..1]
    fanout_penalty:      1.0 - min(1, max_fan_out / 50)              [0..1]
    cycle_penalty:       1.0 if no cycles, 0.0 if cycles > 5,
                         linear interpolation between                 [0..1]

Score output:
    score: 0.0 .. 1.0
    grade: A (≥0.90), B (≥0.80), C (≥0.65), D (≥0.50), F (<0.50)

CLI command: codegraph score
Output file: .codegraph/architecture_score.json
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from codegraph.logging_config import get_logger

logger = get_logger("architecture_score")

SCORE_FILE = "architecture_score.json"

# ── Weight configuration ──────────────────────────────────────────────
W_MODULARITY = 0.30
W_ISOLATION = 0.25
W_COUPLING = 0.20
W_FANOUT = 0.15
W_CYCLE = 0.10

GRADE_THRESHOLDS = [
    (0.90, "A"),
    (0.80, "B"),
    (0.65, "C"),
    (0.50, "D"),
    (0.0, "F"),
]


# ═══════════════════════════════════════════════════════════════════════
# Score Dataclass
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class ArchitectureScore:
    """Architecture quality score with individual metrics."""

    score: float = 0.0
    grade: str = "F"
    metrics: Dict[str, float] = field(default_factory=dict)
    subsystem_scores: Dict[str, float] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": round(self.score, 4),
            "grade": self.grade,
            "metrics": {k: round(v, 4) for k, v in self.metrics.items()},
            "subsystem_scores": {
                k: round(v, 4) for k, v in self.subsystem_scores.items()
            },
            "metadata": self.metadata,
        }

    def format(self) -> str:
        lines = [f"Architecture Score: {self.score:.2%} ({self.grade})"]
        lines.append("  Metrics:")
        lines.append(f"    Modularity:          {self.metrics.get('modularity', 0):.3f}  "
                      f"(weight {W_MODULARITY})")
        lines.append(f"    Subsystem Isolation: {self.metrics.get('subsystem_isolation', 0):.3f}  "
                      f"(weight {W_ISOLATION})")
        lines.append(f"    Coupling:            {self.metrics.get('coupling', 0):.3f}  "
                      f"(weight {W_COUPLING})")
        lines.append(f"    Fan-out Penalty:     {self.metrics.get('fanout_penalty', 0):.3f}  "
                      f"(weight {W_FANOUT})")
        lines.append(f"    Cycle Penalty:       {self.metrics.get('cycle_penalty', 0):.3f}  "
                      f"(weight {W_CYCLE})")

        if self.subsystem_scores:
            lines.append("\n  Subsystem Scores:")
            for name, sc in sorted(self.subsystem_scores.items(),
                                   key=lambda x: x[1]):
                bar = "█" * int(sc * 20) + "░" * (20 - int(sc * 20))
                lines.append(f"    {name:30s} {sc:.2%}  {bar}")

        if self.metadata:
            lines.append(f"\n  Details:")
            for k, v in self.metadata.items():
                lines.append(f"    {k}: {v}")

        return "\n".join(lines)

    def save(self, project_root: Path) -> Path:
        path = project_root / ".codegraph" / SCORE_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("Architecture score saved: %s", path)
        return path

    @classmethod
    def load(cls, project_root: Path) -> Optional["ArchitectureScore"]:
        """Load a previously saved baseline score."""
        path = project_root / ".codegraph" / SCORE_FILE
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(
                score=data.get("score", 0.0),
                grade=data.get("grade", "F"),
                metrics=data.get("metrics", {}),
                subsystem_scores=data.get("subsystem_scores", {}),
                metadata=data.get("metadata", {}),
            )
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load score: %s", exc)
            return None


# ═══════════════════════════════════════════════════════════════════════
# Score Computation
# ═══════════════════════════════════════════════════════════════════════


def _load_score_data(project_root: Path):
    """Load all graph data needed for score computation."""
    nodes, node_types = _load_nodes(project_root)
    edges = _load_edges(project_root)
    mod_to_sub = _load_subsystem_mapping(project_root)
    return nodes, node_types, edges, mod_to_sub


def _compute_raw_metrics(edges, mod_to_sub, total_edges):
    """Compute all raw architecture metrics from edges."""
    modularity = _compute_modularity(edges, total_edges)
    isolation = _compute_subsystem_isolation(edges, mod_to_sub, total_edges)
    coupling = _compute_coupling(edges, total_edges)
    max_fo = _compute_max_fan_out(edges)
    cycle_count = _count_cycles(edges)
    return modularity, isolation, coupling, max_fo, cycle_count


def compute_score(project_root: Path) -> ArchitectureScore:
    """Compute the architecture score from current graph data.

    Reads graph0.json (nodes), workflow.json (edges), system.json (subsystems).
    Returns an :class:`ArchitectureScore` with component metrics.
    """
    nodes, node_types, edges, mod_to_sub = _load_score_data(project_root)
    total_edges = len(edges)

    modularity, isolation, coupling, max_fo, cycle_count = _compute_raw_metrics(
        edges, mod_to_sub, total_edges
    )

    # Transform to 0..1 scale
    fanout_penalty = max(0.0, 1.0 - min(1.0, max_fo / 50.0))
    if cycle_count == 0:
        cycle_penalty_val = 1.0
    elif cycle_count >= 5:
        cycle_penalty_val = 0.0
    else:
        cycle_penalty_val = 1.0 - (cycle_count / 5.0)

    coupling_term = max(0.0, 1.0 - coupling)

    # Weighted score
    score = (
        W_MODULARITY * modularity
        + W_ISOLATION * isolation
        + W_COUPLING * coupling_term
        + W_FANOUT * fanout_penalty
        + W_CYCLE * cycle_penalty_val
    )
    score = max(0.0, min(1.0, score))

    grade = _score_to_grade(score)

    # Per-subsystem scores
    sub_scores = _compute_subsystem_scores(edges, mod_to_sub)

    return ArchitectureScore(
        score=score,
        grade=grade,
        metrics={
            "modularity": modularity,
            "subsystem_isolation": isolation,
            "coupling": coupling,
            "fanout_penalty": fanout_penalty,
            "cycle_penalty": cycle_penalty_val,
            "max_fan_out": float(max_fo),
            "cycle_count": float(cycle_count),
        },
        subsystem_scores=sub_scores,
        metadata={
            "total_nodes": len(nodes),
            "total_edges": total_edges,
            "subsystem_count": len(set(mod_to_sub.values())),
        },
    )


def compare_scores(
    baseline: ArchitectureScore,
    current: ArchitectureScore,
) -> Dict[str, Any]:
    """Compare two scores and return the diff."""
    delta = current.score - baseline.score
    metric_deltas = {}
    for key in baseline.metrics:
        old_val = baseline.metrics.get(key, 0.0)
        new_val = current.metrics.get(key, 0.0)
        metric_deltas[key] = round(new_val - old_val, 4)

    improved = delta >= 0
    no_regression = delta >= -0.05  # Allow up to 5% regression

    return {
        "baseline_score": round(baseline.score, 4),
        "current_score": round(current.score, 4),
        "delta": round(delta, 4),
        "improved": improved,
        "no_regression": no_regression,
        "merge_allowed": no_regression,
        "metric_deltas": metric_deltas,
        "baseline_grade": baseline.grade,
        "current_grade": current.grade,
    }


# ═══════════════════════════════════════════════════════════════════════
# Private Helpers
# ═══════════════════════════════════════════════════════════════════════


def _score_to_grade(score: float) -> str:
    for threshold, grade in GRADE_THRESHOLDS:
        if score >= threshold:
            return grade
    return "F"


def _load_nodes(
    project_root: Path,
) -> tuple[Set[str], Dict[str, str]]:
    """Load node IDs and their types from graph0."""
    path = project_root / ".codegraph" / "graphs" / "graph0.json"
    nodes: Set[str] = set()
    types: Dict[str, str] = {}
    if not path.exists():
        return nodes, types
    try:
        g0 = json.loads(path.read_text(encoding="utf-8"))
        for node in g0.get("nodes", []):
            nid = node.get("id", "")
            if nid:
                nodes.add(nid)
                types[nid] = node.get("type", "")
    except (json.JSONDecodeError, OSError):
        pass
    return nodes, types


def _load_edges(
    project_root: Path,
) -> List[tuple[str, str]]:
    """Load edges from workflow.json."""
    path = project_root / ".codegraph" / "workflow" / "workflow.json"
    if not path.exists():
        return []
    try:
        wf = json.loads(path.read_text(encoding="utf-8"))
        return [
            (e["source"], e["target"])
            for e in wf.get("edges", [])
            if e.get("source") and e.get("target")
        ]
    except (json.JSONDecodeError, OSError):
        return []


def _load_subsystem_mapping(
    project_root: Path,
) -> Dict[str, str]:
    """Load module → subsystem mapping from system.json."""
    path = project_root / ".codegraph" / "architecture" / "system.json"
    if not path.exists():
        return {}
    try:
        system = json.loads(path.read_text(encoding="utf-8"))
        mapping: Dict[str, str] = {}
        for sub in system.get("subsystems", []):
            sub_name = sub["name"]
            for comp in sub.get("components", []):
                mod = comp.get("module", "")
                if mod:
                    mapping[mod] = sub_name
        return mapping
    except (json.JSONDecodeError, OSError):
        return {}


def _node_module(node_id: str) -> str:
    """Extract module from node ID."""
    return node_id.split("::")[0] if "::" in node_id else node_id


def _compute_modularity(
    edges: List[tuple[str, str]],
    total: int,
) -> float:
    """Ratio of intra-module edges to total edges."""
    if total == 0:
        return 1.0
    intra = sum(
        1 for src, tgt in edges
        if _node_module(src) == _node_module(tgt)
    )
    return intra / total


def _compute_coupling(
    edges: List[tuple[str, str]],
    total: int,
) -> float:
    """Ratio of cross-module edges to total edges."""
    if total == 0:
        return 0.0
    cross = sum(
        1 for src, tgt in edges
        if _node_module(src) != _node_module(tgt)
    )
    return cross / total


def _compute_subsystem_isolation(
    edges: List[tuple[str, str]],
    mod_to_sub: Dict[str, str],
    total: int,
) -> float:
    """Ratio of intra-subsystem edges to classified edges."""
    if total == 0 or not mod_to_sub:
        return 1.0

    intra = 0
    classified = 0
    for src, tgt in edges:
        src_mod = _node_module(src)
        tgt_mod = _node_module(tgt)
        src_sub = mod_to_sub.get(src_mod, "")
        tgt_sub = mod_to_sub.get(tgt_mod, "")
        if src_sub and tgt_sub:
            classified += 1
            if src_sub == tgt_sub:
                intra += 1

    return intra / classified if classified > 0 else 1.0


def _compute_max_fan_out(edges: List[tuple[str, str]]) -> int:
    """Find the maximum outgoing edge count for any node."""
    fan_out: Dict[str, int] = {}
    for src, _ in edges:
        fan_out[src] = fan_out.get(src, 0) + 1
    return max(fan_out.values()) if fan_out else 0


def _count_cycles(edges: List[tuple[str, str]]) -> int:
    """Count cycles by detecting strongly connected components > size 1."""
    adj: Dict[str, Set[str]] = {}
    for src, tgt in edges:
        mod_src = _node_module(src)
        mod_tgt = _node_module(tgt)
        if mod_src != mod_tgt:
            adj.setdefault(mod_src, set()).add(mod_tgt)

    # Tarjan SCC
    index_counter = [0]
    stack: List[str] = []
    on_stack: Set[str] = set()
    indices: Dict[str, int] = {}
    lowlinks: Dict[str, int] = {}
    cycles = 0

    all_nodes = set(adj.keys())
    for targets in adj.values():
        all_nodes.update(targets)

    def strongconnect(v: str) -> None:
        nonlocal cycles
        indices[v] = index_counter[0]
        lowlinks[v] = index_counter[0]
        index_counter[0] += 1
        stack.append(v)
        on_stack.add(v)

        for w in adj.get(v, set()):
            if w not in indices:
                strongconnect(w)
                lowlinks[v] = min(lowlinks[v], lowlinks[w])
            elif w in on_stack:
                lowlinks[v] = min(lowlinks[v], indices[w])

        if lowlinks[v] == indices[v]:
            scc: List[str] = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                scc.append(w)
                if w == v:
                    break
            if len(scc) > 1:
                cycles += 1

    for node in all_nodes:
        if node not in indices:
            strongconnect(node)

    return cycles


def _compute_subsystem_scores(
    edges: List[tuple[str, str]],
    mod_to_sub: Dict[str, str],
) -> Dict[str, float]:
    """Compute per-subsystem isolation scores."""
    if not mod_to_sub:
        return {}

    sub_intra: Dict[str, int] = {}
    sub_total: Dict[str, int] = {}

    for src, tgt in edges:
        src_mod = _node_module(src)
        tgt_mod = _node_module(tgt)
        src_sub = mod_to_sub.get(src_mod, "")
        tgt_sub = mod_to_sub.get(tgt_mod, "")

        if src_sub:
            sub_total[src_sub] = sub_total.get(src_sub, 0) + 1
            if src_sub == tgt_sub:
                sub_intra[src_sub] = sub_intra.get(src_sub, 0) + 1

    scores: Dict[str, float] = {}
    for sub_name in set(mod_to_sub.values()):
        total = sub_total.get(sub_name, 0)
        intra = sub_intra.get(sub_name, 0)
        scores[sub_name] = intra / total if total > 0 else 1.0

    return scores
