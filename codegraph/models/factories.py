"""codegraph.models.factories — Convenience builders for model instances.

Task B-030.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from codegraph.models.agent_response import (
    AgentResponse,
    IntentProposal,
    RepairAction,
    WorkflowSuggestion,
)
from codegraph.models.graph0 import Graph0Node
from codegraph.models.graph1 import Graph1Node
from codegraph.models.suggested_workflow import SuggestedWorkflowRule
from codegraph.models.tasks import TaskItem, TaskNode
from codegraph.models.workflow import WorkflowEdge
from codegraph.utils.formatting import iso_now


def make_graph0_node(
    id: str,
    file: str,
    type: str = "function",
    *,
    body_hash: str = "00000",
    line: int = 1,
    dependency_hash: Optional[str] = None,
) -> Graph0Node:
    """Create a :class:`Graph0Node` with sensible defaults."""
    return Graph0Node(
        id=id,
        body_hash=body_hash,
        file=file,
        type=type,
        line=line,
        dependency_hash=dependency_hash,
    )


def make_graph1_node(
    id: str,
    intent: str = "",
    layer: int = 3,
    *,
    arch_layer: Optional[str] = None,
    intent_author: str = "factory",
    tags: Optional[List[str]] = None,
) -> Graph1Node:
    """Create a :class:`Graph1Node` with sensible defaults."""
    return Graph1Node(
        id=id,
        intent=intent,
        layer=layer,
        arch_layer=arch_layer,
        intent_author=intent_author,
        intent_version=1,
        intent_timestamp=iso_now(),
        tags=tags or [],
    )


def make_workflow_edge(
    source: str,
    target: str,
    *,
    edge_type: str = "call",
    confidence: str = "static",
) -> WorkflowEdge:
    """Create a :class:`WorkflowEdge` with sensible defaults."""
    return WorkflowEdge(
        source=source,
        target=target,
        edge_type=edge_type,
        confidence=confidence,
    )


def make_task(
    task_id: str,
    *,
    priority: int = 5,
    nodes: Optional[List[Dict[str, Any]]] = None,
    violations: Optional[List[Dict[str, Any]]] = None,
) -> TaskItem:
    """Create a :class:`TaskItem` from optional raw dicts."""
    node_objs = [TaskNode.from_dict(n) for n in nodes] if nodes else None
    from codegraph.models.tasks import PolicyViolation

    viol_objs = [PolicyViolation.from_dict(v) for v in violations] if violations else None
    return TaskItem(task_id=task_id, priority=priority, nodes=node_objs, violations=viol_objs)


def make_rule(
    type: str,
    source: str,
    target: str,
    reason: str = "",
    *,
    added_by: str = "factory",
) -> SuggestedWorkflowRule:
    """Create a :class:`SuggestedWorkflowRule` with sensible defaults."""
    return SuggestedWorkflowRule(
        type=type,
        source=source,
        target=target,
        reason=reason,
        added_by=added_by,
    )
