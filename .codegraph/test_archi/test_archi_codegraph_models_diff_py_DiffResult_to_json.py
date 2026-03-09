"""Architecture test for codegraph/models/diff.py::DiffResult::to_json."""
from codegraph.models.diff import DiffResult

def test_archi_DiffResult_to_json():
    obj = DiffResult()
    obj.to_json()
