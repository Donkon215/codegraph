"""Architecture test for codegraph/models/status.py::StatusReport::to_json."""
from codegraph.models.status import StatusReport

def test_archi_StatusReport_to_json():
    obj = StatusReport()
    obj.to_json()
