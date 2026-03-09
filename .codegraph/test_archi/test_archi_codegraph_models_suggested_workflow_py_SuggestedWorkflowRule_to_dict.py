"""Architecture test for codegraph/models/suggested_workflow.py::SuggestedWorkflowRule::to_dict."""
from codegraph.models.suggested_workflow import SuggestedWorkflowRule

def test_archi_SuggestedWorkflowRule_to_dict():
    obj = SuggestedWorkflowRule()
    obj.to_dict()
