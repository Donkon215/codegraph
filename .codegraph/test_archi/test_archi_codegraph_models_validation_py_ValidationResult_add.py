"""Architecture test for codegraph/models/validation.py::ValidationResult::add."""
from codegraph.models.validation import ValidationResult

def test_archi_ValidationResult_add():
    obj = ValidationResult()
    obj.add("", "")
