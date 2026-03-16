from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from codegraph.models.workflow import Workflow, WorkflowEdge


def enrich_workflow_with_context_flows(project_root: Path, workflow: Workflow) -> Workflow:
    graph2_path = project_root / ".codegraph" / "graphs" / "graph2.json"
    if not graph2_path.exists():
        return workflow

    try:
        graph2 = json.loads(graph2_path.read_text(encoding="utf-8"))
    except Exception:
        return workflow

    existing = {(e.source, e.target, e.edge_type, e.confidence) for e in workflow.edges}

    for node in graph2.get("nodes", []):
        nid = node.get("id", "")
        if not nid:
            continue

        for action in node.get("actions", []):
            target = action.get("target") or action.get("name") or ""
            if not target:
                continue
            edge = WorkflowEdge(
                source=nid,
                target=target if "::" in target else f"{nid.split('::', 1)[0]}::{target}",
                edge_type="control_flow",
                confidence="ai_inferred",
                source_detail="graph2:actions",
            )
            key = (edge.source, edge.target, edge.edge_type, edge.confidence)
            if key not in existing:
                existing.add(key)
                workflow.edges.append(edge)

        if node.get("data_flow"):
            df = node["data_flow"]
            for out in df.get("outputs", []):
                edge = WorkflowEdge(
                    source=nid,
                    target=f"{nid.split('::', 1)[0]}::{out}",
                    edge_type="data_flow",
                    confidence="ai_inferred",
                    source_detail="graph2:data_flow",
                )
                key = (edge.source, edge.target, edge.edge_type, edge.confidence)
                if key not in existing:
                    existing.add(key)
                    workflow.edges.append(edge)

        for se in node.get("side_effects", []):
            target = se.get("target") or se.get("effect_type") or "external"
            edge = WorkflowEdge(
                source=nid,
                target=f"external::{target}",
                edge_type="side_effect",
                confidence="ai_inferred",
                source_detail="graph2:side_effects",
            )
            key = (edge.source, edge.target, edge.edge_type, edge.confidence)
            if key not in existing:
                existing.add(key)
                workflow.edges.append(edge)

    workflow._rebuild_indexes()
    return workflow
