"""codegraph.models.validation — Unified model validation pipeline.

Task B-035.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional

from codegraph.logging_config import get_logger
from codegraph.models.agent_response import AgentResponse, RepairActionType
from codegraph.models.graph0 import Graph0, Graph0Node, NodeType
from codegraph.models.graph1 import Graph1, Graph1Node, validate_intent
from codegraph.models.tasks import TaskBatch
from codegraph.models.workflow import Workflow, WorkflowEdge

logger = get_logger("models.validation")


@dataclass
class ValidationError:
    """A single validation finding."""

    field_path: str
    message: str
    severity: str = "error"  # error | warning


@dataclass
class ValidationResult:
    """Aggregated validation outcome."""

    errors: List[ValidationError] = field(default_factory=list)
    warnings: List[ValidationError] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0

    def add(self, field_path: str, message: str, *, severity: str = "error") -> None:
        ve = ValidationError(field_path=field_path, message=message, severity=severity)
        if severity == "warning":
            self.warnings.append(ve)
        else:
            self.errors.append(ve)


def validate(model: Any, *, strict: bool = True) -> ValidationResult:
    """Validate any model instance.

    Parameters
    ----------
    model:
        A model instance (Graph0, Graph1, Workflow, AgentResponse, etc.).
    strict:
        If True, reference violations are errors; if False, they are warnings.
    """
    result = ValidationResult()

    if isinstance(model, Graph0):
        _validate_graph0(model, result, strict)
    elif isinstance(model, Graph0Node):
        _validate_graph0_node(model, result)
    elif isinstance(model, Graph1):
        _validate_graph1(model, result, strict)
    elif isinstance(model, Graph1Node):
        _validate_graph1_node(model, result)
    elif isinstance(model, Workflow):
        _validate_workflow(model, result)
    elif isinstance(model, WorkflowEdge):
        _validate_workflow_edge(model, result)
    elif isinstance(model, AgentResponse):
        _validate_agent_response(model, result, strict)
    elif isinstance(model, TaskBatch):
        _validate_task_batch(model, result)
    else:
        result.add("", f"Unknown model type: {type(model).__name__}")

    return result


# ── Internal validators ───────────────────────────────────────────────


def _validate_graph0_node(node: Graph0Node, result: ValidationResult) -> None:
    if not node.id:
        result.add("id", "Node ID is empty")
    if not node.body_hash:
        # Modules may have empty body hash
        if node.type != NodeType.MODULE.value:
            result.add("body_hash", f"body_hash is empty for non-module node '{node.id}'", severity="warning")
    if not node.file:
        result.add("file", f"file is empty for node '{node.id}'")
    try:
        NodeType(node.type)
    except ValueError:
        result.add("type", f"Invalid node type '{node.type}' for node '{node.id}'")


def _validate_graph0(graph0: Graph0, result: ValidationResult, strict: bool) -> None:
    if graph0.format_version < 1:
        result.add("format_version", "format_version must be >= 1")
    seen_ids: set[str] = set()
    for i, node in enumerate(graph0.nodes):
        _validate_graph0_node(node, result)
        if node.id in seen_ids:
            sev = "error" if strict else "warning"
            result.add(f"nodes[{i}].id", f"Duplicate node ID '{node.id}'", severity=sev)
        seen_ids.add(node.id)


def _validate_graph1_node(node: Graph1Node, result: ValidationResult) -> None:
    if not node.id:
        result.add("id", "Node ID is empty")
    if node.intent:
        ok, warnings = validate_intent(node.intent)
        for w in warnings:
            result.add("intent", w, severity="warning")
    if not (0 <= node.layer <= 4):
        result.add("layer", f"Invalid layer {node.layer} for node '{node.id}'")


def _validate_graph1(graph1: Graph1, result: ValidationResult, strict: bool) -> None:
    for i, node in enumerate(graph1.nodes):
        _validate_graph1_node(node, result)


def _validate_workflow_edge(edge: WorkflowEdge, result: ValidationResult) -> None:
    if not edge.source:
        result.add("source", "Edge source is empty")
    if not edge.target:
        result.add("target", "Edge target is empty")


def _validate_workflow(workflow: Workflow, result: ValidationResult) -> None:
    for i, edge in enumerate(workflow.edges):
        _validate_workflow_edge(edge, result)


def _validate_agent_response(resp: AgentResponse, result: ValidationResult, strict: bool) -> None:
    for i, repair in enumerate(resp.repairs):
        try:
            RepairActionType(repair.action)
        except ValueError:
            result.add(f"repairs[{i}].action", f"Unknown repair action '{repair.action}'")


def _validate_task_batch(batch: TaskBatch, result: ValidationResult) -> None:
    if batch.cycle < 1:
        result.add("cycle", "cycle must be >= 1")
    if batch.graph_version < 1:
        result.add("graph_version", "graph_version must be >= 1")
