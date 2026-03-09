"""Architecture test for codegraph/models/workflow.py::WorkflowEdge::to_dict."""
from codegraph.models.workflow import WorkflowEdge

def test_archi_WorkflowEdge_to_dict():
    obj = WorkflowEdge()
    obj.to_dict()
