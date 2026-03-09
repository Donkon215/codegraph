"""Architecture test for codegraph/models/workflow.py::Workflow::from_json."""
from codegraph.models.workflow import Workflow

def test_archi_Workflow_from_json():
    obj = Workflow()
    obj.from_json("")
