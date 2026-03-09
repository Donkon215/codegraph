"""Architecture test for codegraph/models/delta.py::DeltaResult::from_json."""
from codegraph.models.delta import DeltaResult

def test_archi_DeltaResult_from_json():
    obj = DeltaResult()
    obj.from_json("")
