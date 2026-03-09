"""Architecture test for codegraph/filters.py::StdlibFilter::should_filter."""
from codegraph.filters import StdlibFilter

def test_archi_StdlibFilter_should_filter():
    obj = StdlibFilter()
    obj.should_filter("", "", None  # TODO: provide value)
