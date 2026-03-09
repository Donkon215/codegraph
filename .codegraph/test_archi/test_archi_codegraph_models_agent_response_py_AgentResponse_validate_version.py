"""Architecture test for codegraph/models/agent_response.py::AgentResponse::validate_version."""
from codegraph.models.agent_response import AgentResponse

def test_archi_AgentResponse_validate_version():
    obj = AgentResponse()
    obj.validate_version(0)
