"""Architecture test for codegraph/models/workflow.py::WorkflowEdge::is_dynamic."""
from codegraph.models.workflow import WorkflowEdge

def test_archi_WorkflowEdge_is_dynamic():
    obj = WorkflowEdge()
    obj.is_dynamic()
