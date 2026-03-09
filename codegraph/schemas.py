"""codegraph.schemas — JSON-schema validation helpers.

Covers tasks A-014, A-029 (format-version checking).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from codegraph.constants import CURRENT_FORMAT_VERSION
from codegraph.logging_config import get_logger

logger = get_logger("schemas")


# ═══════════════════════════════════════════════════════════════════════
# Lightweight validation helpers (no jsonschema dependency required)
# ═══════════════════════════════════════════════════════════════════════


class ValidationError(Exception):
    """One or more fields failed validation."""

    def __init__(self, errors: List[str]) -> None:
        self.errors = errors
        super().__init__(f"Validation failed: {'; '.join(errors)}")


def _require(data: Dict[str, Any], field: str, expected_type: type) -> Optional[str]:
    """Return an error string if *field* is missing or wrong type."""
    if field not in data:
        return f"missing required field '{field}'"
    if not isinstance(data[field], expected_type):
        return f"field '{field}' must be {expected_type.__name__}, got {type(data[field]).__name__}"
    return None


def validate_graph0_node(data: Dict[str, Any]) -> List[str]:
    """Validate a single Graph_0 node dict."""
    errors: List[str] = []
    for field, typ in [("id", str), ("body_hash", str), ("file", str), ("type", str), ("line", int)]:
        err = _require(data, field, typ)
        if err:
            errors.append(err)
    if data.get("type") and data["type"] not in ("function", "class", "method", "module"):
        errors.append(f"invalid node type: '{data['type']}'")
    return errors


def validate_graph1_node(data: Dict[str, Any]) -> List[str]:
    """Validate a single Graph_1 node dict."""
    errors: List[str] = []
    err = _require(data, "id", str)
    if err:
        errors.append(err)
    if "layer" in data and not isinstance(data["layer"], int):
        errors.append("'layer' must be int")
    return errors


def validate_workflow_edge(data: Dict[str, Any]) -> List[str]:
    """Validate a single Workflow edge dict."""
    errors: List[str] = []
    for field in ("source", "target"):
        err = _require(data, field, str)
        if err:
            errors.append(err)
    return errors


def validate_graph0(data: Dict[str, Any]) -> List[str]:
    """Validate a full graph0.json structure."""
    errors: List[str] = []
    if "format_version" in data:
        fv = data["format_version"]
        if not isinstance(fv, int):
            errors.append("'format_version' must be int")
        elif fv != CURRENT_FORMAT_VERSION:
            errors.append(f"unsupported format_version {fv} (expected {CURRENT_FORMAT_VERSION})")
    nodes = data.get("nodes")
    if nodes is None:
        errors.append("missing 'nodes' list")
    elif isinstance(nodes, list):
        for i, node in enumerate(nodes):
            for err in validate_graph0_node(node):
                errors.append(f"nodes[{i}]: {err}")
    return errors


def validate_graph1(data: Dict[str, Any]) -> List[str]:
    """Validate a full graph1.json structure."""
    errors: List[str] = []
    nodes = data.get("nodes")
    if nodes is None:
        errors.append("missing 'nodes' list")
    elif isinstance(nodes, list):
        for i, node in enumerate(nodes):
            for err in validate_graph1_node(node):
                errors.append(f"nodes[{i}]: {err}")
    return errors


def validate_workflow(data: Dict[str, Any]) -> List[str]:
    """Validate a full workflow.json structure."""
    errors: List[str] = []
    edges = data.get("edges")
    if edges is None:
        errors.append("missing 'edges' list")
    elif isinstance(edges, list):
        for i, edge in enumerate(edges):
            for err in validate_workflow_edge(edge):
                errors.append(f"edges[{i}]: {err}")
    return errors


def validate_tasks(data: Dict[str, Any]) -> List[str]:
    """Validate a tasks.json structure."""
    errors: List[str] = []
    err = _require(data, "graph_version", int)
    if err:
        errors.append(err)
    err = _require(data, "cycle", int)
    if err:
        errors.append(err)
    tasks = data.get("tasks")
    if tasks is None:
        errors.append("missing 'tasks' list")
    elif isinstance(tasks, list):
        for i, t in enumerate(tasks):
            for field in ("task_id", "category", "description", "target_node"):
                e = _require(t, field, str)
                if e:
                    errors.append(f"tasks[{i}]: {e}")
    return errors


def validate_agent_response(data: Dict[str, Any]) -> List[str]:
    """Validate an agent_response.json structure."""
    errors: List[str] = []
    err = _require(data, "graph_version", int)
    if err:
        errors.append(err)
    err = _require(data, "cycle", int)
    if err:
        errors.append(err)
    actions = data.get("actions")
    if actions is None:
        errors.append("missing 'actions' list")
    elif isinstance(actions, list):
        for i, a in enumerate(actions):
            e = _require(a, "action_type", str)
            if e:
                errors.append(f"actions[{i}]: {e}")
            e = _require(a, "target_node", str)
            if e:
                errors.append(f"actions[{i}]: {e}")
    return errors


def validate_delta(data: Dict[str, Any]) -> List[str]:
    """Validate a delta.json structure."""
    errors: List[str] = []
    err = _require(data, "graph_version", int)
    if err:
        errors.append(err)
    return errors


def validate_suggested_workflow(data: Dict[str, Any]) -> List[str]:
    """Validate a suggested_workflow.json structure."""
    errors: List[str] = []
    rules = data.get("rules")
    if rules is None:
        errors.append("missing 'rules' list")
    elif isinstance(rules, list):
        for i, r in enumerate(rules):
            e = _require(r, "rule_id", str)
            if e:
                errors.append(f"rules[{i}]: {e}")
    return errors
