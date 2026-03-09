"""Architecture test for codegraph/filters.py::EdgeFilter::should_filter."""
from codegraph.filters import EdgeFilter

def test_archi_EdgeFilter_should_filter():
    obj = EdgeFilter()
    obj.should_filter("", "", None  # TODO: provide value)
