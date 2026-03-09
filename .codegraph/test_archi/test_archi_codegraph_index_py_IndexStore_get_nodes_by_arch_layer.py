"""Architecture test for codegraph/index.py::IndexStore::get_nodes_by_arch_layer."""
from codegraph.index import IndexStore

def test_archi_IndexStore_get_nodes_by_arch_layer():
    obj = IndexStore()
    obj.get_nodes_by_arch_layer("")
