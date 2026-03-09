"""Architecture test for codegraph/models/tasks.py::TaskBatch::get_tasks_by_type."""
from codegraph.models.tasks import TaskBatch

def test_archi_TaskBatch_get_tasks_by_type():
    obj = TaskBatch()
    obj.get_tasks_by_type("")
