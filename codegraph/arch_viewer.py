"""codegraph.arch_viewer — Interactive HTML architecture dashboard.

Generates a self-contained HTML file that visualizes the architecture
at three levels:
  1. System level — subsystems and inter-subsystem edges
  2. Subsystem level — components within a subsystem
  3. Code level — function call graph

Uses Cytoscape.js (loaded from CDN) for interactive graph rendering.
Shows expected vs actual architecture with violation highlighting.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from codegraph.arch_schema import SystemArchitecture
from codegraph.index import IndexStore
from codegraph.logging_config import get_logger
from codegraph.models.graph0 import Graph0
from codegraph.models.graph1 import Graph1
from codegraph.workflow import Workflow

logger = get_logger("arch_viewer")

VIEWER_DIR = "ui"
VIEWER_FILE = "architecture.html"


def generate_viewer(
    project_root: Path,
    graph0: Graph0,
    graph1: Graph1,
    workflow: Workflow,
    index: IndexStore,
    *,
    architecture: Optional[SystemArchitecture] = None,
    output_path: Optional[Path] = None,
) -> Path:
    """Generate an interactive HTML architecture dashboard.

    Args:
        project_root: Project root directory.
        graph0: Structural graph.
        graph1: Intent overlay.
        workflow: Call edges.
        index: Graph index.
        architecture: Optional architecture definition for expected vs actual.
        output_path: Custom output path; defaults to .codegraph/ui/architecture.html.

    Returns:
        Path to the generated HTML file.
    """
    if output_path is None:
        output_path = project_root / ".codegraph" / VIEWER_DIR / VIEWER_FILE
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Build data for the viewer
    system_data = _build_system_data(graph0, workflow, architecture)
    subsystem_data = _build_subsystem_data(graph0, index, architecture)
    code_data = _build_code_data(graph0, graph1, workflow)
    stats = _build_stats(graph0, workflow, architecture)

    # Generate HTML
    html = _render_html(system_data, subsystem_data, code_data, stats, architecture)
    output_path.write_text(html, encoding="utf-8")

    logger.info("Viewer generated → %s", output_path)
    return output_path


def _build_system_data(
    graph0: Graph0,
    workflow: Workflow,
    architecture: Optional[SystemArchitecture],
) -> Dict[str, Any]:
    """Build system-level graph data (subsystems and inter-subsystem edges)."""
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []

    # Group files into subsystems (auto-detect by top-level directory)
    file_groups: Dict[str, List[str]] = {}
    for node in graph0.nodes:
        parts = node.file.split("/")
        group = parts[0] if len(parts) > 1 else "root"
        file_groups.setdefault(group, []).append(node.file)

    # Deduplicate files per group
    for group in file_groups:
        file_groups[group] = sorted(set(file_groups[group]))

    # Build subsystem nodes
    if architecture and architecture.subsystems:
        # Use architecture-defined subsystems
        for subsys in architecture.subsystems:
            nodes.append({
                "id": subsys.name,
                "label": subsys.name,
                "type": "defined",
                "description": subsys.description,
                "component_count": len(subsys.components),
            })
        # Architecture edges
        for edge in architecture.edges:
            edges.append({
                "source": edge.source,
                "target": edge.target,
                "type": "expected",
            })
    else:
        # Auto-detected from file groups
        for group, files in sorted(file_groups.items()):
            nodes.append({
                "id": group,
                "label": group,
                "type": "detected",
                "file_count": len(files),
            })

    # Add actual inter-group edges from workflow
    node_to_group: Dict[str, str] = {}
    if architecture and architecture.subsystems:
        subsys_modules: Dict[str, str] = {}
        for s in architecture.subsystems:
            for c in s.components:
                if c.module:
                    subsys_modules[c.module] = s.name
        for node in graph0.nodes:
            for mod_path, sname in subsys_modules.items():
                if node.file == mod_path or node.file.startswith(mod_path.rstrip("/") + "/"):
                    node_to_group[node.id] = sname
                    break
    else:
        for node in graph0.nodes:
            parts = node.file.split("/")
            node_to_group[node.id] = parts[0] if len(parts) > 1 else "root"

    group_edges: Dict[Tuple[str, str], int] = {}
    for edge in workflow.edges:
        src_group = node_to_group.get(edge.source, "")
        tgt_group = node_to_group.get(edge.target, "")
        if src_group and tgt_group and src_group != tgt_group:
            key = (src_group, tgt_group)
            group_edges[key] = group_edges.get(key, 0) + 1

    for (src, tgt), count in group_edges.items():
        edges.append({
            "source": src,
            "target": tgt,
            "type": "actual",
            "weight": count,
        })

    return {"nodes": nodes, "edges": edges}


def _build_subsystem_data(
    graph0: Graph0,
    index: IndexStore,
    architecture: Optional[SystemArchitecture],
) -> Dict[str, Any]:
    """Build per-subsystem component data."""
    subsystems: Dict[str, Dict[str, Any]] = {}

    if architecture:
        for subsys in architecture.subsystems:
            components: List[Dict[str, Any]] = []
            for comp in subsys.components:
                components.append({
                    "id": comp.name,
                    "label": comp.name,
                    "module": comp.module,
                    "functions": comp.functions,
                    "description": comp.description,
                })
            internal_edges: List[Dict[str, Any]] = []
            for edge in subsys.edges:
                internal_edges.append({
                    "source": edge.source,
                    "target": edge.target,
                })
            subsystems[subsys.name] = {
                "components": components,
                "edges": internal_edges,
            }
    else:
        # Auto-detect: group by top-level directory
        file_groups: Dict[str, Set[str]] = {}
        for node in graph0.nodes:
            parts = node.file.split("/")
            group = parts[0] if len(parts) > 1 else "root"
            file_groups.setdefault(group, set()).add(node.file)

        for group, files in sorted(file_groups.items()):
            components = [
                {"id": f, "label": f.split("/")[-1], "module": f}
                for f in sorted(files)
            ]
            subsystems[group] = {"components": components, "edges": []}

    return subsystems


def _build_code_data(
    graph0: Graph0,
    graph1: Graph1,
    workflow: Workflow,
) -> Dict[str, Any]:
    """Build code-level graph data (function call graph)."""
    # Intent lookup
    intent_map: Dict[str, str] = {}
    for node in graph1.nodes:
        if node.intent:
            intent_map[node.id] = node.intent

    # Build node list (limit to keep HTML manageable)
    nodes: List[Dict[str, Any]] = []
    node_ids: Set[str] = set()

    # Include nodes that have edges
    edge_nodes: Set[str] = set()
    for edge in workflow.edges:
        edge_nodes.add(edge.source)
        edge_nodes.add(edge.target)

    for node in graph0.nodes:
        if node.id in edge_nodes:
            nodes.append({
                "id": node.id,
                "label": node.id.split("::")[-1],
                "file": node.file,
                "type": node.type,
                "intent": intent_map.get(node.id, ""),
            })
            node_ids.add(node.id)

    # Build edge list
    edges: List[Dict[str, Any]] = []
    for edge in workflow.edges:
        if edge.source in node_ids and edge.target in node_ids:
            edges.append({
                "source": edge.source,
                "target": edge.target,
                "type": edge.edge_type,
            })

    return {"nodes": nodes, "edges": edges}


def _build_stats(
    graph0: Graph0,
    workflow: Workflow,
    architecture: Optional[SystemArchitecture],
) -> Dict[str, Any]:
    """Build summary statistics for the dashboard."""
    files = set(n.file for n in graph0.nodes)
    stats: Dict[str, Any] = {
        "total_nodes": len(graph0.nodes),
        "total_edges": len(workflow.edges),
        "total_files": len(files),
    }
    if architecture:
        stats["architecture_name"] = architecture.name
        stats["subsystem_count"] = len(architecture.subsystems)
        stats["constraint_count"] = len(architecture.constraints)
    return stats


def _render_html(
    system_data: Dict[str, Any],
    subsystem_data: Dict[str, Any],
    code_data: Dict[str, Any],
    stats: Dict[str, Any],
    architecture: Optional[SystemArchitecture],
) -> str:
    """Render the complete HTML dashboard."""
    # Serialize data as JSON for embedding
    system_json = json.dumps(system_data, ensure_ascii=False)
    subsystem_json = json.dumps(subsystem_data, ensure_ascii=False)
    code_json = json.dumps(code_data, ensure_ascii=False)
    stats_json = json.dumps(stats, ensure_ascii=False)

    arch_name = architecture.name if architecture else "Auto-detected"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Codegraph Architecture - {_escape_html(arch_name)}</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/cytoscape/3.28.1/cytoscape.min.js"
        integrity="sha512-JhsHFTOdrzIbsRPHHKNMFODqDU118nwCMXaUlJM4OrmEvuSNKPJfDoSBqjMKhSiuiHEQ7OEFNYMZxn+KeQIFQ=="
        crossorigin="anonymous" referrerpolicy="no-referrer"></script>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       background: #0d1117; color: #c9d1d9; }}
header {{ background: #161b22; padding: 16px 24px; border-bottom: 1px solid #30363d;
         display: flex; align-items: center; gap: 16px; }}
header h1 {{ font-size: 20px; color: #58a6ff; }}
header .stats {{ font-size: 13px; color: #8b949e; display: flex; gap: 16px; }}
header .stats span {{ background: #21262d; padding: 4px 10px; border-radius: 12px; }}
.tabs {{ display: flex; background: #161b22; border-bottom: 1px solid #30363d;
         padding: 0 24px; }}
.tab {{ padding: 10px 20px; cursor: pointer; color: #8b949e; font-size: 14px;
        border-bottom: 2px solid transparent; }}
.tab:hover {{ color: #c9d1d9; }}
.tab.active {{ color: #58a6ff; border-bottom-color: #58a6ff; }}
.panels {{ display: flex; height: calc(100vh - 110px); }}
.graph-panel {{ flex: 1; position: relative; }}
.graph-container {{ width: 100%; height: 100%; }}
.info-panel {{ width: 320px; background: #161b22; border-left: 1px solid #30363d;
               padding: 16px; overflow-y: auto; display: none; }}
.info-panel.visible {{ display: block; }}
.info-panel h3 {{ color: #58a6ff; margin-bottom: 12px; font-size: 15px; }}
.info-panel .field {{ margin-bottom: 8px; }}
.info-panel .field label {{ color: #8b949e; font-size: 12px; display: block; }}
.info-panel .field value {{ color: #c9d1d9; font-size: 13px; }}
.legend {{ position: absolute; bottom: 16px; left: 16px; background: rgba(22,27,34,0.9);
           padding: 12px; border-radius: 8px; font-size: 12px; }}
.legend-item {{ display: flex; align-items: center; gap: 8px; margin: 4px 0; }}
.legend-dot {{ width: 12px; height: 12px; border-radius: 50%; }}
.hidden {{ display: none; }}
</style>
</head>
<body>
<header>
  <h1>&#x1f4ca; {_escape_html(arch_name)}</h1>
  <div class="stats" id="stats"></div>
</header>
<div class="tabs">
  <div class="tab active" onclick="switchTab('system')">System</div>
  <div class="tab" onclick="switchTab('subsystem')">Subsystems</div>
  <div class="tab" onclick="switchTab('code')">Code Graph</div>
</div>
<div class="panels">
  <div class="graph-panel">
    <div class="graph-container" id="cy"></div>
    <div class="legend" id="legend"></div>
  </div>
  <div class="info-panel" id="info-panel">
    <h3 id="info-title">Node Info</h3>
    <div id="info-content"></div>
  </div>
</div>

<script>
const SYSTEM = {system_json};
const SUBSYSTEMS = {subsystem_json};
const CODE = {code_json};
const STATS = {stats_json};

let cy = null;
let currentTab = 'system';

function initStats() {{
  const el = document.getElementById('stats');
  const parts = [];
  parts.push('<span>Nodes: ' + STATS.total_nodes + '</span>');
  parts.push('<span>Edges: ' + STATS.total_edges + '</span>');
  parts.push('<span>Files: ' + STATS.total_files + '</span>');
  if (STATS.subsystem_count) parts.push('<span>Subsystems: ' + STATS.subsystem_count + '</span>');
  el.innerHTML = parts.join('');
}}

function switchTab(tab) {{
  currentTab = tab;
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab')[{{'system':0,'subsystem':1,'code':2}}[tab]].classList.add('active');
  document.getElementById('info-panel').classList.remove('visible');
  renderGraph(tab);
}}

function renderGraph(tab) {{
  const container = document.getElementById('cy');
  if (cy) cy.destroy();

  let elements = [];
  let legendHtml = '';

  if (tab === 'system') {{
    elements = buildSystemElements();
    legendHtml = legendItem('#58a6ff', 'Defined subsystem') +
                 legendItem('#3fb950', 'Detected group') +
                 legendItem('#f0883e', 'Expected edge') +
                 legendItem('#8b949e', 'Actual edge');
  }} else if (tab === 'subsystem') {{
    elements = buildSubsystemElements();
    legendHtml = legendItem('#58a6ff', 'Component') + legendItem('#8b949e', 'Internal edge');
  }} else {{
    elements = buildCodeElements();
    legendHtml = legendItem('#79c0ff', 'Function') +
                 legendItem('#d2a8ff', 'Class') +
                 legendItem('#7ee787', 'Module') +
                 legendItem('#8b949e', 'Call edge');
  }}

  document.getElementById('legend').innerHTML = legendHtml;

  cy = cytoscape({{
    container: container,
    elements: elements,
    style: getStyles(tab),
    layout: getLayout(tab),
    minZoom: 0.2,
    maxZoom: 5,
  }});

  cy.on('tap', 'node', function(evt) {{
    showNodeInfo(evt.target.data(), tab);
  }});

  cy.on('tap', function(evt) {{
    if (evt.target === cy) {{
      document.getElementById('info-panel').classList.remove('visible');
    }}
  }});
}}

function buildSystemElements() {{
  const els = [];
  SYSTEM.nodes.forEach(n => {{
    els.push({{ data: {{ id: n.id, label: n.label, nodeType: n.type,
                        description: n.description || '', count: n.component_count || n.file_count || 0 }} }});
  }});
  SYSTEM.edges.forEach((e, i) => {{
    els.push({{ data: {{ id: 'se' + i, source: e.source, target: e.target,
                        edgeType: e.type, weight: e.weight || 1 }} }});
  }});
  return els;
}}

function buildSubsystemElements() {{
  const els = [];
  let idx = 0;
  Object.keys(SUBSYSTEMS).forEach(name => {{
    const sub = SUBSYSTEMS[name];
    els.push({{ data: {{ id: 'parent_' + name, label: name }}, classes: 'parent' }});
    sub.components.forEach(c => {{
      els.push({{ data: {{ id: c.id, label: c.label, parent: 'parent_' + name,
                          module: c.module || '', description: c.description || '' }} }});
    }});
    sub.edges.forEach(e => {{
      els.push({{ data: {{ id: 'sse' + idx++, source: e.source, target: e.target }} }});
    }});
  }});
  return els;
}}

function buildCodeElements() {{
  const els = [];
  const limit = 500;
  const nodes = CODE.nodes.slice(0, limit);
  const nodeSet = new Set(nodes.map(n => n.id));
  nodes.forEach(n => {{
    els.push({{ data: {{ id: n.id, label: n.label, file: n.file,
                        nodeType: n.type, intent: n.intent || '' }} }});
  }});
  CODE.edges.forEach((e, i) => {{
    if (nodeSet.has(e.source) && nodeSet.has(e.target)) {{
      els.push({{ data: {{ id: 'ce' + i, source: e.source, target: e.target }} }});
    }}
  }});
  return els;
}}

function getStyles(tab) {{
  const base = [
    {{ selector: 'node', style: {{
      'label': 'data(label)', 'text-valign': 'center', 'text-halign': 'center',
      'font-size': '11px', 'color': '#c9d1d9', 'text-outline-width': 2,
      'text-outline-color': '#0d1117', 'width': 40, 'height': 40,
      'background-color': '#58a6ff', 'border-width': 2, 'border-color': '#30363d'
    }} }},
    {{ selector: 'edge', style: {{
      'width': 1.5, 'line-color': '#8b949e', 'target-arrow-color': '#8b949e',
      'target-arrow-shape': 'triangle', 'curve-style': 'bezier',
      'arrow-scale': 0.8, 'opacity': 0.6
    }} }},
    {{ selector: ':parent', style: {{
      'background-color': '#21262d', 'border-color': '#30363d',
      'text-valign': 'top', 'text-halign': 'center', 'padding': '20px',
      'font-size': '14px', 'color': '#58a6ff'
    }} }}
  ];
  if (tab === 'system') {{
    base.push({{ selector: 'node[nodeType="defined"]', style: {{ 'background-color': '#58a6ff', 'width': 60, 'height': 60 }} }});
    base.push({{ selector: 'node[nodeType="detected"]', style: {{ 'background-color': '#3fb950', 'width': 50, 'height': 50 }} }});
    base.push({{ selector: 'edge[edgeType="expected"]', style: {{ 'line-color': '#f0883e', 'target-arrow-color': '#f0883e', 'width': 2.5, 'line-style': 'dashed' }} }});
    base.push({{ selector: 'edge[edgeType="actual"]', style: {{ 'line-color': '#8b949e', 'width': 'mapData(weight, 1, 50, 1, 5)' }} }});
  }} else if (tab === 'code') {{
    base.push({{ selector: 'node[nodeType="function"]', style: {{ 'background-color': '#79c0ff', 'shape': 'ellipse' }} }});
    base.push({{ selector: 'node[nodeType="method"]', style: {{ 'background-color': '#79c0ff', 'shape': 'ellipse' }} }});
    base.push({{ selector: 'node[nodeType="class"]', style: {{ 'background-color': '#d2a8ff', 'shape': 'round-rectangle' }} }});
    base.push({{ selector: 'node[nodeType="module"]', style: {{ 'background-color': '#7ee787', 'shape': 'diamond', 'width': 30, 'height': 30 }} }});
  }}
  return base;
}}

function getLayout(tab) {{
  if (tab === 'system') return {{ name: 'circle', padding: 50, animate: false }};
  if (tab === 'subsystem') return {{ name: 'cose', padding: 40, animate: false, nodeRepulsion: 8000 }};
  return {{ name: 'cose', padding: 20, animate: false, nodeRepulsion: 4000, idealEdgeLength: 80 }};
}}

function legendItem(color, label) {{
  return '<div class="legend-item"><div class="legend-dot" style="background:' + color + '"></div>' + label + '</div>';
}}

function showNodeInfo(data, tab) {{
  const panel = document.getElementById('info-panel');
  const title = document.getElementById('info-title');
  const content = document.getElementById('info-content');
  panel.classList.add('visible');
  title.textContent = data.label || data.id;
  let html = '';
  if (data.id) html += field('ID', data.id);
  if (data.file) html += field('File', data.file);
  if (data.nodeType) html += field('Type', data.nodeType);
  if (data.intent) html += field('Intent', data.intent);
  if (data.description) html += field('Description', data.description);
  if (data.module) html += field('Module', data.module);
  if (data.count) html += field('Components', data.count);
  content.innerHTML = html;
}}

function field(label, value) {{
  return '<div class="field"><label>' + label + '</label><value>' +
         String(value).replace(/</g, '&lt;') + '</value></div>';
}}

initStats();
renderGraph('system');
</script>
</body>
</html>"""


def _escape_html(text: str) -> str:
    """Escape HTML special characters."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
