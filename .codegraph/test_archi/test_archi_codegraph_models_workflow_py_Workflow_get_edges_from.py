"""Architecture test for codegraph/models/workflow.py::Workflow::get_edges_from."""
from codegraph.models.workflow import Workflow

def test_archi_Workflow_get_edges_from():
    obj = Workflow()
    obj.get_edges_from("")
