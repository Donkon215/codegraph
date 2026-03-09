"""Architecture test for codegraph/models/convergence.py::ConvergenceState::record_iteration."""
from codegraph.models.convergence import ConvergenceState

def test_archi_ConvergenceState_record_iteration():
    obj = ConvergenceState()
    obj.record_iteration(0, 0)
