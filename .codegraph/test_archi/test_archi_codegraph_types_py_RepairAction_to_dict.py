"""Architecture test for codegraph/types.py::RepairAction::to_dict."""
from codegraph.types import RepairAction

def test_archi_RepairAction_to_dict():
    obj = RepairAction()
    obj.to_dict()
