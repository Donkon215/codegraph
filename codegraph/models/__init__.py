"""codegraph.models — Data models, schemas, enums, and serialization.

Tasks B-033 (serialization registry), B-044 (Graph2 re-export).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Type, TypeVar

from codegraph.constants import (
    CODEGRAPH_DIR,
    DELTA_FILE,
    GRAPH0_FILE,
    GRAPH1_FILE,
    GRAPH2_FILE,
    GRAPHS_DIR,
    SUGGESTED_WORKFLOW_FILE,
    WORKFLOW_DIR,
    WORKFLOW_FILE,
)

# ── Re-exports ─────────────────────────────────────────────────────────

from codegraph.models.graph0 import CollisionResolver, Graph0, Graph0Node, NodeType
from codegraph.models.graph1 import Graph1, Graph1Node, validate_intent
from codegraph.models.workflow import (
    Confidence,
    EdgeType,
    Workflow,
    WorkflowEdge,
    WorkflowLevel,
    compare_edges,
    deduplicate_edges,
)
from codegraph.models.suggested_workflow import (
    RuleType,
    SuggestedWorkflow,
    SuggestedWorkflowRule,
)
from codegraph.models.tasks import (
    PolicyViolation,
    SuggestedFix,
    TaskBatch,
    TaskID,
    TaskItem,
    TaskNode,
    TestChangeType,
)
from codegraph.models.agent_response import (
    AgentResponse,
    IntentProposal,
    RepairAction,
    RepairActionType,
    WorkflowSuggestion,
)
from codegraph.models.delta import DeltaResult
from codegraph.models.status import StatusReport
from codegraph.models.explain import ExplainResult
from codegraph.models.diff import DiffResult
from codegraph.models.alignment import AlignmentReport, check_alignment
from codegraph.models.dead_code import DeadCodeSignals
from codegraph.models.convergence import ConvergenceState
from codegraph.models.graph2 import (
    DataFlowSummary,
    Graph2,
    Graph2Node,
    SemanticAction,
    SideEffect,
)

__all__ = [
    # graph0
    "Graph0",
    "Graph0Node",
    "NodeType",
    "CollisionResolver",
    # graph1
    "Graph1",
    "Graph1Node",
    "validate_intent",
    # workflow
    "Workflow",
    "WorkflowEdge",
    "EdgeType",
    "Confidence",
    "WorkflowLevel",
    "compare_edges",
    "deduplicate_edges",
    # suggested workflow
    "SuggestedWorkflow",
    "SuggestedWorkflowRule",
    "RuleType",
    # tasks
    "TaskBatch",
    "TaskItem",
    "TaskNode",
    "PolicyViolation",
    "TaskID",
    "TestChangeType",
    "SuggestedFix",
    # agent response
    "AgentResponse",
    "IntentProposal",
    "RepairAction",
    "RepairActionType",
    "WorkflowSuggestion",
    # delta
    "DeltaResult",
    # status / explain / diff
    "StatusReport",
    "ExplainResult",
    "DiffResult",
    # alignment
    "AlignmentReport",
    "check_alignment",
    # dead code
    "DeadCodeSignals",
    # convergence
    "ConvergenceState",
    # graph2
    "Graph2",
    "Graph2Node",
    "SemanticAction",
    "SideEffect",
    "DataFlowSummary",
    # registry
    "load_model",
    "save_model",
]


# ── B-033  Serialization registry ──────────────────────────────────────

_T = TypeVar("_T")

# Maps (model_type_name -> (relative_path, class))
_REGISTRY: Dict[str, tuple[str, type]] = {
    "graph0": (f"{GRAPHS_DIR}/{GRAPH0_FILE}", Graph0),
    "graph1": (f"{GRAPHS_DIR}/{GRAPH1_FILE}", Graph1),
    "graph2": (f"{GRAPHS_DIR}/{GRAPH2_FILE}", Graph2),
    "workflow": (f"{WORKFLOW_DIR}/{WORKFLOW_FILE}", Workflow),
    "suggested_workflow": (f"{WORKFLOW_DIR}/{SUGGESTED_WORKFLOW_FILE}", SuggestedWorkflow),
    "delta": (f"{GRAPHS_DIR}/{DELTA_FILE}", DeltaResult),
}


def _resolve(model_type: str, project_root: Path) -> Path:
    if model_type not in _REGISTRY:
        raise ValueError(f"Unknown model type '{model_type}'. Known: {list(_REGISTRY)}")
    rel, _ = _REGISTRY[model_type]
    return project_root / CODEGRAPH_DIR / rel


def load_model(model_type: str, project_root: Path) -> Any:
    """Load a model from disk by type name."""
    fp = _resolve(model_type, project_root)
    if not fp.exists():
        return None
    _, cls = _REGISTRY[model_type]
    text = fp.read_text(encoding="utf-8")
    return cls.from_json(text)


def save_model(model: Any, project_root: Path, model_type: Optional[str] = None) -> Path:
    """Save *model* to its canonical location.

    *model_type* is inferred from the instance class if not given.
    """
    if model_type is None:
        for name, (_, cls) in _REGISTRY.items():
            if isinstance(model, cls):
                model_type = name
                break
    if model_type is None:
        raise ValueError(f"Cannot infer model type for {type(model).__name__}")
    fp = _resolve(model_type, project_root)
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(model.to_json(), encoding="utf-8")
    return fp
