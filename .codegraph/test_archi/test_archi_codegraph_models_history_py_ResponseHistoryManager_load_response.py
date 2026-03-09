"""Architecture test for codegraph/models/history.py::ResponseHistoryManager::load_response."""
from codegraph.models.history import ResponseHistoryManager

def test_archi_ResponseHistoryManager_load_response():
    obj = ResponseHistoryManager()
    obj.load_response(0)
