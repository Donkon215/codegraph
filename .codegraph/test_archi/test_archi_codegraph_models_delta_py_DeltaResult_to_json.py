"""Architecture test for codegraph/models/delta.py::DeltaResult::to_json."""
from codegraph.models.delta import DeltaResult

def test_archi_DeltaResult_to_json():
    obj = DeltaResult()
    obj.to_json()
