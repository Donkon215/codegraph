"""Architecture test for codegraph/models/status.py::StatusReport::to_text."""
from codegraph.models.status import StatusReport

def test_archi_StatusReport_to_text():
    obj = StatusReport()
    obj.to_text()
