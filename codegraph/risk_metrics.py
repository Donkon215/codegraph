"""codegraph.risk_metrics — Dependency risk scoring and structural metrics.

Computes fan-in, fan-out, centrality, coupling scores, and risk levels
for nodes in the dependency graph.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from codegraph.index import IndexStore
from codegraph.logging_config import get_logger

logger = get_logger("risk_metrics")


class RiskLevel(str, Enum):
    """Risk classification for a node."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class NodeMetrics:
    """Structural metrics for a single node."""

    node_id: str
    fan_in: int = 0  # number of callers
    fan_out: int = 0  # number of callees
    degree: int = 0  # fan_in + fan_out
    betweenness: float = 0.0  # approximate betweenness centrality
    coupling_score: float = 0.0  # normalized coupling (0-1)
    risk_level: RiskLevel = RiskLevel.LOW
    risk_score: float = 0.0  # composite 0-1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "fan_in": self.fan_in,
            "fan_out": self.fan_out,
            "degree": self.degree,
            "betweenness": round(self.betweenness, 4),
            "coupling_score": round(self.coupling_score, 4),
            "risk_level": self.risk_level.value,
            "risk_score": round(self.risk_score, 4),
        }


@dataclass
class RiskReport:
    """Aggregated risk metrics for the project."""

    total_nodes: int = 0
    node_metrics: List[NodeMetrics] = field(default_factory=list)
    critical_nodes: List[str] = field(default_factory=list)
    high_risk_nodes: List[str] = field(default_factory=list)
    avg_fan_in: float = 0.0
    avg_fan_out: float = 0.0
    max_fan_in: int = 0
    max_fan_out: int = 0
    avg_coupling: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_nodes": self.total_nodes,
            "critical_nodes": self.critical_nodes,
            "high_risk_nodes": self.high_risk_nodes,
            "avg_fan_in": round(self.avg_fan_in, 2),
            "avg_fan_out": round(self.avg_fan_out, 2),
            "max_fan_in": self.max_fan_in,
            "max_fan_out": self.max_fan_out,
            "avg_coupling": round(self.avg_coupling, 4),
            "top_risk": [m.to_dict() for m in self.node_metrics[:20]],
        }

    def format(self) -> str:
        lines = [
            f"Risk Report ({self.total_nodes} nodes)",
            f"  Avg fan-in:  {self.avg_fan_in:.1f}  (max: {self.max_fan_in})",
            f"  Avg fan-out: {self.avg_fan_out:.1f}  (max: {self.max_fan_out})",
            f"  Avg coupling: {self.avg_coupling:.3f}",
            f"  Critical: {len(self.critical_nodes)}  High: {len(self.high_risk_nodes)}",
        ]
        if self.node_metrics:
            lines.append("\nTop risk nodes:")
            for m in self.node_metrics[:10]:
                lines.append(
                    f"  [{m.risk_level.value:8s}] {m.node_id}  "
                    f"(in={m.fan_in} out={m.fan_out} risk={m.risk_score:.2f})"
                )
        return "\n".join(lines)


def compute_risk_metrics(
    index: IndexStore,
    *,
    fan_in_threshold: int = 10,
    fan_out_threshold: int = 15,
    critical_threshold: float = 0.8,
    high_threshold: float = 0.5,
) -> RiskReport:
    """Compute risk metrics for all nodes in the index."""
    report = RiskReport()

    # Get all nodes
    conn = index._get_conn()
    rows = conn.execute("SELECT id FROM nodes").fetchall()
    all_node_ids = [r[0] for r in rows]
    report.total_nodes = len(all_node_ids)

    if not all_node_ids:
        return report

    # Compute fan-in / fan-out from callers/callees tables
    fan_in_map: Dict[str, int] = defaultdict(int)
    fan_out_map: Dict[str, int] = defaultdict(int)

    caller_rows = conn.execute("SELECT node_id, caller_id FROM callers").fetchall()
    for row in caller_rows:
        fan_in_map[row[0]] += 1

    callee_rows = conn.execute("SELECT node_id, callee_id FROM callees").fetchall()
    for row in callee_rows:
        fan_out_map[row[0]] += 1

    # Build adjacency for betweenness approximation
    adj: Dict[str, List[str]] = defaultdict(list)
    for row in callee_rows:
        adj[row[0]].append(row[1])

    # Approximate betweenness centrality via sampling
    betweenness = _approximate_betweenness(all_node_ids, adj, sample_size=min(50, len(all_node_ids)))

    # Compute metrics for each node
    max_fi = max(fan_in_map.values()) if fan_in_map else 1
    max_fo = max(fan_out_map.values()) if fan_out_map else 1
    max_bet = max(betweenness.values()) if betweenness else 1.0

    metrics: List[NodeMetrics] = []
    for nid in all_node_ids:
        fi = fan_in_map.get(nid, 0)
        fo = fan_out_map.get(nid, 0)
        bet = betweenness.get(nid, 0.0)

        # Normalized coupling: weighted combo of fan-in and fan-out
        coupling = 0.0
        if max_fi > 0 or max_fo > 0:
            coupling = 0.4 * (fi / max(max_fi, 1)) + 0.6 * (fo / max(max_fo, 1))

        # Risk score: composite of fan-in, fan-out, betweenness
        norm_fi = fi / max(max_fi, 1)
        norm_fo = fo / max(max_fo, 1)
        norm_bet = bet / max(max_bet, 1e-9)
        risk_score = 0.3 * norm_fi + 0.3 * norm_fo + 0.4 * norm_bet

        # Classify risk level
        risk_level = RiskLevel.LOW
        if risk_score >= critical_threshold:
            risk_level = RiskLevel.CRITICAL
        elif risk_score >= high_threshold:
            risk_level = RiskLevel.HIGH
        elif risk_score >= 0.25:
            risk_level = RiskLevel.MEDIUM

        m = NodeMetrics(
            node_id=nid,
            fan_in=fi,
            fan_out=fo,
            degree=fi + fo,
            betweenness=bet,
            coupling_score=coupling,
            risk_level=risk_level,
            risk_score=risk_score,
        )
        metrics.append(m)

    # Sort by risk score descending
    metrics.sort(key=lambda m: m.risk_score, reverse=True)
    report.node_metrics = metrics

    # Aggregate stats
    total_fi = sum(m.fan_in for m in metrics)
    total_fo = sum(m.fan_out for m in metrics)
    report.avg_fan_in = total_fi / len(metrics) if metrics else 0
    report.avg_fan_out = total_fo / len(metrics) if metrics else 0
    report.max_fan_in = max(m.fan_in for m in metrics) if metrics else 0
    report.max_fan_out = max(m.fan_out for m in metrics) if metrics else 0
    report.avg_coupling = sum(m.coupling_score for m in metrics) / len(metrics) if metrics else 0

    report.critical_nodes = [m.node_id for m in metrics if m.risk_level == RiskLevel.CRITICAL]
    report.high_risk_nodes = [m.node_id for m in metrics if m.risk_level == RiskLevel.HIGH]

    return report


