"""Architecture test for codegraph/models/tasks.py::TaskItem::to_dict."""
from codegraph.models.tasks import TaskItem

def test_archi_TaskItem_to_dict():
    obj = TaskItem()
    obj.to_dict()
