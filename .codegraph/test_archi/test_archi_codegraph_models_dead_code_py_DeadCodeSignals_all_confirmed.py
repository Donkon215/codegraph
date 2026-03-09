"""Architecture test for codegraph/models/dead_code.py::DeadCodeSignals::all_confirmed."""
from codegraph.models.dead_code import DeadCodeSignals

def test_archi_DeadCodeSignals_all_confirmed():
    obj = DeadCodeSignals()
    obj.all_confirmed()
