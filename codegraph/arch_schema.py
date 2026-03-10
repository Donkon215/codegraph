"""codegraph.arch_schema — Architecture definition models.

Provides dataclass models for defining system architecture as JSON:
  - SystemArchitecture: top-level system with subsystems and constraints
  - SubsystemDef: a named architectural subsystem with components and edges
  - ArchComponent: a module or package within a subsystem
  - ArchEdge: a dependency between components or subsystems
  - ArchConstraint: a forbidden or required architectural rule

Architecture definitions live in `.codegraph/architecture/` and serve as
the source of truth for what the system *should* look like, enabling
comparison against the actual code graph.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from codegraph.logging_config import get_logger

logger = get_logger("arch_schema")

ARCHITECTURE_DIR = "architecture"
SYSTEM_FILE = "system.json"


# ── ArchComponent ──────────────────────────────────────────────────────


@dataclass
class ArchComponent:
    """A module or package within a subsystem."""

    name: str
    module: str = ""  # relative path to module/file
    functions: List[str] = field(default_factory=list)
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"name": self.name}
        if self.module:
            d["module"] = self.module
        if self.functions:
            d["functions"] = self.functions
        if self.description:
            d["description"] = self.description
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> ArchComponent:
        return cls(
            name=d["name"],
            module=d.get("module", ""),
            functions=d.get("functions", []),
            description=d.get("description", ""),
        )


# ── ArchEdge ───────────────────────────────────────────────────────────


@dataclass
class ArchEdge:
    """A dependency between components or subsystems."""

    source: str
    target: str
    edge_type: str = "dependency"  # dependency, call, data_flow

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"source": self.source, "target": self.target}
        if self.edge_type != "dependency":
            d["edge_type"] = self.edge_type
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> ArchEdge:
        if isinstance(d, list) and len(d) >= 2:
            return cls(source=d[0], target=d[1])
        return cls(
            source=d["source"],
            target=d["target"],
            edge_type=d.get("edge_type", "dependency"),
        )


# ── ArchConstraint ─────────────────────────────────────────────────────


@dataclass
class ArchConstraint:
    """A forbidden or required architectural rule."""

    constraint_type: str  # "forbidden", "required"
    source: str
    target: str
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "type": self.constraint_type,
            "source": self.source,
            "target": self.target,
        }
        if self.reason:
            d["reason"] = self.reason
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> ArchConstraint:
        return cls(
            constraint_type=d.get("type", "forbidden"),
            source=d["source"],
            target=d["target"],
            reason=d.get("reason", ""),
        )


# ── SubsystemDef ───────────────────────────────────────────────────────


@dataclass
class SubsystemDef:
    """A named architectural subsystem with components and internal edges."""

    name: str
    description: str = ""
    components: List[ArchComponent] = field(default_factory=list)
    edges: List[ArchEdge] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"name": self.name}
        if self.description:
            d["description"] = self.description
        if self.components:
            d["components"] = [c.to_dict() for c in self.components]
        if self.edges:
            d["edges"] = [e.to_dict() for e in self.edges]
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> SubsystemDef:
        components = [ArchComponent.from_dict(c) for c in d.get("components", [])]
        edges = [ArchEdge.from_dict(e) for e in d.get("edges", [])]
        return cls(
            name=d["name"],
            description=d.get("description", ""),
            components=components,
            edges=edges,
        )

    @property
    def component_names(self) -> List[str]:
        return [c.name for c in self.components]

    @property
    def module_paths(self) -> List[str]:
        return [c.module for c in self.components if c.module]

    @property
    def all_functions(self) -> List[str]:
        result: List[str] = []
        for c in self.components:
            for fn in c.functions:
                if "::" in fn:
                    result.append(fn)
                elif c.module:
                    result.append(f"{c.module}::{fn}")
                else:
                    result.append(fn)
        return result


# ── SystemArchitecture ─────────────────────────────────────────────────


@dataclass
class SystemArchitecture:
    """Top-level system architecture definition.

    Describes the intended architecture with subsystems, inter-subsystem
    edges, and architectural constraints. Serves as the blueprint that
    the code should conform to.
    """

    name: str
    description: str = ""
    subsystems: List[SubsystemDef] = field(default_factory=list)
    edges: List[ArchEdge] = field(default_factory=list)  # inter-subsystem
    constraints: List[ArchConstraint] = field(default_factory=list)
    version: int = 1

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "name": self.name,
            "version": self.version,
        }
        if self.description:
            d["description"] = self.description
        if self.subsystems:
            d["subsystems"] = [s.to_dict() for s in self.subsystems]
        if self.edges:
            d["edges"] = [e.to_dict() for e in self.edges]
        if self.constraints:
            d["constraints"] = [c.to_dict() for c in self.constraints]
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> SystemArchitecture:
        subsystems = [SubsystemDef.from_dict(s) for s in d.get("subsystems", [])]
        edges = [ArchEdge.from_dict(e) for e in d.get("edges", [])]
        constraints = [ArchConstraint.from_dict(c) for c in d.get("constraints", [])]
        return cls(
            name=d.get("name", ""),
            description=d.get("description", ""),
            subsystems=subsystems,
            edges=edges,
            constraints=constraints,
            version=d.get("version", 1),
        )

    def save(self, project_root: Path) -> Path:
        arch_dir = project_root / ".codegraph" / ARCHITECTURE_DIR
        arch_dir.mkdir(parents=True, exist_ok=True)
        path = arch_dir / SYSTEM_FILE
        path.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("Saved architecture → %s", path)
        return path

    @classmethod
    def load(cls, project_root: Path) -> Optional[SystemArchitecture]:
        path = project_root / ".codegraph" / ARCHITECTURE_DIR / SYSTEM_FILE
        if not path.exists():
            return None
        text = path.read_text(encoding="utf-8")
        return cls.from_dict(json.loads(text))

    def get_subsystem(self, name: str) -> Optional[SubsystemDef]:
        for s in self.subsystems:
            if s.name == name:
                return s
        return None

    @property
    def subsystem_names(self) -> List[str]:
        return [s.name for s in self.subsystems]

    @property
    def all_modules(self) -> List[str]:
        result: List[str] = []
        for s in self.subsystems:
            result.extend(s.module_paths)
        return result

    @property
    def all_components(self) -> List[ArchComponent]:
        result: List[ArchComponent] = []
        for s in self.subsystems:
            result.extend(s.components)
        return result

    def get_constraint_violations(
        self, actual_edges: List[tuple[str, str]]
    ) -> List[Dict[str, Any]]:
        """Check actual edges against forbidden constraints.

        Each actual edge is (source_file, target_file). Returns list of
        violations where a forbidden constraint matches.
        """
        violations: List[Dict[str, Any]] = []
        forbidden = [c for c in self.constraints if c.constraint_type == "forbidden"]
        if not forbidden:
            return violations

        # Build subsystem name -> module paths mapping
        subsystem_modules: Dict[str, set[str]] = {}
        for s in self.subsystems:
            subsystem_modules[s.name] = set(s.module_paths)

        # Also build component name -> module path
        component_modules: Dict[str, str] = {}
        for s in self.subsystems:
            for c in s.components:
                component_modules[c.name] = c.module

        for src_file, tgt_file in actual_edges:
            for constraint in forbidden:
                src_match = _matches_target(
                    src_file, constraint.source, subsystem_modules, component_modules
                )
                tgt_match = _matches_target(
                    tgt_file, constraint.target, subsystem_modules, component_modules
                )
                if src_match and tgt_match:
                    violations.append({
                        "constraint": constraint.to_dict(),
                        "source_file": src_file,
                        "target_file": tgt_file,
                    })
        return violations


def _matches_target(
    file_path: str,
    target_name: str,
    subsystem_modules: Dict[str, set[str]],
    component_modules: Dict[str, str],
) -> bool:
    """Check if a file path matches a subsystem or component name."""
    # Direct file match
    if file_path == target_name:
        return True
    # Subsystem match: file belongs to a subsystem's modules
    if target_name in subsystem_modules:
        return file_path in subsystem_modules[target_name]
    # Component match
    if target_name in component_modules:
        return file_path == component_modules[target_name]
    # Prefix match (e.g., "ui/" matches "ui/views.py")
    if target_name.endswith("/"):
        return file_path.startswith(target_name)
    return False


def init_architecture(project_root: Path, name: str = "") -> SystemArchitecture:
    """Create a template architecture definition."""
    arch = SystemArchitecture(
        name=name or project_root.name,
        description=f"Architecture definition for {name or project_root.name}",
        subsystems=[
            SubsystemDef(
                name="core",
                description="Core application logic",
                components=[
                    ArchComponent(name="main", module="", description="Entry point"),
                ],
            ),
        ],
    )
    arch.save(project_root)
    return arch
