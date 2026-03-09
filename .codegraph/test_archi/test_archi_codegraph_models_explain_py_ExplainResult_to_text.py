"""Architecture test for codegraph/models/explain.py::ExplainResult::to_text."""
from codegraph.models.explain import ExplainResult

def test_archi_ExplainResult_to_text():
    obj = ExplainResult()
    obj.to_text()
