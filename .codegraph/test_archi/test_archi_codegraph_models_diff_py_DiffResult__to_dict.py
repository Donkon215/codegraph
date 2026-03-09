"""Architecture test for codegraph/models/diff.py::DiffResult::_to_dict."""
from codegraph.models.diff import DiffResult

def test_archi_DiffResult__to_dict():
    obj = DiffResult()
    obj._to_dict()
