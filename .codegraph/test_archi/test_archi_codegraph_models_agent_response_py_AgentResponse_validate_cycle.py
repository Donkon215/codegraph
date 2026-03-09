"""Architecture test for codegraph/models/agent_response.py::AgentResponse::validate_cycle."""
from codegraph.models.agent_response import AgentResponse

def test_archi_AgentResponse_validate_cycle():
    obj = AgentResponse()
    obj.validate_cycle(0)
