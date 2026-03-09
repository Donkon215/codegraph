"""Architecture test for codegraph/extractor.py::ExtractionCache::invalidate."""
from codegraph.extractor import ExtractionCache

def test_archi_ExtractionCache_invalidate():
    obj = ExtractionCache()
    obj.invalidate(None  # TODO: provide value)
