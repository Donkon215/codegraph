"""Architecture test for codegraph/models/status.py::StatusReport::_to_dict."""
from codegraph.models.status import StatusReport

def test_archi_StatusReport__to_dict():
    obj = StatusReport()
    obj._to_dict()
