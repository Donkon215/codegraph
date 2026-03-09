"""Architecture test for codegraph/index.py::IndexStore::get_node."""
from codegraph.index import IndexStore

def test_archi_IndexStore_get_node():
    obj = IndexStore()
    obj.get_node("")
