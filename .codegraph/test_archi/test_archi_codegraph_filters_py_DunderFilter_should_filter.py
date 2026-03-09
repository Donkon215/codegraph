"""Architecture test for codegraph/filters.py::DunderFilter::should_filter."""
from codegraph.filters import DunderFilter

def test_archi_DunderFilter_should_filter():
    obj = DunderFilter()
    obj.should_filter("", "", None  # TODO: provide value)
