"""Architecture test for codegraph/index.py::IndexStore::close."""
from codegraph.index import IndexStore

def test_archi_IndexStore_close():
    obj = IndexStore()
    obj.close()
