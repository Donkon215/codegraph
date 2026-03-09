"""Architecture test for codegraph/models/agent_response.py::AgentResponse::from_json."""
from codegraph.models.agent_response import AgentResponse

def test_archi_AgentResponse_from_json():
    obj = AgentResponse()
    obj.from_json("")
