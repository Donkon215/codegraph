"""codegraph.arch_health — Architecture health scoring engine.

Aggregates risk metrics, cycle detection, coupling analysis, and
subsystem cohesion into a unified architecture health report.
Tracks health over time and detects architecture degradation.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from codegraph.index import IndexStore
from codegraph.logging_config import get_logger
from codegraph.models.graph0 import Graph0
from codegraph.models.graph1 import Graph1
from codegraph.refactor import detect_cycles
from codegraph.risk_metrics import RiskLevel, compute_risk_metrics
from codegraph.subsystem import detect_subsystems

logger = get_logger("arch_health")


@dataclass
class ModuleHealth:
    """Health assessment for a single module (file)."""

    file: str
    node_count: int = 0
    avg_risk: float = 0.0
    max_risk: float = 0.0
    fan_in_total: int = 0
    fan_out_total: int = 0
    in_cycle: bool = False
    health_score: float = 1.0  # 0.0 = terrible, 1.0 = perfect
    issues: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file": self.file,
            "node_count": self.node_count,
            "health_score": round(self.health_score, 3),
            "avg_risk": round(self.avg_risk, 3),
            "max_risk": round(self.max_risk, 3),
            "fan_in_total": self.fan_in_total,
            "fan_out_total": self.fan_out_total,
            "in_cycle": self.in_cycle,
            "issues": self.issues,
        }


@dataclass
class ArchHealthReport:
    """Comprehensive architecture health report."""

    overall_score: float = 1.0  # 0-1 composite
    total_nodes: int = 0
    total_edges: int = 0
    total_files: int = 0
    cycle_count: int = 0
    avg_cohesion: float = 0.0
    critical_nodes: int = 0
    high_risk_nodes: int = 0
    module_health: List[ModuleHealth] = field(default_factory=list)
    architecture_smells: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall_score": round(self.overall_score, 3),
            "grade": self._grade(),
            "total_nodes": self.total_nodes,
            "total_edges": self.total_edges,
            "total_files": self.total_files,
            "cycle_count": self.cycle_count,
            "avg_cohesion": round(self.avg_cohesion, 3),
            "critical_nodes": self.critical_nodes,
            "high_risk_nodes": self.high_risk_nodes,
            "architecture_smells": self.architecture_smells,
            "recommendations": self.recommendations,
            "worst_modules": [m.to_dict() for m in self.module_health[:10]],
        }

    def _grade(self) -> str:
        if self.overall_score >= 0.9:
            return "A"
        if self.overall_score >= 0.8:
            return "B"
        if self.overall_score >= 0.7:
            return "C"
        if self.overall_score >= 0.5:
            return "D"
        return "F"

    def format(self) -> str:
        lines = [
            f"Architecture Health: {self._grade()} ({self.overall_score:.1%})",
            f"  Nodes: {self.total_nodes}  Edges: {self.total_edges}  Files: {self.total_files}",
            f"  Cycles: {self.cycle_count}  Critical: {self.critical_nodes}  High-risk: {self.high_risk_nodes}",
            f"  Avg cohesion: {self.avg_cohesion:.2f}",
        ]
        if self.architecture_smells:
            lines.append(f"\nArchitecture smells ({len(self.architecture_smells)}):")
            for smell in self.architecture_smells:
                lines.append(f"  - {smell}")
        if self.recommendations:
            lines.append(f"\nRecommendations:")
            for rec in self.recommendations:
                lines.append(f"  - {rec}")
        if self.module_health:
            lines.append(f"\nWorst modules:")
            for m in self.module_health[:10]:
                lines.append(
                    f"  {m.file}: score={m.health_score:.2f} "
                    f"(risk={m.avg_risk:.2f}, nodes={m.node_count})"
                )
                for issue in m.issues[:2]:
                    lines.append(f"    - {issue}")
        return "\n".join(lines)


def compute_health(
    graph0: Graph0,
    index: IndexStore,
    *,
    cycle_penalty: float = 0.15,
    critical_penalty: float = 0.10,
    coupling_penalty: float = 0.05,
) -> ArchHealthReport:
    """Compute comprehensive architecture health score.

    The overall score starts at 1.0 and is reduced by penalties:
    - Cycles in the dependency graph
    - Critical/high-risk nodes
    - Low subsystem cohesion
    - God modules
    - High coupling between subsystems
    """
    report = ArchHealthReport()
    report.total_nodes = len(graph0.nodes)
    report.total_files = len(set(n.file for n in graph0.nodes))

    # Count edges
    conn = index._conn
    edge_count = conn.execute("SELECT COUNT(*) FROM callees").fetchone()[0]
    report.total_edges = edge_count

    # 1. Risk metrics
    risk = compute_risk_metrics(index)
    report.critical_nodes = len(risk.critical_nodes)
    report.high_risk_nodes = len(risk.high_risk_nodes)

    # 2. Cycles
    cycles = detect_cycles(index)
    report.cycle_count = len(cycles)

    # Build set of nodes in cycles for module health
    cycle_nodes: set = set()
    for c in cycles:
        cycle_nodes.update(c.nodes)

    # 3. Subsystem cohesion
    sub_report = detect_subsystems(graph0, index)
    if sub_report.subsystems:
        report.avg_cohesion = sum(s.cohesion for s in sub_report.subsystems) / len(sub_report.subsystems)

    # 4. Per-module health
    file_nodes: Dict[str, List[str]] = defaultdict(list)
    for node in graph0.nodes:
        file_nodes[node.file].append(node.id)

    risk_map = {m.node_id: m for m in risk.node_metrics}
    modules: List[ModuleHealth] = []

    for filepath, node_ids in file_nodes.items():
        mh = ModuleHealth(file=filepath, node_count=len(node_ids))
        risks = [risk_map[nid].risk_score for nid in node_ids if nid in risk_map]
        if risks:
            mh.avg_risk = sum(risks) / len(risks)
            mh.max_risk = max(risks)
        fan_ins = [risk_map[nid].fan_in for nid in node_ids if nid in risk_map]
        fan_outs = [risk_map[nid].fan_out for nid in node_ids if nid in risk_map]
        mh.fan_in_total = sum(fan_ins)
        mh.fan_out_total = sum(fan_outs)
        mh.in_cycle = any(nid in cycle_nodes for nid in node_ids)

        # Compute module health score
        score = 1.0
        if mh.in_cycle:
            score -= 0.3
            mh.issues.append("Contains nodes in dependency cycles")
        if mh.max_risk >= 0.8:
            score -= 0.2
            mh.issues.append(f"Has critical-risk node (max_risk={mh.max_risk:.2f})")
        if mh.node_count > 30:
            score -= 0.15
            mh.issues.append(f"God module ({mh.node_count} nodes)")
        if mh.fan_out_total > 50:
            score -= 0.1
            mh.issues.append(f"High total fan-out ({mh.fan_out_total})")
        mh.health_score = max(0.0, score)
        modules.append(mh)

    # Sort by health score ascending (worst first)
    modules.sort(key=lambda m: m.health_score)
    report.module_health = modules

    # 5. Architecture smells
    if report.cycle_count > 0:
        total_cycle_nodes = len(cycle_nodes)
        report.architecture_smells.append(
            f"{report.cycle_count} dependency cycle(s) involving {total_cycle_nodes} nodes"
        )
    if report.critical_nodes > 0:
        report.architecture_smells.append(
            f"{report.critical_nodes} critical-risk node(s) with high centrality"
        )
    god_modules = [m for m in modules if m.node_count > 30]
    if god_modules:
        report.architecture_smells.append(
            f"{len(god_modules)} god module(s) with >30 nodes"
        )
    low_cohesion = [s for s in sub_report.subsystems if s.cohesion < 0.3]
    if low_cohesion:
        report.architecture_smells.append(
            f"{len(low_cohesion)} subsystem(s) with low cohesion (<30%)"
        )

    # 6. Recommendations
    if report.cycle_count > 0:
        report.recommendations.append("Break dependency cycles by introducing interfaces or mediators")
    if god_modules:
        for gm in god_modules[:3]:
            report.recommendations.append(f"Split {gm.file} into smaller, focused modules")
    if report.critical_nodes > 5:
        report.recommendations.append("Reduce centrality of critical nodes by distributing responsibilities")
    if report.avg_cohesion < 0.5 and sub_report.subsystems:
        report.recommendations.append("Improve subsystem cohesion by reducing cross-boundary dependencies")

    # 7. Compute overall score
    score = 1.0
    if report.cycle_count > 0:
        score -= min(cycle_penalty * report.cycle_count, 0.3)
    if report.critical_nodes > 0:
        score -= min(critical_penalty * report.critical_nodes, 0.2)
    if god_modules:
        score -= min(0.05 * len(god_modules), 0.15)
    if sub_report.couplings:
        high_coupling = [c for c in sub_report.couplings if c.coupling_strength > 0.1]
        score -= min(coupling_penalty * len(high_coupling), 0.15)
    if report.avg_cohesion < 0.5 and sub_report.subsystems:
        score -= 0.1
    report.overall_score = max(0.0, score)

    return report


def save_health_report(report: ArchHealthReport, project_root: Path) -> Path:
    """Save health report to .codegraph/health/."""
    health_dir = project_root / ".codegraph" / "health"
    health_dir.mkdir(parents=True, exist_ok=True)
    path = health_dir / "health_report.json"
    path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    return path


def load_health_history(project_root: Path) -> List[Dict[str, Any]]:
    """Load previous health reports for trend analysis."""
    history_path = project_root / ".codegraph" / "health" / "history.json"
    if not history_path.exists():
        return []
    return json.loads(history_path.read_text(encoding="utf-8"))


def append_health_history(report: ArchHealthReport, project_root: Path) -> None:
    """Append current health snapshot to history."""
    from codegraph.utils.formatting import iso_now

    history = load_health_history(project_root)
    history.append({
        "timestamp": iso_now(),
        "overall_score": round(report.overall_score, 3),
        "grade": report._grade(),
        "nodes": report.total_nodes,
        "edges": report.total_edges,
        "cycles": report.cycle_count,
        "critical": report.critical_nodes,
    })
    # Keep last 100 entries
    history = history[-100:]
    health_dir = project_root / ".codegraph" / "health"
    health_dir.mkdir(parents=True, exist_ok=True)
    path = health_dir / "history.json"
    path.write_text(json.dumps(history, indent=2), encoding="utf-8")
