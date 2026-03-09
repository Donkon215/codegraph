"""Architecture test for codegraph/models/agent_response.py::RepairActionType::modifies_code."""
from codegraph.models.agent_response import RepairActionType

def test_archi_RepairActionType_modifies_code():
    obj = RepairActionType()
    obj.modifies_code()
