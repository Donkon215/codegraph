"""Architecture test for codegraph/types.py::TaskItem::to_dict."""
from codegraph.types import TaskItem

def test_archi_TaskItem_to_dict():
    obj = TaskItem()
    obj.to_dict()
