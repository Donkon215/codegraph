"""Architecture test for codegraph/models/workflow.py::Workflow::remove_edge."""
from codegraph.models.workflow import Workflow

def test_archi_Workflow_remove_edge():
    obj = Workflow()
    obj.remove_edge("", "")
