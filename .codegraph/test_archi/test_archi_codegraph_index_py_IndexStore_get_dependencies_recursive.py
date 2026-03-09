"""Architecture test for codegraph/index.py::IndexStore::get_dependencies_recursive."""
from codegraph.index import IndexStore

def test_archi_IndexStore_get_dependencies_recursive():
    obj = IndexStore()
    obj.get_dependencies_recursive("")
