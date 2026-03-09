"""Architecture test for codegraph/index.py::IndexStore::search_nodes."""
from codegraph.index import IndexStore

def test_archi_IndexStore_search_nodes():
    obj = IndexStore()
    obj.search_nodes("")
