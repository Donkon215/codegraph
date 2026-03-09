"""Architecture test for codegraph/models/suggested_workflow.py::SuggestedWorkflow::remove_rule."""
from codegraph.models.suggested_workflow import SuggestedWorkflow

def test_archi_SuggestedWorkflow_remove_rule():
    obj = SuggestedWorkflow()
    obj.remove_rule("")
