"""codegraph.drift_detector — Architecture drift detection.

Detects drift between declared architecture (system.json) and actual
code state (graph0 + workflow). Unlike arch_diff which compares two
architecture snapshots, drift detection compares architecture DEFINITION
against actual CODE.

Drift types:
  - Undeclared modules: code files not in any subsystem
  - Missing modules: declared modules that don't exist
  - Undeclared dependencies: actual edges not in architecture edges
  - Missing dependencies: declared edges with no actual calls
  - Component drift: functions not matching declared component
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from codegraph.arch_schema import SystemArchitecture
from codegraph.logging_config import get_logger
from codegraph.models.graph0 import Graph0

logger = get_logger("drift_detector")

DRIFT_FILE = "drift_report.json"


# ── Drift Finding ──────────────────────────────────────────────────────


@dataclass
class DriftFinding:
    """A single drift finding between architecture and code."""

    drift_type: str  # "undeclared_module", "missing_module",
    #                  "undeclared_dependency", "missing_dependency",
    #                  "component_drift"
    severity: str = "warning"  # "error", "warning", "info"
    description: str = ""
    module: str = ""
    subsystem: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "drift_type": self.drift_type,
            "severity": self.severity,
            "description": self.description,
        }
        if self.module:
            d["module"] = self.module
        if self.subsystem:
            d["subsystem"] = self.subsystem
        if self.details:
            d["details"] = self.details
        return d


# ── Drift Report ───────────────────────────────────────────────────────


@dataclass
class DriftReport:
    """Complete drift analysis report."""

    findings: List[DriftFinding] = field(default_factory=list)
    declared_module_count: int = 0
    actual_module_count: int = 0
    drift_score: float = 0.0  # 0.0=perfect, 1.0=total drift

    @property
    def has_drift(self) -> bool:
        return len(self.findings) > 0

    @property
    def error_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "warning")

    @property
    def findings_by_type(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for f in self.findings:
            counts[f.drift_type] = counts.get(f.drift_type, 0) + 1
        return counts

    def to_dict(self) -> Dict[str, Any]:
        return {
            "has_drift": self.has_drift,
            "drift_score": round(self.drift_score, 3),
            "summary": {
                "declared_modules": self.declared_module_count,
                "actual_modules": self.actual_module_count,
                "total_findings": len(self.findings),
                "errors": self.error_count,
                "warnings": self.warning_count,
                "by_type": self.findings_by_type,
            },
            "findings": [f.to_dict() for f in self.findings],
        }

    def save(self, project_root: Path) -> Path:
        path = (project_root / ".codegraph" / "architecture" / DRIFT_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("Saved drift report → %s", path)
        return path

    def format(self) -> str:
        status = "NO DRIFT" if not self.has_drift else "DRIFT DETECTED"
        lines = [f"Drift Report: {status}"]
        lines.append(f"  Drift score: {self.drift_score:.1%}")
        lines.append(f"  Declared modules: {self.declared_module_count}")
        lines.append(f"  Actual modules: {self.actual_module_count}")
        lines.append(f"  Findings: {len(self.findings)} "
                      f"({self.error_count} errors, "
                      f"{self.warning_count} warnings)")
        by_type = self.findings_by_type
        if by_type:
            lines.append("  By type: " + ", ".join(
                f"{k}={v}" for k, v in sorted(by_type.items())
            ))
        if self.findings:
            lines.append("\nFindings:")
            for f in self.findings[:30]:
                lines.append(f"  [{f.severity}] {f.description}")
            if len(self.findings) > 30:
                lines.append(f"  ... and {len(self.findings) - 30} more")
        return "\n".join(lines)


# ── Drift Detection ───────────────────────────────────────────────────


def detect_drift(
    architecture: SystemArchitecture,
    graph0: Graph0,
    actual_edges: List[Tuple[str, str]],
    *,
    project_root: Optional[Path] = None,
) -> DriftReport:
    """Detect drift between declared architecture and actual code.

    Args:
        architecture: Declared architecture from system.json.
        graph0: Actual code graph from extraction.
        actual_edges: List of (source_file, target_file) dependency edges
            from the workflow.
        project_root: Optional project root for file existence checks.
    """
    report = DriftReport()

    # Build declared module set
    declared_modules = set(architecture.all_modules)
    report.declared_module_count = len(declared_modules)

    # Build actual module set from graph0
    actual_modules: Set[str] = set()
    for node in graph0.nodes:
        if node.file:
            actual_modules.add(node.file)
    report.actual_module_count = len(actual_modules)

    # Build subsystem mappings
    mod_to_sub = _build_module_to_subsystem(architecture)
    sub_modules = _build_subsystem_modules(architecture)

    # 1. Undeclared modules — code exists but not in architecture
    _detect_undeclared_modules(
        report, actual_modules, declared_modules, mod_to_sub,
    )

    # 2. Missing modules — declared but file doesn't exist
    if project_root:
        _detect_missing_modules(
            report, declared_modules, project_root,
        )

    # 3. Undeclared dependencies — actual edges not matching architecture
    _detect_undeclared_dependencies(
        report, actual_edges, architecture, mod_to_sub,
    )

    # 4. Missing dependencies — declared subsystem edges with no actual calls
    _detect_missing_dependencies(
        report, actual_edges, architecture, sub_modules, mod_to_sub,
    )

    # Compute drift score
    total_checks = max(
        report.declared_module_count + report.actual_module_count + len(actual_edges),
        1,
    )
    report.drift_score = min(len(report.findings) / total_checks, 1.0)

    logger.info(
        "Drift detection: %d findings, score=%.1f%%",
        len(report.findings), report.drift_score * 100,
    )
    return report


# ── Internal Detectors ─────────────────────────────────────────────────


def _detect_undeclared_modules(
    report: DriftReport,
    actual_modules: Set[str],
    declared_modules: Set[str],
    mod_to_sub: Dict[str, str],
) -> None:
    """Find modules in code that aren't declared in architecture."""
    # Build known prefixes from declared modules
    known_prefixes: Set[str] = set()
    for m in declared_modules:
        if "/" in m:
            known_prefixes.add(m.rsplit("/", 1)[0] + "/")

    for mod in sorted(actual_modules):
        if mod in declared_modules or mod in mod_to_sub:
            continue
        # Skip test files and non-codegraph files
        if mod.startswith("tests/") or mod.startswith("examples/"):
            continue
        if mod.startswith("benchmarks/"):
            continue
        # Check if under a known package prefix
        if any(mod.startswith(p) for p in known_prefixes):
            continue

        report.findings.append(DriftFinding(
            drift_type="undeclared_module",
            severity="warning",
            description=f"Module {mod} exists in code but not in architecture",
            module=mod,
        ))


