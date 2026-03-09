"""Architecture test for codegraph/index.py::IndexStore::get_nodes_at_layer."""
from codegraph.index import IndexStore

def test_archi_IndexStore_get_nodes_at_layer():
    obj = IndexStore()
    obj.get_nodes_at_layer(0)
