"""Architecture test for codegraph/index.py::IndexStore::get_nodes_by_file."""
from codegraph.index import IndexStore

def test_archi_IndexStore_get_nodes_by_file():
    obj = IndexStore()
    obj.get_nodes_by_file("")
