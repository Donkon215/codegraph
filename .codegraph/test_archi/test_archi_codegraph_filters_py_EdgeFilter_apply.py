"""Architecture test for codegraph/filters.py::EdgeFilter::apply."""
from codegraph.filters import EdgeFilter

def test_archi_EdgeFilter_apply():
    obj = EdgeFilter()
    obj.apply([])
