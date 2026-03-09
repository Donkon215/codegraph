"""codegraph.agent_memory — Persistent agent memory for learning patterns.

Stores:
- Successful repair patterns
- Convention observations
- Frequently encountered issues
- Agent performance stats
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from codegraph.logging_config import get_logger
from codegraph.utils.formatting import iso_now

logger = get_logger("agent_memory")

MEMORY_FILE = "agent_memory.json"


@dataclass
class RepairPattern:
    """A learned repair pattern from successful fixes."""

    pattern_id: str = ""
    task_type: str = ""  # "intent_missing", "orphan", "policy_violation"
    action_taken: str = ""  # "add_intent", "flag_for_human_review", "connect_call"
    node_pattern: str = ""  # glob pattern that matched
    success_count: int = 0
    last_used: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            "task_type": self.task_type,
            "action_taken": self.action_taken,
            "node_pattern": self.node_pattern,
            "success_count": self.success_count,
            "last_used": self.last_used,
        }


@dataclass
class Convention:
    """An observed codebase convention."""

    name: str = ""
    description: str = ""
    examples: List[str] = field(default_factory=list)
    confidence: float = 0.0
    observed_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "examples": self.examples[:5],
            "confidence": round(self.confidence, 2),
            "observed_at": self.observed_at,
        }


@dataclass
class AgentStats:
    """Cumulative agent performance statistics."""

    total_cycles: int = 0
    total_intents_applied: int = 0
    total_repairs_applied: int = 0
    total_flags: int = 0
    successful_repairs: int = 0
    failed_repairs: int = 0
    avg_tasks_per_cycle: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_cycles": self.total_cycles,
            "total_intents_applied": self.total_intents_applied,
            "total_repairs_applied": self.total_repairs_applied,
            "total_flags": self.total_flags,
            "successful_repairs": self.successful_repairs,
            "failed_repairs": self.failed_repairs,
            "avg_tasks_per_cycle": round(self.avg_tasks_per_cycle, 1),
        }


@dataclass
class AgentMemory:
    """Persistent agent memory store."""

    version: int = 1
    patterns: List[RepairPattern] = field(default_factory=list)
    conventions: List[Convention] = field(default_factory=list)
    stats: AgentStats = field(default_factory=AgentStats)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "patterns": [p.to_dict() for p in self.patterns],
            "conventions": [c.to_dict() for c in self.conventions],
            "stats": self.stats.to_dict(),
            "notes": self.notes[-20:],  # Keep last 20 notes
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    def add_pattern(self, task_type: str, action: str, node_pattern: str) -> None:
        """Record a successful repair pattern."""
        # Check if pattern already exists
        for p in self.patterns:
            if p.task_type == task_type and p.action_taken == action and p.node_pattern == node_pattern:
                p.success_count += 1
                p.last_used = iso_now()
                return

        pid = f"pat_{len(self.patterns) + 1:03d}"
        self.patterns.append(RepairPattern(
            pattern_id=pid,
            task_type=task_type,
            action_taken=action,
            node_pattern=node_pattern,
            success_count=1,
            last_used=iso_now(),
        ))

    def add_convention(self, name: str, description: str, examples: Optional[List[str]] = None) -> None:
        """Record an observed convention."""
        for c in self.conventions:
            if c.name == name:
                c.confidence = min(1.0, c.confidence + 0.1)
                return

        self.conventions.append(Convention(
            name=name,
            description=description,
            examples=examples or [],
            confidence=0.5,
            observed_at=iso_now(),
        ))

    def add_note(self, note: str) -> None:
        """Add a free-form note."""
        self.notes.append(f"[{iso_now()}] {note}")

    def record_cycle(self, intents: int, repairs: int, flags: int) -> None:
        """Record stats for a completed cycle."""
        self.stats.total_cycles += 1
        self.stats.total_intents_applied += intents
        self.stats.total_repairs_applied += repairs
        self.stats.total_flags += flags
        total_tasks = intents + repairs + flags
        # Running average
        if self.stats.total_cycles > 0:
            self.stats.avg_tasks_per_cycle = (
                (self.stats.total_intents_applied + self.stats.total_repairs_applied + self.stats.total_flags)
                / self.stats.total_cycles
            )

    def format(self) -> str:
        lines = [
            "Agent Memory",
            f"  Patterns: {len(self.patterns)}",
            f"  Conventions: {len(self.conventions)}",
            f"  Cycles: {self.stats.total_cycles}",
            f"  Intents applied: {self.stats.total_intents_applied}",
            f"  Repairs applied: {self.stats.total_repairs_applied}",
        ]
        if self.patterns:
            lines.append("\nTop patterns:")
            for p in sorted(self.patterns, key=lambda x: x.success_count, reverse=True)[:5]:
                lines.append(f"  {p.task_type} → {p.action_taken} ({p.success_count}x)")
        if self.conventions:
            lines.append("\nConventions:")
            for c in self.conventions[:5]:
                lines.append(f"  {c.name}: {c.description} ({c.confidence:.0%})")
        return "\n".join(lines)


def load_memory(project_root: Path) -> AgentMemory:
    """Load agent memory from .codegraph/agent_memory.json."""
    path = project_root / ".codegraph" / MEMORY_FILE
    if not path.exists():
        return AgentMemory()

    data = json.loads(path.read_text(encoding="utf-8"))
    memory = AgentMemory(version=data.get("version", 1))

    for pd in data.get("patterns", []):
        memory.patterns.append(RepairPattern(
            pattern_id=pd.get("pattern_id", ""),
            task_type=pd.get("task_type", ""),
            action_taken=pd.get("action_taken", ""),
            node_pattern=pd.get("node_pattern", ""),
            success_count=pd.get("success_count", 0),
            last_used=pd.get("last_used", ""),
        ))

    for cd in data.get("conventions", []):
        memory.conventions.append(Convention(
            name=cd.get("name", ""),
            description=cd.get("description", ""),
            examples=cd.get("examples", []),
            confidence=cd.get("confidence", 0.0),
            observed_at=cd.get("observed_at", ""),
        ))

    sd = data.get("stats", {})
    memory.stats = AgentStats(
        total_cycles=sd.get("total_cycles", 0),
        total_intents_applied=sd.get("total_intents_applied", 0),
        total_repairs_applied=sd.get("total_repairs_applied", 0),
        total_flags=sd.get("total_flags", 0),
        successful_repairs=sd.get("successful_repairs", 0),
        failed_repairs=sd.get("failed_repairs", 0),
        avg_tasks_per_cycle=sd.get("avg_tasks_per_cycle", 0.0),
    )

    memory.notes = data.get("notes", [])
    return memory


def save_memory(memory: AgentMemory, project_root: Path) -> Path:
    """Save agent memory to .codegraph/agent_memory.json."""
    path = project_root / ".codegraph" / MEMORY_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(memory.to_json(), encoding="utf-8")
    return path
