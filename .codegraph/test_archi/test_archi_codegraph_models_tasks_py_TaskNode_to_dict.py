"""Architecture test for codegraph/models/tasks.py::TaskNode::to_dict."""
from codegraph.models.tasks import TaskNode

def test_archi_TaskNode_to_dict():
    obj = TaskNode()
    obj.to_dict()
