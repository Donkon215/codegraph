from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from codegraph.architecture_detection import detect_architecture_patterns
from codegraph.graph_module import build_module_graph


@dataclass
class PatternFinding:
    architecture_type: str
    confidence: float
    consistency: float
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "architecture_type": self.architecture_type,
            "confidence": round(self.confidence, 4),
            "consistency": round(self.consistency, 4),
            "details": self.details,
        }


@dataclass
class ArchitecturePatternReport:
    primary_pattern: str
    patterns: List[PatternFinding] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "primary_pattern": self.primary_pattern,
            "patterns": [p.to_dict() for p in self.patterns],
        }

    def save(self, project_root: Path) -> Path:
        out = project_root / ".codegraph" / "architecture" / "architecture_patterns.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return out


def detect_patterns(project_root: Path, graph0, index) -> ArchitecturePatternReport:
    base = detect_architecture_patterns(graph0, index)
    module_graph = build_module_graph(project_root)

    patterns: List[PatternFinding] = []
    reports = base.get("reports", {})

    layered = reports.get("layered", {})
    layered_consistency = 1.0 - min(1.0, float(layered.get("details", {}).get("upward_violations", 0)) / 50.0)
    patterns.append(PatternFinding(
        architecture_type="layered",
        confidence=float(layered.get("confidence", 0.0)),
        consistency=layered_consistency,
        details=layered.get("details", {}),
    ))

    event_driven = reports.get("event_driven", {})
    event_density = len(event_driven.get("details", {}).get("event_named_modules", [])) / max(1, len(module_graph.nodes))
    patterns.append(PatternFinding(
        architecture_type="event_driven",
        confidence=float(event_driven.get("confidence", 0.0)),
        consistency=min(1.0, event_density * 5.0),
        details=event_driven.get("details", {}),
    ))

    pipeline = reports.get("pipeline", {})
    chain_count = float(pipeline.get("details", {}).get("chain_module_count", 0))
    patterns.append(PatternFinding(
        architecture_type="pipeline",
        confidence=float(pipeline.get("confidence", 0.0)),
        consistency=min(1.0, chain_count / 100.0),
        details=pipeline.get("details", {}),
    ))

    # Additional heuristics for requested styles
    module_names = [n.id.lower() for n in module_graph.nodes]

    mvc_markers = sum(1 for m in module_names if any(k in m for k in ("controller", "model", "view")))
    patterns.append(PatternFinding(
        architecture_type="mvc",
        confidence=min(1.0, mvc_markers / 12.0),
        consistency=min(1.0, mvc_markers / 15.0),
        details={"markers": mvc_markers},
    ))

    clean_markers = sum(1 for m in module_names if any(k in m for k in ("domain", "usecase", "entity", "repository")))
    patterns.append(PatternFinding(
        architecture_type="clean",
        confidence=min(1.0, clean_markers / 16.0),
        consistency=min(1.0, clean_markers / 20.0),
        details={"markers": clean_markers},
    ))

    hexa_markers = sum(1 for m in module_names if any(k in m for k in ("adapter", "port", "driven", "driver")))
    patterns.append(PatternFinding(
        architecture_type="hexagonal",
        confidence=min(1.0, hexa_markers / 10.0),
        consistency=min(1.0, hexa_markers / 12.0),
        details={"markers": hexa_markers},
    ))

    microservice_markers = sum(1 for m in module_names if any(k in m for k in ("service", "gateway", "api", "worker", "queue")))
    patterns.append(PatternFinding(
        architecture_type="microservice",
        confidence=min(1.0, microservice_markers / 20.0),
        consistency=min(1.0, microservice_markers / 25.0),
        details={"markers": microservice_markers},
    ))

    primary = max(patterns, key=lambda p: p.confidence).architecture_type if patterns else "unknown"
    return ArchitecturePatternReport(primary_pattern=primary, patterns=patterns)