def get_node_risk(node_id: str, index: IndexStore) -> Optional[NodeMetrics]:
    """Get risk metrics for a single node."""
    report = compute_risk_metrics(index)
    for m in report.node_metrics:
        if m.node_id == node_id:
            return m
    return None


def check_dependency_limits(
    index: IndexStore,
    rules: list,
) -> List[Dict[str, Any]]:
    """Check dependency_limit rules against actual fan-in/fan-out values.

    Returns a list of violation dicts for each rule that is exceeded.
    """
    import fnmatch

    violations: List[Dict[str, Any]] = []
    if not rules:
        return violations

    conn = index._get_conn()
    all_node_ids = [r[0] for r in conn.execute("SELECT id FROM nodes").fetchall()]

    # Pre-compute fan counts
    fan_in_map: Dict[str, int] = defaultdict(int)
    fan_out_map: Dict[str, int] = defaultdict(int)
    for row in conn.execute("SELECT node_id, caller_id FROM callers").fetchall():
        fan_in_map[row[0]] += 1
    for row in conn.execute("SELECT node_id, callee_id FROM callees").fetchall():
        fan_out_map[row[0]] += 1

    for rule in rules:
        if rule.type != "dependency_limit":
            continue

        # Expand source
        source_pat = rule.source
        if source_pat:
            matched_nodes = [n for n in all_node_ids if fnmatch.fnmatch(n, source_pat)]
        elif rule.source_arch_layer:
            matched_nodes = [n for n in all_node_ids if source_pat and fnmatch.fnmatch(n, source_pat)]
            continue  # arch layer expansion needs graph1 — skip for now
        else:
            matched_nodes = all_node_ids

        for nid in matched_nodes:
            fi = fan_in_map.get(nid, 0)
            fo = fan_out_map.get(nid, 0)

            if rule.max_fan_in is not None and fi > rule.max_fan_in:
                violations.append({
                    "rule_id": rule.id,
                    "node_id": nid,
                    "metric": "fan_in",
                    "actual": fi,
                    "limit": rule.max_fan_in,
                    "reason": f"fan_in={fi} exceeds limit={rule.max_fan_in}",
                })
            if rule.max_fan_out is not None and fo > rule.max_fan_out:
                violations.append({
                    "rule_id": rule.id,
                    "node_id": nid,
                    "metric": "fan_out",
                    "actual": fo,
                    "limit": rule.max_fan_out,
                    "reason": f"fan_out={fo} exceeds limit={rule.max_fan_out}",
                })

    return violations


def _approximate_betweenness(
    nodes: List[str],
    adj: Dict[str, List[str]],
    sample_size: int = 50,
) -> Dict[str, float]:
    """Approximate betweenness centrality via BFS from sampled sources."""
    from collections import deque
    import random

    betweenness: Dict[str, float] = defaultdict(float)

    if len(nodes) <= 1:
        return dict(betweenness)

    # Sample source nodes
    sources = random.sample(nodes, min(sample_size, len(nodes)))

    for source in sources:
        # BFS from source
        visited: Dict[str, int] = {source: 0}
        predecessors: Dict[str, List[str]] = defaultdict(list)
        sigma: Dict[str, int] = defaultdict(int)
        sigma[source] = 1
        queue: deque[str] = deque([source])
        order: List[str] = []

        while queue:
            v = queue.popleft()
            order.append(v)
            for w in adj.get(v, []):
                if w not in visited:
                    visited[w] = visited[v] + 1
                    queue.append(w)
                if w in visited and visited[w] == visited[v] + 1:
                    sigma[w] += sigma[v]
                    predecessors[w].append(v)

        # Back-propagation
        delta: Dict[str, float] = defaultdict(float)
        for w in reversed(order):
            for v in predecessors[w]:
                if sigma[w] > 0:
                    delta[v] += (sigma[v] / sigma[w]) * (1 + delta[w])
            if w != source:
                betweenness[w] += delta[w]

    # Normalize
    n = len(nodes)
    if n > 2:
        scale = 1.0 / ((n - 1) * (n - 2))
        # Scale for sampling
        scale *= len(nodes) / len(sources) if sources else 1.0
        for k in betweenness:
            betweenness[k] *= scale

    return dict(betweenness)
