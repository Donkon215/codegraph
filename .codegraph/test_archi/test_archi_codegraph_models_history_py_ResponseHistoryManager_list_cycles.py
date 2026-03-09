"""Architecture test for codegraph/models/history.py::ResponseHistoryManager::list_cycles."""
from codegraph.models.history import ResponseHistoryManager

def test_archi_ResponseHistoryManager_list_cycles():
    obj = ResponseHistoryManager()
    obj.list_cycles()
