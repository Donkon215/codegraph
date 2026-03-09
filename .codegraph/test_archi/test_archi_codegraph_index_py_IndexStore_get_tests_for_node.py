"""Architecture test for codegraph/index.py::IndexStore::get_tests_for_node."""
from codegraph.index import IndexStore

def test_archi_IndexStore_get_tests_for_node():
    obj = IndexStore()
    obj.get_tests_for_node("")
