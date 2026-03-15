from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List


@dataclass
class BuildNode:
    id: str
    node_type: str  # service, container, deployment, runtime
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = {"id": self.id, "node_type": self.node_type}
        if self.details:
            data["details"] = self.details
        return data


@dataclass
class BuildEdge:
    source: str
    target: str
    edge_type: str = "depends_on"

    def to_dict(self) -> Dict[str, Any]:
        return {"source": self.source, "target": self.target, "edge_type": self.edge_type}


@dataclass
class GraphBuild:
    nodes: List[BuildNode] = field(default_factory=list)
    edges: List[BuildEdge] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "total_nodes": len(self.nodes),
            "total_edges": len(self.edges),
        }

    def save(self, project_root: Path) -> Path:
        out = project_root / ".codegraph" / "graphs" / "graph_build.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return out


def _read_lines(path: Path) -> List[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []


def build_graph_build(project_root: Path) -> GraphBuild:
    nodes: List[BuildNode] = []
    edges: List[BuildEdge] = []

    req = project_root / "requirements.txt"
    if req.exists():
        runtime_id = "runtime:python"
        nodes.append(BuildNode(id=runtime_id, node_type="runtime", details={"source": "requirements.txt"}))
        for line in _read_lines(req):
            pkg = line.strip()
            if not pkg or pkg.startswith("#"):
                continue
            dep_id = f"dependency:{pkg}"
            nodes.append(BuildNode(id=dep_id, node_type="service"))
            edges.append(BuildEdge(source=runtime_id, target=dep_id, edge_type="dependency"))

    package_json = project_root / "package.json"
    if package_json.exists():
        runtime_id = "runtime:node"
        nodes.append(BuildNode(id=runtime_id, node_type="runtime", details={"source": "package.json"}))
        try:
            data = json.loads(package_json.read_text(encoding="utf-8"))
            deps = {}
            deps.update(data.get("dependencies", {}) or {})
            deps.update(data.get("devDependencies", {}) or {})
            for dep, ver in sorted(deps.items()):
                dep_id = f"dependency:{dep}@{ver}"
                nodes.append(BuildNode(id=dep_id, node_type="service"))
                edges.append(BuildEdge(source=runtime_id, target=dep_id, edge_type="dependency"))
        except Exception:
            pass

    dockerfile = project_root / "Dockerfile"
    if dockerfile.exists():
        container_id = "container:docker"
        nodes.append(BuildNode(id=container_id, node_type="container"))
        lines = _read_lines(dockerfile)
        for line in lines:
            line_s = line.strip()
            if line_s.upper().startswith("FROM "):
                image = line_s.split(maxsplit=1)[1].strip()
                image_id = f"runtime:{image}"
                nodes.append(BuildNode(id=image_id, node_type="runtime"))
                edges.append(BuildEdge(source=container_id, target=image_id, edge_type="runtime"))

    workflow_dir = project_root / ".github" / "workflows"
    if workflow_dir.exists():
        deploy_id = "deployment:ci"
        nodes.append(BuildNode(id=deploy_id, node_type="deployment"))
        for wf in workflow_dir.glob("*.yml"):
            node_id = f"pipeline:{wf.name}"
            nodes.append(BuildNode(id=node_id, node_type="deployment"))
            edges.append(BuildEdge(source=deploy_id, target=node_id, edge_type="pipeline"))

    # Deduplicate by id
    dedup_nodes: Dict[str, BuildNode] = {n.id: n for n in nodes}
    dedup_edges: Dict[tuple[str, str, str], BuildEdge] = {
        (e.source, e.target, e.edge_type): e for e in edges
    }

    return GraphBuild(
        nodes=sorted(dedup_nodes.values(), key=lambda n: n.id),
        edges=list(dedup_edges.values()),
    )
