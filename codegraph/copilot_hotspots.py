"""codegraph.copilot_hotspots — HotspotReport: what needs attention most.

Fast summary of what's changing, what's broken, and what's risky.
Copilot checks this to prioritize its actions.

Extracted from copilot_context_builder.py for single-responsibility.
Re-exported from copilot_context_builder for backward compatibility.

CLI command: codegraph hotspots [--json]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from codegraph.logging_config import get_logger
from codegraph.utils.json_cache import load_json_cached

logger = get_logger("copilot_hotspots")


@dataclass
class HotspotReport:
    """Architecture hotspots -- areas that need attention most.

    Fast summary of what's changing, what's broken, and what's risky.
    Copilot checks this to prioritize its actions.
    """

    high_churn_modules: List[Dict[str, Any]] = field(default_factory=list)
    violation_hotspots: List[Dict[str, Any]] = field(default_factory=list)
    coupling_hotspots: List[Dict[str, Any]] = field(default_factory=list)
    god_modules: List[Dict[str, Any]] = field(default_factory=list)
    cycle_participants: List[str] = field(default_factory=list)
    score: float = 0.0
    grade: str = ""
    top_priority_actions: List[str] = field(default_factory=list)

    @property
    def status_line(self) -> str:
        """Single-line status for Copilot inline scanning."""
        parts = [f"score={self.score:.2f} grade={self.grade}"]
        if self.violation_hotspots:
            parts.append(f"{len(self.violation_hotspots)} violations")
        if self.cycle_participants:
            parts.append(f"{len(self.cycle_participants)} cycle nodes")
        if self.god_modules:
            parts.append(f"{len(self.god_modules)} god modules")
        if self.coupling_hotspots:
            parts.append(f"{len(self.coupling_hotspots)} coupling hotspots")
        return " | ".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status_line": self.status_line,
            "score": self.score,
            "grade": self.grade,
            "high_churn_modules": self.high_churn_modules[:15],
            "violation_hotspots": self.violation_hotspots[:15],
            "coupling_hotspots": self.coupling_hotspots[:15],
            "god_modules": self.god_modules[:10],
            "cycle_participants": self.cycle_participants[:20],
            "top_priority_actions": self.top_priority_actions[:10],
            "suggested_next_steps": _hotspot_next_steps(self),
        }

    def format(self) -> str:
        lines = [f"Architecture Hotspots  (score={self.score:.2f} grade={self.grade})"]
        if self.high_churn_modules:
            lines.append(f"\nHigh Churn ({len(self.high_churn_modules)}):")
            for m in self.high_churn_modules[:10]:
                lines.append(f"  {m.get('module', '?')}: {m.get('changes', 0)} changes")
        if self.violation_hotspots:
            lines.append(f"\nViolation Hotspots ({len(self.violation_hotspots)}):")
            for v in self.violation_hotspots[:10]:
                lines.append(f"  {v.get('node', '?')}: {v.get('type', '?')}")
        if self.coupling_hotspots:
            lines.append(f"\nCoupling Hotspots ({len(self.coupling_hotspots)}):")
            for c in self.coupling_hotspots[:10]:
                lines.append(f"  {c.get('module', '?')}: fan_out={c.get('fan_out', 0)}")
        if self.god_modules:
            lines.append(f"\nGod Modules ({len(self.god_modules)}):")
            for g in self.god_modules[:5]:
                lines.append(f"  {g.get('module', '?')}: {g.get('node_count', 0)} nodes")
        if self.cycle_participants:
            lines.append(f"\nCycle Participants ({len(self.cycle_participants)}):")
            for c in self.cycle_participants[:10]:
                lines.append(f"  {c}")
        if self.top_priority_actions:
            lines.append(f"\nPriority Actions:")
            for i, a in enumerate(self.top_priority_actions[:5], 1):
                lines.append(f"  {i}. {a}")
        return "\n".join(lines)


def build_architecture_stability(project_root: Path) -> Dict[str, Any]:
    """Compute churn metrics comparing graph0 vs graph1 intent hashes."""
    graph0_path = project_root / ".codegraph" / "graphs" / "graph0.json"
    graph1_path = project_root / ".codegraph" / "graphs" / "graph1.json"
    history_path = project_root / ".codegraph" / "architecture" / "architecture_history.json"

    changed_nodes = 0
    top_churn_modules: List[Dict[str, Any]] = []

    try:
        g0 = load_json_cached(graph0_path, {})
        g1 = load_json_cached(graph1_path, {})
        g0_nodes = {n.get("id", ""): n for n in g0.get("nodes", [])}
        g1_nodes = g1.get("nodes", [])

        churn_by_module: Dict[str, int] = {}
        for node in g1_nodes:
            node_id = node.get("id", "")
            if not node_id:
                continue
            g0_node = g0_nodes.get(node_id)
            if not g0_node:
                continue
            if (node.get("intent_body_hash", "")
                    and node.get("intent_body_hash", "") != g0_node.get("body_hash", "")):
                changed_nodes += 1
                module = node_id.split("::", 1)[0]
                churn_by_module[module] = churn_by_module.get(module, 0) + 1

        top_churn_modules = [
            {"module": module, "changes": count}
            for module, count in sorted(churn_by_module.items(), key=lambda x: -x[1])[:10]
        ]
    except Exception:
        pass

    score_trend: Dict[str, Any] = {}
    history = load_json_cached(history_path, {})
    try:
        entries = history.get("entries", [])
        if entries:
            last = entries[-1]
            prev = entries[-2] if len(entries) >= 2 else None
            score_trend = {
                "latest_cycles": last.get("cycles_count", 0),
                "latest_coupling_index": last.get("coupling_index", 0.0),
                "delta_cycles": (
                    last.get("cycles_count", 0) - prev.get("cycles_count", 0)
                ) if prev else 0,
            }
    except Exception:
        pass

    return {
        "changed_intent_nodes": changed_nodes,
        "top_churn_modules": top_churn_modules,
        "score_trend": score_trend,
    }


def hotspot_context(project_root: Path) -> HotspotReport:
    """Build a fast hotspot report showing what needs attention most.

    This is Copilot's "where should I look?" command. Returns the
    highest-priority areas based on churn, violations, coupling, and smells.
    """
    report = HotspotReport()

    advice_path = project_root / ".codegraph" / "architecture" / "architecture_advice.json"
    advice = load_json_cached(advice_path, {})
    report.score = advice.get("score", 0.0)
    report.grade = advice.get("grade", "")
    for smell in advice.get("smells", []):
        st = smell.get("smell_type", "")
        if st == "god_module":
            report.god_modules.append({
                "module": smell.get("entity", ""),
                "node_count": smell.get("node_count", 0),
                "severity": smell.get("severity", ""),
            })
        elif st == "cycle":
            report.cycle_participants.extend(smell.get("participants", []))
    report.cycle_participants = list(dict.fromkeys(report.cycle_participants))

    stability = build_architecture_stability(project_root)
    report.high_churn_modules = stability.get("top_churn_modules", [])

    wf_path = project_root / ".codegraph" / "workflow" / "workflow.json"
    wf = load_json_cached(wf_path, {})
    fan_out: Dict[str, int] = {}
    for edge in wf.get("edges", []):
        src = edge.get("source", "")
        if src:
            module = src.split("::", 1)[0]
            fan_out[module] = fan_out.get(module, 0) + 1
    sorted_coupling = sorted(fan_out.items(), key=lambda x: -x[1])
    report.coupling_hotspots = [
        {"module": m, "fan_out": fo}
        for m, fo in sorted_coupling[:15]
        if fo > 10
    ]

    violations_path = project_root / ".codegraph" / "analysis" / "violations.json"
    vdata = load_json_cached(violations_path, {})
    for v in vdata.get("violations", []):
        report.violation_hotspots.append({
            "node": v.get("node", v.get("source", "")),
            "type": v.get("type", ""),
            "message": v.get("message", ""),
        })

    if report.violation_hotspots:
        report.top_priority_actions.append(
            f"Fix {len(report.violation_hotspots)} architecture violation(s)"
        )
    if report.cycle_participants:
        report.top_priority_actions.append(
            f"Break {len(report.cycle_participants)} cycle participant(s)"
        )
    if report.god_modules:
        report.top_priority_actions.append(
            f"Split {len(report.god_modules)} god module(s)"
        )
    if report.coupling_hotspots:
        report.top_priority_actions.append(
            f"Reduce coupling in {len(report.coupling_hotspots)} high-fan-out modules"
        )
    if report.high_churn_modules:
        report.top_priority_actions.append(
            f"Stabilize {len(report.high_churn_modules)} high-churn module(s)"
        )

    return report


def _hotspot_next_steps(report: HotspotReport) -> List[str]:
    """Generate actionable next-step commands based on hotspot state."""
    steps: List[str] = []
    if report.violation_hotspots:
        top = report.violation_hotspots[0]
        node = top.get("node", "")
        steps.append(f"codegraph focus {node} --json  # zoom into top violation hotspot")
    if report.god_modules:
        top_god = report.god_modules[0].get("module", "")
        steps.append(f"codegraph scenario --components {top_god}  # explore split scenarios")
    if report.cycle_participants:
        steps.append("codegraph query \"SELECT cycles\"  # trace cycle paths")
    if report.coupling_hotspots:
        top_coupling = report.coupling_hotspots[0].get("module", "")
        steps.append(f"codegraph decide {top_coupling}  # get reasoning for coupling reduction")
    if not steps:
        steps.append("codegraph score  # architecture is healthy, track score")
    return steps
