"""Architecture test for codegraph/models/workflow.py::Workflow::to_json."""
from codegraph.models.workflow import Workflow

def test_archi_Workflow_to_json():
    obj = Workflow()
    obj.to_json()
