"""Architecture test for codegraph/index.py::IndexStore::get_orphans."""
from codegraph.index import IndexStore

def test_archi_IndexStore_get_orphans():
    obj = IndexStore()
    obj.get_orphans()
