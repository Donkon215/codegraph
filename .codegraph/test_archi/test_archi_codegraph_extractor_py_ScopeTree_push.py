"""Architecture test for codegraph/extractor.py::ScopeTree::push."""
from codegraph.extractor import ScopeTree

def test_archi_ScopeTree_push():
    obj = ScopeTree()
    obj.push("", "")
