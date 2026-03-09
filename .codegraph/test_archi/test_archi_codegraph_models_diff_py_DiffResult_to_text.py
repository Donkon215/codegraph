"""Architecture test for codegraph/models/diff.py::DiffResult::to_text."""
from codegraph.models.diff import DiffResult

def test_archi_DiffResult_to_text():
    obj = DiffResult()
    obj.to_text()
