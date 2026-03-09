"""Architecture test for codegraph/index.py::IndexStore::get_callers."""
from codegraph.index import IndexStore

def test_archi_IndexStore_get_callers():
    obj = IndexStore()
    obj.get_callers("")
