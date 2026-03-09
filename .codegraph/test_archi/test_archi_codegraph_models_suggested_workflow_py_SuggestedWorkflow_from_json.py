"""Architecture test for codegraph/models/suggested_workflow.py::SuggestedWorkflow::from_json."""
from codegraph.models.suggested_workflow import SuggestedWorkflow

def test_archi_SuggestedWorkflow_from_json():
    obj = SuggestedWorkflow()
    obj.from_json("")
