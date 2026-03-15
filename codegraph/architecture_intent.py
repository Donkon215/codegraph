from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List


INTENT_FILE = "intent.json"


@dataclass
class ArchitectureIntent:
    layers: Dict[str, List[str]] = field(default_factory=dict)
    rules: List[Dict[str, Any]] = field(default_factory=list)
    subsystem_rules: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "layers": self.layers,
            "rules": self.rules,
            "subsystem_rules": self.subsystem_rules,
        }


def load_architecture_intent(root_path: Path) -> ArchitectureIntent:
    path = root_path / ".codegraph" / "architecture" / INTENT_FILE
    if not path.exists():
        return ArchitectureIntent()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ArchitectureIntent()

    return ArchitectureIntent(
        layers={k: list(v) for k, v in (raw.get("layers", {}) or {}).items()},
        rules=list(raw.get("rules", []) or []),
        subsystem_rules=dict(raw.get("subsystem_rules", {}) or {}),
    )


def save_architecture_intent(root_path: Path, intent: ArchitectureIntent) -> Path:
    path = root_path / ".codegraph" / "architecture" / INTENT_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(intent.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return path
