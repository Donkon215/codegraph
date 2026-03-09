"""Architecture test for codegraph/models/suggested_workflow.py::SuggestedWorkflow::get_rule."""
from codegraph.models.suggested_workflow import SuggestedWorkflow

def test_archi_SuggestedWorkflow_get_rule():
    obj = SuggestedWorkflow()
    obj.get_rule("")
