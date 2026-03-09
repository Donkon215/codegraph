"""Architecture test for codegraph/models/agent_response.py::RepairAction::to_dict."""
from codegraph.models.agent_response import RepairAction

def test_archi_RepairAction_to_dict():
    obj = RepairAction()
    obj.to_dict()
