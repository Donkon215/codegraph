"""Architecture test for codegraph/models/suggested_workflow.py::RuleType::is_violation."""
from codegraph.models.suggested_workflow import RuleType

def test_archi_RuleType_is_violation():
    obj = RuleType()
    obj.is_violation(False)
