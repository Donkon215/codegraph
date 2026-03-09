"""Architecture test for codegraph/types.py::WorkflowEdge::to_dict."""
from codegraph.types import WorkflowEdge

def test_archi_WorkflowEdge_to_dict():
    obj = WorkflowEdge()
    obj.to_dict()
