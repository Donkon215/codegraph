from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from codegraph.architecture_graph import ArchitectureGraph


@dataclass
class SystemLayerMapping:
    layers: Dict[str, List[str]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"layers": self.layers}

    def save(self, project_root: Path) -> Path:
        out = project_root / ".codegraph" / "architecture" / "system_layers.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return out


def _classify(node_id: str, file_path: str) -> str:
    low = f"{file_path}::{node_id}".lower()
    if any(k in low for k in ("react", "component", "frontend", "ui/", ".tsx", ".jsx")):
        return "UI"
    if any(k in low for k in ("route", "controller", "api", "fastapi", "flask")):
        return "API"
    if any(k in low for k in ("service", "usecase", "handler")):
        return "Service"
    if any(k in low for k in ("repo", "repository", "dao", "model", "data")):
        return "Data"
    if any(k in low for k in ("infra", "storage", "docker", "deploy", "queue", "worker")):
        return "Infrastructure"
    if any(k in low for k in ("event", "dispatch", "emit", "pub", "sub")):
        return "Events"
    return "Service"


def build_system_layer_mapping(project_root: Path) -> SystemLayerMapping:
    graph = ArchitectureGraph.load(project_root)
    layers: Dict[str, List[str]] = {
        "UI": [],
        "API": [],
        "Service": [],
        "Data": [],
        "Infrastructure": [],
        "Events": [],
    }

    for node in graph.structure_graph.nodes:
        layer = _classify(node.id, node.file)
        layers.setdefault(layer, []).append(node.id)

    for key in layers:
        layers[key] = sorted(set(layers[key]))

    return SystemLayerMapping(layers=layers)
