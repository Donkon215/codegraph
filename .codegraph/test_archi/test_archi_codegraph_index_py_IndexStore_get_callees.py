"""Architecture test for codegraph/index.py::IndexStore::get_callees."""
from codegraph.index import IndexStore

def test_archi_IndexStore_get_callees():
    obj = IndexStore()
    obj.get_callees("")
