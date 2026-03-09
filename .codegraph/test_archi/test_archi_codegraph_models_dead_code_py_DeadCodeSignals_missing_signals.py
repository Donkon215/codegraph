"""Architecture test for codegraph/models/dead_code.py::DeadCodeSignals::missing_signals."""
from codegraph.models.dead_code import DeadCodeSignals

def test_archi_DeadCodeSignals_missing_signals():
    obj = DeadCodeSignals()
    obj.missing_signals()
