"""Architecture test for codegraph/models/tasks.py::TaskBatch::to_json."""
from codegraph.models.tasks import TaskBatch

def test_archi_TaskBatch_to_json():
    obj = TaskBatch()
    obj.to_json()
