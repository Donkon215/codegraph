"""Architecture test for codegraph/models/tasks.py::TaskBatch::get_tasks_by_priority."""
from codegraph.models.tasks import TaskBatch

def test_archi_TaskBatch_get_tasks_by_priority():
    obj = TaskBatch()
    obj.get_tasks_by_priority()
