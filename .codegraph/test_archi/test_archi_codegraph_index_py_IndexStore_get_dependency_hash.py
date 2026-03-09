"""Architecture test for codegraph/index.py::IndexStore::get_dependency_hash."""
from codegraph.index import IndexStore

def test_archi_IndexStore_get_dependency_hash():
    obj = IndexStore()
    obj.get_dependency_hash("")
