from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List


@dataclass
class SystemArchitectureGraph:
    repositories: Dict[str, str] = field(default_factory=dict)
    nodes: List[Dict[str, Any]] = field(default_factory=list)
    edges: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "repositories": self.repositories,
            "nodes": self.nodes,
            "edges": self.edges,
        }


def _load_system_config(project_root: Path) -> Dict[str, str]:
    path = project_root / ".codegraph" / "system.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    repos = data.get("repositories", {})
    if not isinstance(repos, dict):
        return {}
    return {str(k): str(v) for k, v in repos.items()}


def _extract_repo_api_routes(repo_root: Path) -> List[str]:
    routes: List[str] = []
    pattern = re.compile(r"['\"](/api/[a-zA-Z0-9_\-/]+)['\"]")
    for path in repo_root.rglob("*.py"):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for match in pattern.finditer(text):
            routes.append(match.group(1))
    return sorted(set(routes))


def _extract_repo_outbound_routes(repo_root: Path) -> List[str]:
    routes: List[str] = []
    pattern = re.compile(r"(?:fetch|axios|requests\.(?:get|post|put|patch|delete))\s*\(\s*['\"]([^'\"]+)['\"]")
    for path in repo_root.rglob("*.py"):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for match in pattern.finditer(text):
            routes.append(match.group(1))
    for path in list(repo_root.rglob("*.ts")) + list(repo_root.rglob("*.tsx")) + list(repo_root.rglob("*.js")) + list(repo_root.rglob("*.jsx")):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for match in pattern.finditer(text):
            routes.append(match.group(1))
    return sorted(set(routes))


def build_system_graph(project_root: Path) -> SystemArchitectureGraph:
    repos = _load_system_config(project_root)
    graph = SystemArchitectureGraph(repositories=repos)
    if not repos:
        return graph

    api_by_repo: Dict[str, List[str]] = {}
    outbound_by_repo: Dict[str, List[str]] = {}

    for repo_name, rel_path in repos.items():
        repo_root = (project_root / rel_path).resolve()
        graph.nodes.append({
            "id": f"repo:{repo_name}",
            "type": "repository",
            "path": str(repo_root),
        })

        if not repo_root.exists():
            continue
        api_by_repo[repo_name] = _extract_repo_api_routes(repo_root)
        outbound_by_repo[repo_name] = _extract_repo_outbound_routes(repo_root)

    for src_repo, outbound_routes in outbound_by_repo.items():
        for tgt_repo, api_routes in api_by_repo.items():
            if src_repo == tgt_repo:
                continue
            matched = sorted({route for route in outbound_routes if any(route.endswith(api) or api in route for api in api_routes)})
            if not matched:
                continue
            graph.edges.append({
                "source": f"repo:{src_repo}",
                "target": f"repo:{tgt_repo}",
                "edge_type": "cross_repo_api",
                "matched_routes": matched[:20],
            })

    return graph