def _detect_missing_modules(
    report: DriftReport,
    declared_modules: Set[str],
    project_root: Path,
) -> None:
    """Find modules declared in architecture that don't exist as files."""
    for mod in sorted(declared_modules):
        if not mod:
            continue
        mod_path = project_root / mod
        # Handle both file and directory modules
        if mod.endswith("/"):
            if not mod_path.exists():
                report.findings.append(DriftFinding(
                    drift_type="missing_module",
                    severity="error",
                    description=f"Declared package {mod} does not exist",
                    module=mod,
                ))
        else:
            if not mod_path.exists():
                report.findings.append(DriftFinding(
                    drift_type="missing_module",
                    severity="error",
                    description=f"Declared module {mod} does not exist",
                    module=mod,
                ))


def _detect_undeclared_dependencies(
    report: DriftReport,
    actual_edges: List[Tuple[str, str]],
    architecture: SystemArchitecture,
    mod_to_sub: Dict[str, str],
) -> None:
    """Find cross-subsystem dependencies not in architecture edges."""
    allowed = {(e.source, e.target) for e in architecture.edges}
    # Also add reverse: some edges may be bi-directional
    seen_pairs: Set[Tuple[str, str]] = set()

    for src_file, tgt_file in actual_edges:
        src_sub = mod_to_sub.get(src_file)
        tgt_sub = mod_to_sub.get(tgt_file)
        if not src_sub or not tgt_sub or src_sub == tgt_sub:
            continue

        pair = (src_sub, tgt_sub)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)

        if pair not in allowed:
            report.findings.append(DriftFinding(
                drift_type="undeclared_dependency",
                severity="warning",
                description=(
                    f"Cross-subsystem dependency {src_sub} → {tgt_sub} "
                    f"not declared in architecture"
                ),
                module=src_file,
                subsystem=src_sub,
                details={"source_subsystem": src_sub,
                         "target_subsystem": tgt_sub},
            ))


def _detect_missing_dependencies(
    report: DriftReport,
    actual_edges: List[Tuple[str, str]],
    architecture: SystemArchitecture,
    sub_modules: Dict[str, Set[str]],
    mod_to_sub: Dict[str, str],
) -> None:
    """Find declared subsystem edges that have no actual calls."""
    # Build actual cross-subsystem pairs
    actual_pairs: Set[Tuple[str, str]] = set()
    for src_file, tgt_file in actual_edges:
        src_sub = mod_to_sub.get(src_file)
        tgt_sub = mod_to_sub.get(tgt_file)
        if src_sub and tgt_sub and src_sub != tgt_sub:
            actual_pairs.add((src_sub, tgt_sub))

    for edge in architecture.edges:
        pair = (edge.source, edge.target)
        if pair not in actual_pairs:
            # Only report if both subsystems have modules
            if (edge.source in sub_modules and sub_modules[edge.source]
                    and edge.target in sub_modules
                    and sub_modules[edge.target]):
                report.findings.append(DriftFinding(
                    drift_type="missing_dependency",
                    severity="info",
                    description=(
                        f"Declared edge {edge.source} → {edge.target} "
                        f"has no actual cross-subsystem calls"
                    ),
                    subsystem=edge.source,
                    details={"source_subsystem": edge.source,
                             "target_subsystem": edge.target},
                ))


# ── Helpers ────────────────────────────────────────────────────────────


def _build_module_to_subsystem(
    architecture: SystemArchitecture,
) -> Dict[str, str]:
    """Build module_path → subsystem_name mapping."""
    result: Dict[str, str] = {}
    for s in architecture.subsystems:
        for c in s.components:
            if c.module:
                result[c.module] = s.name
    return result


def _build_subsystem_modules(
    architecture: SystemArchitecture,
) -> Dict[str, Set[str]]:
    """Build subsystem_name → set of module paths."""
    result: Dict[str, Set[str]] = {}
    for s in architecture.subsystems:
        result[s.name] = set(s.module_paths)
    return result
