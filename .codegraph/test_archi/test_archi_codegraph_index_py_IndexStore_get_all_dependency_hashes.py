"""Architecture test for codegraph/index.py::IndexStore::get_all_dependency_hashes."""
from codegraph.index import IndexStore

def test_archi_IndexStore_get_all_dependency_hashes():
    obj = IndexStore()
    obj.get_all_dependency_hashes()
