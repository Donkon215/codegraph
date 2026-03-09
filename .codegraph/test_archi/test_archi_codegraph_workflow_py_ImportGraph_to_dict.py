"""Architecture test for codegraph/workflow.py::ImportGraph::to_dict."""
from codegraph.workflow import ImportGraph

def test_archi_ImportGraph_to_dict():
    obj = ImportGraph()
    obj.to_dict()
