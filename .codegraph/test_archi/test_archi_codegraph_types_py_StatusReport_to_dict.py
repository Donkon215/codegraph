"""Architecture test for codegraph/types.py::StatusReport::to_dict."""
from codegraph.types import StatusReport

def test_archi_StatusReport_to_dict():
    obj = StatusReport()
    obj.to_dict()
