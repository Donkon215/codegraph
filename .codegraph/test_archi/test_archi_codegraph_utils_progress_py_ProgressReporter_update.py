"""Architecture test for codegraph/utils/progress.py::ProgressReporter::update."""
from codegraph.utils.progress import ProgressReporter

def test_archi_ProgressReporter_update():
    obj = ProgressReporter()
    obj.update()
