"""Architecture test for codegraph/index.py::IndexStore::_get_conn."""
from codegraph.index import IndexStore

def test_archi_IndexStore__get_conn():
    obj = IndexStore()
    obj._get_conn()
