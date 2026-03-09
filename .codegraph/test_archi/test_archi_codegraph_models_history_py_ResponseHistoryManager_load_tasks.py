"""Architecture test for codegraph/models/history.py::ResponseHistoryManager::load_tasks."""
from codegraph.models.history import ResponseHistoryManager

def test_archi_ResponseHistoryManager_load_tasks():
    obj = ResponseHistoryManager()
    obj.load_tasks(0)
