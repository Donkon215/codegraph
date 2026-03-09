"""Architecture test for codegraph/index.py::IndexStore::shortest_path."""
from codegraph.index import IndexStore

def test_archi_IndexStore_shortest_path():
    obj = IndexStore()
    obj.shortest_path("", "")
