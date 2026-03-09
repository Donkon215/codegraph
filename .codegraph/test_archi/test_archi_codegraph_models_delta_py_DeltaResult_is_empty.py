"""Architecture test for codegraph/models/delta.py::DeltaResult::is_empty."""
from codegraph.models.delta import DeltaResult

def test_archi_DeltaResult_is_empty():
    obj = DeltaResult()
    obj.is_empty()
