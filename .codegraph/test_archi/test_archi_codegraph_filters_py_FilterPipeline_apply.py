"""Architecture test for codegraph/filters.py::FilterPipeline::apply."""
from codegraph.filters import FilterPipeline

def test_archi_FilterPipeline_apply():
    obj = FilterPipeline()
    obj.apply([])
