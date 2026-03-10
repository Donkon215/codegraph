"""codegraph.architecture_lock — Architecture boundary enforcement.

Prevents architecture drift by blocking changes that violate the
declared architecture. Checks module placement, dependency rules,
subsystem boundaries, and layer constraints.

The lock is consulted during:
  - Plan validation (before implementation)
  - Branch validation (before merge)
  - Build analysis (detecting existing violations)

Violations are reported as LockViolation objects with actionable
descriptions for Copilot to fix.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from codegraph.arch_schema import SystemArchitecture
from codegraph.logging_config import get_logger

logger = get_logger("architecture_lock")


# ── Lock Violation ─────────────────────────────────────────────────────


@dataclass
class LockViolation:
    """A detected architecture lock violation."""

    violation_type: str  # "undeclared_module", "forbidden_dependency",
    #                      "boundary_violation", "constraint_violation"
    severity: str = "error"  # "error", "warning"
    description: str = ""
    module: str = ""
    subsystem: str = ""
    suggestion: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "type": self.violation_type,
            "severity": self.severity,
            "description": self.description,
        }
        if self.module:
            d["module"] = self.module
        if self.subsystem:
            d["subsystem"] = self.subsystem
        if self.suggestion:
            d["suggestion"] = self.suggestion
        return d


@dataclass
class LockReport:
    """Report from architecture lock checking."""

    violations: List[LockViolation] = field(default_factory=list)
    checked_modules: int = 0
    checked_edges: int = 0

    @property
    def is_locked(self) -> bool:
        """True if no error-level violations found."""
        return not any(v.severity == "error" for v in self.violations)

    @property
    def error_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "warning")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "locked": self.is_locked,
            "checked_modules": self.checked_modules,
            "checked_edges": self.checked_edges,
            "errors": self.error_count,
            "warnings": self.warning_count,
            "violations": [v.to_dict() for v in self.violations],
        }

    def format(self) -> str:
        status = "LOCKED ✓" if self.is_locked else "UNLOCKED ✗"
        lines = [f"Architecture Lock: {status}"]
        lines.append(f"  Checked: {self.checked_modules} modules, "
                      f"{self.checked_edges} edges")
        lines.append(f"  Errors: {self.error_count}")
        lines.append(f"  Warnings: {self.warning_count}")
        if self.violations:
            lines.append("\nViolations:")
            for v in self.violations:
                lines.append(f"  [{v.severity}] {v.description}")
                if v.suggestion:
                    lines.append(f"         → {v.suggestion}")
        return "\n".join(lines)


# ── Lock Checking ──────────────────────────────────────────────────────


def check_lock(
    architecture: SystemArchitecture,
    actual_modules: List[str],
    actual_edges: List[Tuple[str, str]],
    *,
    strict: bool = False,
) -> LockReport:
    """Check architecture lock against actual code state.

    Args:
        architecture: Declared architecture definition.
        actual_modules: List of actual module file paths found in codebase.
        actual_edges: List of (source_file, target_file) dependency edges.
        strict: If True, undeclared modules are errors; otherwise warnings.
    """
    report = LockReport()

    # Build architecture module set
    declared_modules = set(architecture.all_modules)
    subsystem_modules = _build_subsystem_module_map(architecture)
    module_to_subsystem = _build_reverse_module_map(architecture)

    # 1. Check for undeclared modules
    _check_undeclared_modules(
        report, actual_modules, declared_modules,
        module_to_subsystem, strict,
    )

    # 2. Check forbidden dependencies
    _check_forbidden_dependencies(
        report, actual_edges, architecture, subsystem_modules,
        module_to_subsystem,
    )

    # 3. Check allowed inter-subsystem edges
    _check_subsystem_boundaries(
        report, actual_edges, architecture, subsystem_modules,
        module_to_subsystem,
    )

    report.checked_modules = len(actual_modules)
    report.checked_edges = len(actual_edges)

    logger.info(
        "Lock check: %s (%d errors, %d warnings)",
        "LOCKED" if report.is_locked else "UNLOCKED",
        report.error_count, report.warning_count,
    )
    return report


def check_module_placement(
    module_path: str,
    architecture: SystemArchitecture,
) -> Optional[LockViolation]:
    """Check if a module is declared in the architecture.

    Returns a LockViolation if the module is not in any subsystem,
    or None if it's properly declared.
    """
    declared = set(architecture.all_modules)
    if module_path in declared:
        return None
    # Check if it falls under a known prefix
    for sub in architecture.subsystems:
        for comp in sub.components:
            if comp.module and module_path.startswith(
                comp.module.rsplit("/", 1)[0] + "/"
            ):
                return None  # Under a known package
    return LockViolation(
        violation_type="undeclared_module",
        severity="warning",
        description=f"Module {module_path} is not declared in architecture",
        module=module_path,
        suggestion="Add this module to a subsystem in system.json",
    )


def check_dependency_allowed(
    source_module: str,
    target_module: str,
    architecture: SystemArchitecture,
) -> Optional[LockViolation]:
    """Check if a dependency between two modules is allowed.

    Returns a LockViolation if the dependency is forbidden,
    or None if it's allowed.
    """
    module_to_sub = _build_reverse_module_map(architecture)
    source_sub = module_to_sub.get(source_module)
    target_sub = module_to_sub.get(target_module)

    if not source_sub or not target_sub:
        return None  # Can't check undeclared modules

    if source_sub == target_sub:
        return None  # Intra-subsystem always allowed

    # Check forbidden constraints
    for constraint in architecture.constraints:
        if constraint.constraint_type == "forbidden":
            if constraint.source == source_sub and constraint.target == target_sub:
                return LockViolation(
                    violation_type="forbidden_dependency",
                    severity="error",
                    description=(
                        f"Forbidden: {source_module} ({source_sub}) → "
                        f"{target_module} ({target_sub}): "
                        f"{constraint.reason}"
                    ),
                    module=source_module,
                    subsystem=source_sub,
                    suggestion=(
                        f"Remove the import of {target_module} from "
                        f"{source_module} or restructure the dependency"
                    ),
                )

    # Check if inter-subsystem edge is declared
    allowed_edges = {(e.source, e.target) for e in architecture.edges}
    if (source_sub, target_sub) not in allowed_edges:
        return LockViolation(
            violation_type="boundary_violation",
            severity="warning",
            description=(
                f"Undeclared cross-subsystem: {source_module} ({source_sub}) → "
                f"{target_module} ({target_sub})"
            ),
            module=source_module,
            subsystem=source_sub,
            suggestion=(
                f"Add edge {source_sub} → {target_sub} to system.json "
                f"or move the module to the correct subsystem"
            ),
        )

    return None


# ── Internal Helpers ───────────────────────────────────────────────────


def _build_subsystem_module_map(
    architecture: SystemArchitecture,
) -> Dict[str, Set[str]]:
    """Build subsystem_name → set of module paths."""
    result: Dict[str, Set[str]] = {}
    for s in architecture.subsystems:
        result[s.name] = set(s.module_paths)
    return result


def _build_reverse_module_map(
    architecture: SystemArchitecture,
) -> Dict[str, str]:
    """Build module_path → subsystem_name mapping."""
    result: Dict[str, str] = {}
    for s in architecture.subsystems:
        for c in s.components:
            if c.module:
                result[c.module] = s.name
    return result


def _check_undeclared_modules(
    report: LockReport,
    actual_modules: List[str],
    declared_modules: Set[str],
    module_to_subsystem: Dict[str, str],
    strict: bool,
) -> None:
    """Check for modules not declared in architecture."""
    # Build prefix set from declared module directories
    declared_prefixes: Set[str] = set()
    for m in declared_modules:
        if "/" in m:
            declared_prefixes.add(m.rsplit("/", 1)[0] + "/")

    for mod in actual_modules:
        if mod in declared_modules:
            continue
        if mod in module_to_subsystem:
            continue
        # Check if under a known prefix (package)
        under_known = any(
            mod.startswith(prefix) for prefix in declared_prefixes
        )
        if under_known:
            continue

        report.violations.append(LockViolation(
            violation_type="undeclared_module",
            severity="error" if strict else "warning",
            description=f"Module {mod} is not declared in architecture",
            module=mod,
            suggestion="Add this module to a subsystem in system.json",
        ))


def _check_forbidden_dependencies(
    report: LockReport,
    actual_edges: List[Tuple[str, str]],
    architecture: SystemArchitecture,
    subsystem_modules: Dict[str, Set[str]],
    module_to_subsystem: Dict[str, str],
) -> None:
    """Check for forbidden dependency violations."""
    forbidden_pairs: List[Tuple[str, str, str]] = []
    for c in architecture.constraints:
        if c.constraint_type == "forbidden":
            forbidden_pairs.append((c.source, c.target, c.reason))

    for src_file, tgt_file in actual_edges:
        src_sub = module_to_subsystem.get(src_file)
        tgt_sub = module_to_subsystem.get(tgt_file)
        if not src_sub or not tgt_sub:
            continue
        if src_sub == tgt_sub:
            continue
        for f_src, f_tgt, reason in forbidden_pairs:
            if src_sub == f_src and tgt_sub == f_tgt:
                report.violations.append(LockViolation(
                    violation_type="forbidden_dependency",
                    severity="error",
                    description=(
                        f"Forbidden: {src_file} ({src_sub}) → "
                        f"{tgt_file} ({tgt_sub}): {reason}"
                    ),
                    module=src_file,
                    subsystem=src_sub,
                    suggestion=(
                        f"Remove dependency from {src_file} to {tgt_file}"
                    ),
                ))


def _check_subsystem_boundaries(
    report: LockReport,
    actual_edges: List[Tuple[str, str]],
    architecture: SystemArchitecture,
    subsystem_modules: Dict[str, Set[str]],
    module_to_subsystem: Dict[str, str],
) -> None:
    """Check for undeclared cross-subsystem dependencies."""
    allowed_cross = {(e.source, e.target) for e in architecture.edges}
    seen_pairs: Set[Tuple[str, str]] = set()

    for src_file, tgt_file in actual_edges:
        src_sub = module_to_subsystem.get(src_file)
        tgt_sub = module_to_subsystem.get(tgt_file)
        if not src_sub or not tgt_sub:
            continue
        if src_sub == tgt_sub:
            continue
        pair = (src_sub, tgt_sub)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)

        if pair not in allowed_cross:
            report.violations.append(LockViolation(
                violation_type="boundary_violation",
                severity="warning",
                description=(
                    f"Undeclared cross-subsystem edge: "
                    f"{src_sub} → {tgt_sub} "
                    f"(via {src_file} → {tgt_file})"
                ),
                module=src_file,
                subsystem=src_sub,
                suggestion=(
                    f"Add edge {src_sub} → {tgt_sub} in system.json "
                    f"or restructure the dependency"
                ),
            ))
