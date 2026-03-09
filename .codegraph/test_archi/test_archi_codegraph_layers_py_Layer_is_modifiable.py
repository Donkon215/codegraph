"""Architecture test for codegraph/layers.py::Layer::is_modifiable."""
from codegraph.layers import Layer

def test_archi_Layer_is_modifiable():
    obj = Layer()
    obj.is_modifiable()
