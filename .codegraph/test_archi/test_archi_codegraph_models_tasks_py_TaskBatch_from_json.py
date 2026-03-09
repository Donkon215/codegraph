"""Architecture test for codegraph/models/tasks.py::TaskBatch::from_json."""
from codegraph.models.tasks import TaskBatch

def test_archi_TaskBatch_from_json():
    obj = TaskBatch()
    obj.from_json("")
