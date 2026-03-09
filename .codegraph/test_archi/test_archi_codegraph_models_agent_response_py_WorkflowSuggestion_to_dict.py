"""Architecture test for codegraph/models/agent_response.py::WorkflowSuggestion::to_dict."""
from codegraph.models.agent_response import WorkflowSuggestion

def test_archi_WorkflowSuggestion_to_dict():
    obj = WorkflowSuggestion()
    obj.to_dict()
