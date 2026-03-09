"""Architecture test for codegraph/config.py::CodegraphConfig::to_dict."""
from codegraph.config import CodegraphConfig

def test_archi_CodegraphConfig_to_dict():
    obj = CodegraphConfig()
    obj.to_dict()
