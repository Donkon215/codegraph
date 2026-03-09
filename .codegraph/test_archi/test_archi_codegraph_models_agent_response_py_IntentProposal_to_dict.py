"""Architecture test for codegraph/models/agent_response.py::IntentProposal::to_dict."""
from codegraph.models.agent_response import IntentProposal

def test_archi_IntentProposal_to_dict():
    obj = IntentProposal()
    obj.to_dict()
