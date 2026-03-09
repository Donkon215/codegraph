"""Architecture test for codegraph/models/explain.py::ExplainResult::to_json."""
from codegraph.models.explain import ExplainResult

def test_archi_ExplainResult_to_json():
    obj = ExplainResult()
    obj.to_json()
