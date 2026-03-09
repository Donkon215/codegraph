"""Architecture test for codegraph/models/agent_response.py::AgentResponse::to_json."""
from codegraph.models.agent_response import AgentResponse

def test_archi_AgentResponse_to_json():
    obj = AgentResponse()
    obj.to_json()
