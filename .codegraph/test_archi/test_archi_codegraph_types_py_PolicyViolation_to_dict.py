"""Architecture test for codegraph/types.py::PolicyViolation::to_dict."""
from codegraph.types import PolicyViolation

def test_archi_PolicyViolation_to_dict():
    obj = PolicyViolation()
    obj.to_dict()
