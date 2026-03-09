"""Architecture test for codegraph/extractor.py::ScopeTree::bind."""
from codegraph.extractor import ScopeTree

def test_archi_ScopeTree_bind():
    obj = ScopeTree()
    obj.bind("", "")
