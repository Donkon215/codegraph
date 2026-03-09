"""Architecture test for codegraph/models/explain.py::ExplainResult::_to_dict."""
from codegraph.models.explain import ExplainResult

def test_archi_ExplainResult__to_dict():
    obj = ExplainResult()
    obj._to_dict()
