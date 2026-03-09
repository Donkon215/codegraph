"""Architecture test for codegraph/filters.py::DataclassFilter::should_filter."""
from codegraph.filters import DataclassFilter

def test_archi_DataclassFilter_should_filter():
    obj = DataclassFilter()
    obj.should_filter("", "", None  # TODO: provide value)
