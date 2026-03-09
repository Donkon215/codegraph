"""Architecture test for codegraph/filters.py::LoggingFilter::should_filter."""
from codegraph.filters import LoggingFilter

def test_archi_LoggingFilter_should_filter():
    obj = LoggingFilter()
    obj.should_filter("", "", None  # TODO: provide value)
