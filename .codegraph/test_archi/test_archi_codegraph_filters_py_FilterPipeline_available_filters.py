"""Architecture test for codegraph/filters.py::FilterPipeline::available_filters."""
from codegraph.filters import FilterPipeline

def test_archi_FilterPipeline_available_filters():
    obj = FilterPipeline()
    obj.available_filters()
