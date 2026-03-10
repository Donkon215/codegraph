"""codegraph.subsystem_lifecycle — Subsystem lifecycle management.

Operations for evolving subsystem boundaries:
  - create_subsystem: define a new subsystem in architecture
  - split_subsystem: split a subsystem into two
  - merge_subsystems: merge two subsystems
  - move_component: move a component between subsystems
  - generate_subsystem_files: split system.json into per-subsystem files
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from codegraph.arch_schema import (
    ArchComponent,
    ArchConstraint,
    ArchEdge,
    SubsystemDef,
    SystemArchitecture,
)
from codegraph.logging_config import get_logger

logger = get_logger("subsystem_lifecycle")

SUBSYSTEMS_DIR = "subsystems"


@dataclass
class SubsystemChange:
    """A planned subsystem lifecycle change."""

    operation: str  # create, split, merge, move_component
    subsystem: str = ""
    target_subsystem: str = ""
    component: str = ""
    reason: str = ""
    new_components: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "operation": self.operation,
            "reason": self.reason,
        }
        if self.subsystem:
            d["subsystem"] = self.subsystem
        if self.target_subsystem:
            d["target_subsystem"] = self.target_subsystem
        if self.component:
            d["component"] = self.component
        if self.new_components:
            d["new_components"] = self.new_components
        return d


@dataclass
class SubsystemFile:
    """A per-subsystem architecture file."""

    name: str
    description: str = ""
    components: List[Dict[str, Any]] = field(default_factory=list)
    edges: List[List[str]] = field(default_factory=list)
    rules: List[Dict[str, Any]] = field(default_factory=list)
    intent: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"name": self.name}
        if self.description:
            d["description"] = self.description
        if self.intent:
            d["intent"] = self.intent
        if self.components:
            d["components"] = self.components
        if self.edges:
            d["edges"] = self.edges
        if self.rules:
            d["rules"] = self.rules
        return d


# ── Subsystem Operations ──────────────────────────────────────────────


def create_subsystem(
    arch: SystemArchitecture,
    name: str,
    description: str = "",
    components: Optional[List[ArchComponent]] = None,
) -> SubsystemDef:
    """Create a new subsystem in the architecture."""
    existing = arch.get_subsystem(name)
    if existing:
        raise ValueError(f"Subsystem already exists: {name}")

    subsystem = SubsystemDef(
        name=name,
        description=description,
        components=components or [],
    )
    arch.subsystems.append(subsystem)
    logger.info("Created subsystem: %s", name)
    return subsystem


def split_subsystem(
    arch: SystemArchitecture,
    source_name: str,
    new_name: str,
    component_names: List[str],
    new_description: str = "",
) -> Tuple[SubsystemDef, SubsystemDef]:
    """Split a subsystem by moving components to a new subsystem.

    Args:
        source_name: Subsystem to split from.
        new_name: Name for the new subsystem.
        component_names: Components to move to the new subsystem.

    Returns:
        Tuple of (modified source, new subsystem).
    """
    source = arch.get_subsystem(source_name)
    if not source:
        raise ValueError(f"Subsystem not found: {source_name}")
    if arch.get_subsystem(new_name):
        raise ValueError(f"Subsystem already exists: {new_name}")

    # Separate components
    move_set = set(component_names)
    moving = [c for c in source.components if c.name in move_set]
    staying = [c for c in source.components if c.name not in move_set]

    if not moving:
        raise ValueError(f"No matching components found: {component_names}")

    # Update source
    source.components = staying

    # Create new subsystem with moved components
    new_subsystem = SubsystemDef(
        name=new_name,
        description=new_description or f"Split from {source_name}",
        components=moving,
    )

    # Move internal edges
    move_comp_names = {c.name for c in moving}
    stay_comp_names = {c.name for c in staying}
    new_internal_edges: List[ArchEdge] = []
    remaining_edges: List[ArchEdge] = []
    cross_edges: List[ArchEdge] = []

    for edge in source.edges:
        if edge.source in move_comp_names and edge.target in move_comp_names:
            new_internal_edges.append(edge)
        elif edge.source in stay_comp_names and edge.target in stay_comp_names:
            remaining_edges.append(edge)
        else:
            # Cross-subsystem edge → becomes inter-subsystem
            cross_edges.append(edge)

    source.edges = remaining_edges
    new_subsystem.edges = new_internal_edges

    # Add cross edges as inter-subsystem edges
    for edge in cross_edges:
        if edge.source in move_comp_names:
            arch.edges.append(ArchEdge(source=new_name, target=source_name))
        else:
            arch.edges.append(ArchEdge(source=source_name, target=new_name))

    arch.subsystems.append(new_subsystem)
    logger.info("Split %s → %s + %s", source_name, source_name, new_name)
    return source, new_subsystem


def merge_subsystems(
    arch: SystemArchitecture,
    name_a: str,
    name_b: str,
    merged_name: Optional[str] = None,
) -> SubsystemDef:
    """Merge two subsystems into one.

    Args:
        name_a, name_b: Subsystems to merge.
        merged_name: Name for the merged subsystem. Defaults to name_a.

    Returns:
        The merged subsystem.
    """
    ss_a = arch.get_subsystem(name_a)
    ss_b = arch.get_subsystem(name_b)
    if not ss_a:
        raise ValueError(f"Subsystem not found: {name_a}")
    if not ss_b:
        raise ValueError(f"Subsystem not found: {name_b}")

    final_name = merged_name or name_a
    merged = SubsystemDef(
        name=final_name,
        description=f"Merged from {name_a} and {name_b}",
        components=ss_a.components + ss_b.components,
        edges=ss_a.edges + ss_b.edges,
    )

    # Remove old subsystems
    arch.subsystems = [
        s for s in arch.subsystems if s.name not in (name_a, name_b)
    ]
    arch.subsystems.append(merged)

    # Update inter-subsystem edges
    new_edges: List[ArchEdge] = []
    for edge in arch.edges:
        src = final_name if edge.source in (name_a, name_b) else edge.source
        tgt = final_name if edge.target in (name_a, name_b) else edge.target
        if src != tgt:  # Don't add self-edges
            new_edges.append(ArchEdge(source=src, target=tgt))
    arch.edges = new_edges

    # Update constraints
    new_constraints: List[ArchConstraint] = []
    for c in arch.constraints:
        src = final_name if c.source in (name_a, name_b) else c.source
        tgt = final_name if c.target in (name_a, name_b) else c.target
        if src != tgt:
            new_constraints.append(ArchConstraint(
                constraint_type=c.constraint_type,
                source=src, target=tgt, reason=c.reason,
            ))
    arch.constraints = new_constraints

    logger.info("Merged %s + %s → %s", name_a, name_b, final_name)
    return merged


def move_component(
    arch: SystemArchitecture,
    component_name: str,
    from_subsystem: str,
    to_subsystem: str,
) -> None:
    """Move a component from one subsystem to another."""
    source = arch.get_subsystem(from_subsystem)
    target = arch.get_subsystem(to_subsystem)
    if not source:
        raise ValueError(f"Source subsystem not found: {from_subsystem}")
    if not target:
        raise ValueError(f"Target subsystem not found: {to_subsystem}")

    comp = None
    remaining = []
    for c in source.components:
        if c.name == component_name:
            comp = c
        else:
            remaining.append(c)

    if not comp:
        raise ValueError(
            f"Component {component_name} not found in {from_subsystem}"
        )

    source.components = remaining
    target.components.append(comp)

    # Move related internal edges
    new_source_edges: List[ArchEdge] = []
    for edge in source.edges:
        if edge.source == component_name or edge.target == component_name:
            target.edges.append(edge)
        else:
            new_source_edges.append(edge)
    source.edges = new_source_edges

    logger.info("Moved %s: %s → %s", component_name, from_subsystem, to_subsystem)


# ── Subsystem File Generation ─────────────────────────────────────────


def generate_subsystem_files(
    arch: SystemArchitecture,
    project_root: Path,
) -> List[Path]:
    """Generate per-subsystem JSON files from system.json.

    Creates .codegraph/architecture/subsystems/<name>.json for each subsystem.
    """
    subsys_dir = project_root / ".codegraph" / "architecture" / SUBSYSTEMS_DIR
    subsys_dir.mkdir(parents=True, exist_ok=True)

    paths: List[Path] = []
    for subsystem in arch.subsystems:
        sf = SubsystemFile(
            name=subsystem.name,
            description=subsystem.description,
            intent=subsystem.description,
            components=[c.to_dict() for c in subsystem.components],
            edges=[[e.source, e.target] for e in subsystem.edges],
        )

        # Find applicable constraints
        for c in arch.constraints:
            if c.source == subsystem.name or c.target == subsystem.name:
                sf.rules.append(c.to_dict())

        path = subsys_dir / f"{subsystem.name}.json"
        path.write_text(
            json.dumps(sf.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        paths.append(path)

    logger.info("Generated %d subsystem files in %s", len(paths), subsys_dir)
    return paths


def load_subsystem_file(project_root: Path, name: str) -> Optional[SubsystemFile]:
    """Load a per-subsystem JSON file."""
    path = project_root / ".codegraph" / "architecture" / SUBSYSTEMS_DIR / f"{name}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return SubsystemFile(
        name=data.get("name", name),
        description=data.get("description", ""),
        intent=data.get("intent", ""),
        components=data.get("components", []),
        edges=data.get("edges", []),
        rules=data.get("rules", []),
    )


def list_subsystem_files(project_root: Path) -> List[str]:
    """List available subsystem files."""
    subsys_dir = project_root / ".codegraph" / "architecture" / SUBSYSTEMS_DIR
    if not subsys_dir.exists():
        return []
    return [p.stem for p in sorted(subsys_dir.glob("*.json"))]
