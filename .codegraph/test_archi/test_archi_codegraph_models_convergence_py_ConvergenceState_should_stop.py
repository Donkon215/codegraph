"""Architecture test for codegraph/models/convergence.py::ConvergenceState::should_stop."""
from codegraph.models.convergence import ConvergenceState

def test_archi_ConvergenceState_should_stop():
    obj = ConvergenceState()
    obj.should_stop()
