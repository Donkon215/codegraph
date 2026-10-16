from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple


@dataclass
class CrossLanguageEdge:
    source: str
    target: str
    edge_type: str
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = {
            "source": self.source,
            "target": self.target,
            "edge_type": self.edge_type,
        }
        if self.details:
            data["details"] = self.details
        return data


@dataclass
class CrossLanguageLinkReport:
    edges: List[CrossLanguageEdge] = field(default_factory=list)
    service_nodes: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "edges": [edge.to_dict() for edge in self.edges],
            "service_nodes": self.service_nodes,
            "stats": {
                "edge_count": len(self.edges),
                "service_nodes": len(self.service_nodes),
            },
        }


@lru_cache(maxsize=32)
def _cached_backend_routes(root: str) -> Dict[str, str]:
    project_root = Path(root)
    routes: Dict[str, str] = {}
    from codegraph.utils.file_discovery import discover_source_files

    route_pattern = re.compile(
        r"@\w+\.(?:get|post|put|patch|delete)\((['\"])(/[^'\"]*)\1\)",
        re.IGNORECASE,
    )

    for py_file in discover_source_files(project_root, extensions=[".py"]):
        rel = py_file.relative_to(project_root).as_posix()
        try:
            source = py_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in route_pattern.finditer(source):
            routes[match.group(2)] = rel
    return routes


@lru_cache(maxsize=32)
def _cached_frontend_api_calls(root: str) -> List[Tuple[str, str, str]]:
    project_root = Path(root)
    calls: List[Tuple[str, str, str]] = []
    from codegraph.utils.file_discovery import discover_source_files

    patterns = [
        ("fetch", re.compile(r"fetch\((['\"])(/api/[^'\"]*)\1")),
        (
            "axios",
            re.compile(r"axios\.(?:get|post|put|patch|delete)\((['\"])(/api/[^'\"]*)\1"),
        ),
        ("axios", re.compile(r"axios\((['\"])(/api/[^'\"]*)\1")),
    ]

    for src_file in discover_source_files(
        project_root, extensions=[".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"],
    ):
        rel = src_file.relative_to(project_root).as_posix()
        try:
            content = src_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        for detector, pattern in patterns:
            for match in pattern.finditer(content):
                calls.append((rel, detector, match.group(2)))

    return calls


@lru_cache(maxsize=32)
def _cached_type_maps(root: str) -> Tuple[Dict[str, List[str]], Dict[str, List[str]]]:
    project_root = Path(root)
    from codegraph.utils.file_discovery import discover_source_files

    frontend_types: Dict[str, List[str]] = {}
    backend_models: Dict[str, List[str]] = {}

    ts_pattern = re.compile(r"\b(?:interface|type)\s+([A-Za-z_][A-Za-z0-9_]*)")
    py_pattern = re.compile(r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)")

    for ts_file in discover_source_files(project_root, extensions=[".ts", ".tsx"]):
        rel = ts_file.relative_to(project_root).as_posix()
        try:
            content = ts_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in ts_pattern.finditer(content):
            name = match.group(1)
            base = _normalize_contract_name(name)
            frontend_types.setdefault(base, []).append(f"{rel}::{name}")

    for py_file in discover_source_files(project_root, extensions=[".py"]):
        rel = py_file.relative_to(project_root).as_posix()
        try:
            content = py_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in py_pattern.finditer(content):
            name = match.group(1)
            if not any(token in name.lower() for token in ("model", "dto", "schema")):
                continue
            base = _normalize_contract_name(name)
            backend_models.setdefault(base, []).append(f"{rel}::{name}")

    return frontend_types, backend_models


def _normalize_contract_name(name: str) -> str:
    normalized = re.sub(r"(DTO|Dto|Model|Schema)$", "", name)
    return normalized.lower()


def _detect_service_boundaries(project_root: Path) -> List[Dict[str, Any]]:
    boundaries: Dict[str, Set[str]] = {
        "frontend": set(),
        "backend": set(),
        "worker": set(),
        "scheduler": set(),
        "gateway": set(),
    }

    from codegraph.utils.file_discovery import discover_source_files

    for src_file in discover_source_files(
        project_root,
        extensions=[".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"],
    ):
        rel = src_file.relative_to(project_root).as_posix().lower()

        if "frontend" in rel or "/src/components/" in rel:
            boundaries["frontend"].add(rel)
        if any(token in rel for token in ("backend", "api", "server", "service")):
            boundaries["backend"].add(rel)
        if any(token in rel for token in ("worker", "queue", "celery")):
            boundaries["worker"].add(rel)
        if any(token in rel for token in ("scheduler", "cron", "jobs")):
            boundaries["scheduler"].add(rel)
        if "gateway" in rel:
            boundaries["gateway"].add(rel)

    nodes: List[Dict[str, Any]] = []
    for kind, files in boundaries.items():
        if not files:
            continue
        nodes.append(
            {
                "id": f"service::{kind}",
                "service_type": kind,
                "file_count": len(files),
                "sample_files": sorted(files)[:10],
            }
        )

    return nodes


def build_cross_language_links(project_root: Path) -> CrossLanguageLinkReport:
    report = CrossLanguageLinkReport()

    # The caches are keyed by root for convenience, but discovery/config/source
    # can change between builds at that same root. Refresh before each build.
    _cached_backend_routes.cache_clear()
    _cached_frontend_api_calls.cache_clear()
    _cached_type_maps.cache_clear()

    routes = _cached_backend_routes(str(project_root.resolve()))
    frontend_calls = _cached_frontend_api_calls(str(project_root.resolve()))

    for source_file, detector, route in frontend_calls:
        backend_file = routes.get(route)
        if not backend_file:
            continue
        report.edges.append(
            CrossLanguageEdge(
                source=f"{source_file}::<module>",
                target=f"{backend_file}::{route}",
                edge_type="frontend_to_backend",
                details={"route": route, "detector": detector},
            )
        )

    frontend_types, backend_models = _cached_type_maps(str(project_root.resolve()))
    for key, ts_nodes in frontend_types.items():
        py_nodes = backend_models.get(key, [])
        if not py_nodes:
            continue
        for ts_node in ts_nodes:
            for py_node in py_nodes:
                report.edges.append(
                    CrossLanguageEdge(
                        source=ts_node,
                        target=py_node,
                        edge_type="contract_mapping",
                        details={"contract": key},
                    )
                )

    report.service_nodes = _detect_service_boundaries(project_root)

    return report
