"""Architecture test for codegraph/utils/progress.py::ProgressReporter::finish."""
from codegraph.utils.progress import ProgressReporter

def test_archi_ProgressReporter_finish():
    obj = ProgressReporter()
    obj.finish()
