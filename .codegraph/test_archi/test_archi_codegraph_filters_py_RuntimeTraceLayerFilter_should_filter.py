"""Architecture test for codegraph/filters.py::RuntimeTraceLayerFilter::should_filter."""
from codegraph.filters import RuntimeTraceLayerFilter

def test_archi_RuntimeTraceLayerFilter_should_filter():
    obj = RuntimeTraceLayerFilter()
    obj.should_filter("", "", None  # TODO: provide value)
