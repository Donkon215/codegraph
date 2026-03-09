"""codegraph.visualization — Graph visualization export.

Exports the dependency graph in formats suitable for visualization:
- JSON for D3.js / Cytoscape.js
- Mermaid diagram syntax
- HTML standalone report
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from codegraph.logging_config import get_logger
from codegraph.models.graph0 import Graph0
from codegraph.models.graph1 import Graph1
from codegraph.models.workflow import Workflow

logger = get_logger("visualization")


@dataclass
class VisNode:
    """A node for visualization."""

    id: str
    label: str
    file: str = ""
    node_type: str = ""
    layer: int = 0
    has_intent: bool = False
    group: str = ""  # module grouping

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "file": self.file,
            "type": self.node_type,
            "layer": self.layer,
            "has_intent": self.has_intent,
            "group": self.group,
        }


@dataclass
class VisEdge:
    """An edge for visualization."""

    source: str
    target: str
    edge_type: str = "call"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "type": self.edge_type,
        }


@dataclass
class VisGraph:
    """Complete visualization graph."""

    nodes: List[VisNode] = field(default_factory=list)
    edges: List[VisEdge] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "metadata": self.metadata,
        }

    def to_json(self, compact: bool = False) -> str:
        indent = None if compact else 2
        return json.dumps(self.to_dict(), indent=indent)


def build_vis_graph(
    graph0: Graph0,
    graph1: Graph1,
    workflow: Workflow,
    *,
    filter_file: Optional[str] = None,
    max_nodes: int = 500,
) -> VisGraph:
    """Build a visualization graph from codegraph data.

    Args:
        filter_file: Only include nodes from this file (glob pattern).
        max_nodes: Maximum number of nodes to include.
    """
    import fnmatch

    vis = VisGraph()
    g1_map = {n.id: n for n in graph1.nodes}

    # Filter nodes
    nodes = list(graph0.nodes)
    if filter_file:
        nodes = [n for n in nodes if fnmatch.fnmatch(n.file, filter_file)]

    # Limit
    if len(nodes) > max_nodes:
        nodes = nodes[:max_nodes]

    node_ids: Set[str] = set()
    for n in nodes:
        g1n = g1_map.get(n.id)
        label = n.id.split("::")[-1] if "::" in n.id else n.id
        group = n.file.rsplit("/", 1)[0] if "/" in n.file else n.file

        vis.nodes.append(VisNode(
            id=n.id,
            label=label,
            file=n.file,
            node_type=n.type,
            layer=g1n.layer if g1n else 0,
            has_intent=bool(g1n and g1n.intent),
            group=group,
        ))
        node_ids.add(n.id)

    # Edges
    for edge in workflow.edges:
        if edge.source in node_ids and edge.target in node_ids:
            vis.edges.append(VisEdge(
                source=edge.source,
                target=edge.target,
                edge_type=edge.type,
            ))

    vis.metadata = {
        "total_nodes": len(vis.nodes),
        "total_edges": len(vis.edges),
        "filtered": filter_file or "none",
    }

    return vis


def export_mermaid(
    graph0: Graph0,
    graph1: Graph1,
    workflow: Workflow,
    *,
    filter_file: Optional[str] = None,
    max_nodes: int = 100,
    direction: str = "TD",
) -> str:
    """Export graph as Mermaid diagram syntax."""
    vis = build_vis_graph(graph0, graph1, workflow, filter_file=filter_file, max_nodes=max_nodes)

    lines = [f"graph {direction}"]

    # Group nodes by module
    groups: Dict[str, List[VisNode]] = defaultdict(list)
    for node in vis.nodes:
        groups[node.group].append(node)

    # Sanitize node ID for mermaid
    def mermaid_id(nid: str) -> str:
        return nid.replace("::", "__").replace("/", "_").replace(".", "_").replace("-", "_")

    for group_name, group_nodes in groups.items():
        safe_group = group_name.replace("/", "_").replace(".", "_").replace("-", "_")
        lines.append(f"    subgraph {safe_group}")
        for node in group_nodes:
            mid = mermaid_id(node.id)
            shape = f"[{node.label}]" if node.node_type == "function" else f"({node.label})"
            lines.append(f"        {mid}{shape}")
        lines.append("    end")

    for edge in vis.edges:
        src = mermaid_id(edge.source)
        tgt = mermaid_id(edge.target)
        lines.append(f"    {src} --> {tgt}")

    return "\n".join(lines)


def export_html_report(
    graph0: Graph0,
    graph1: Graph1,
    workflow: Workflow,
    *,
    title: str = "Codegraph Visualization",
    filter_file: Optional[str] = None,
    max_nodes: int = 300,
) -> str:
    """Generate a standalone HTML page with an interactive graph visualization."""
    vis = build_vis_graph(graph0, graph1, workflow, filter_file=filter_file, max_nodes=max_nodes)
    graph_json = vis.to_json()

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{title}</title>
    <style>
        body {{ margin: 0; font-family: system-ui, sans-serif; background: #1a1a2e; color: #eee; }}
        #info {{ position: fixed; top: 10px; left: 10px; background: rgba(0,0,0,0.7);
                 padding: 15px; border-radius: 8px; z-index: 10; }}
        #graph {{ width: 100vw; height: 100vh; }}
        .node {{ cursor: pointer; }}
        .node circle {{ stroke: #fff; stroke-width: 1.5px; }}
        .link {{ stroke: #444; stroke-opacity: 0.6; stroke-width: 1px; }}
        .label {{ font-size: 10px; fill: #ccc; pointer-events: none; }}
    </style>
</head>
<body>
    <div id="info">
        <h3>{title}</h3>
        <p>Nodes: {len(vis.nodes)} | Edges: {len(vis.edges)}</p>
        <p><small>Drag to pan, scroll to zoom, click nodes for details</small></p>
    </div>
    <div id="graph"></div>
    <script src="https://d3js.org/d3.v7.min.js"></script>
    <script>
    const data = {graph_json};

    const width = window.innerWidth;
    const height = window.innerHeight;

    const svg = d3.select("#graph").append("svg")
        .attr("width", width).attr("height", height);

    const g = svg.append("g");

    svg.call(d3.zoom().on("zoom", (e) => g.attr("transform", e.transform)));

    const color = d3.scaleOrdinal(d3.schemeCategory10);

    const simulation = d3.forceSimulation(data.nodes)
        .force("link", d3.forceLink(data.edges).id(d => d.id).distance(80))
        .force("charge", d3.forceManyBody().strength(-200))
        .force("center", d3.forceCenter(width / 2, height / 2));

    const link = g.selectAll(".link").data(data.edges).enter()
        .append("line").attr("class", "link");

    const node = g.selectAll(".node").data(data.nodes).enter()
        .append("g").attr("class", "node")
        .call(d3.drag()
            .on("start", (e, d) => {{ if (!e.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; }})
            .on("drag", (e, d) => {{ d.fx = e.x; d.fy = e.y; }})
            .on("end", (e, d) => {{ if (!e.active) simulation.alphaTarget(0); d.fx = null; d.fy = null; }}));

    node.append("circle")
        .attr("r", d => d.type === "class" ? 8 : 5)
        .attr("fill", d => d.has_intent ? color(d.group) : "#666");

    node.append("text").attr("class", "label")
        .attr("dx", 12).attr("dy", 4).text(d => d.label);

    node.append("title").text(d => d.id + "\\n" + d.file);

    simulation.on("tick", () => {{
        link.attr("x1", d => d.source.x).attr("y1", d => d.source.y)
            .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
        node.attr("transform", d => `translate(${{d.x}},${{d.y}})`);
    }});
    </script>
</body>
</html>"""
    return html


def save_visualization(
    graph0: Graph0,
    graph1: Graph1,
    workflow: Workflow,
    output_path: Path,
    *,
    fmt: str = "json",
    filter_file: Optional[str] = None,
    max_nodes: int = 500,
) -> Path:
    """Save visualization to a file."""
    if fmt == "json":
        vis = build_vis_graph(graph0, graph1, workflow, filter_file=filter_file, max_nodes=max_nodes)
        output_path.write_text(vis.to_json(), encoding="utf-8")
    elif fmt == "mermaid":
        content = export_mermaid(graph0, graph1, workflow, filter_file=filter_file, max_nodes=max_nodes)
        output_path.write_text(content, encoding="utf-8")
    elif fmt == "html":
        content = export_html_report(graph0, graph1, workflow, filter_file=filter_file, max_nodes=max_nodes)
        output_path.write_text(content, encoding="utf-8")
    else:
        raise ValueError(f"Unknown format: {fmt}")
    return output_path
