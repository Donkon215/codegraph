"""Architecture test for codegraph/models/suggested_workflow.py::SuggestedWorkflow::to_json."""
from codegraph.models.suggested_workflow import SuggestedWorkflow

def test_archi_SuggestedWorkflow_to_json():
    obj = SuggestedWorkflow()
    obj.to_json()
