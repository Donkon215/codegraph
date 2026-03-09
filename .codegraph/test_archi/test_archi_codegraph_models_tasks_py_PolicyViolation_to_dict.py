"""Architecture test for codegraph/models/tasks.py::PolicyViolation::to_dict."""
from codegraph.models.tasks import PolicyViolation

def test_archi_PolicyViolation_to_dict():
    obj = PolicyViolation()
    obj.to_dict()
