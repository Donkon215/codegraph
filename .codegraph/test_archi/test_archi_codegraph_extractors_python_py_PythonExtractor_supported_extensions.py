"""Architecture test for codegraph/extractors/python.py::PythonExtractor::supported_extensions."""
from codegraph.extractors.python import PythonExtractor

def test_archi_PythonExtractor_supported_extensions():
    obj = PythonExtractor()
    obj.supported_extensions()
