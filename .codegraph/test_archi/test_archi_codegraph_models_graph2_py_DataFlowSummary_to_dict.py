"""Architecture test for codegraph/models/graph2.py::DataFlowSummary::to_dict."""
from codegraph.models.graph2 import DataFlowSummary

def test_archi_DataFlowSummary_to_dict():
    obj = DataFlowSummary()
    obj.to_dict()
