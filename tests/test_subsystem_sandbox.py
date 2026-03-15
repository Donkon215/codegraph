from __future__ import annotations

from codegraph.subsystem_graph import SubsystemGraph
from codegraph.subsystem_sandbox import SubsystemSandbox


def _base_subsystem() -> SubsystemGraph:
    return SubsystemGraph(
        nodes=[
            {"id": "payment.py::PaymentController", "layer": 2, "type": "class"},
            {"id": "payment.py::PaymentService", "layer": 3, "type": "class"},
            {"id": "payment.py::PaymentRepository", "layer": 4, "type": "class"},
        ],
        edges=[
            {"source": "payment.py::PaymentController", "target": "payment.py::PaymentService", "edge_type": "call"},
            {"source": "payment.py::PaymentService", "target": "payment.py::PaymentRepository", "edge_type": "call"},
        ],
        boundary_nodes=["payment.py::PaymentService"],
        external_edges=[],
        metadata={"root_node": "payment.py::PaymentService"},
    )


def test_sandbox_split_and_simulate():
    sandbox = SubsystemSandbox(_base_subsystem())
    sandbox.apply_change(
        {
            "action": "split_node",
            "node": "payment.py::PaymentService",
            "new_nodes": [
                "payment.py::PaymentProcessor",
                "payment.py::PaymentValidator",
            ],
        }
    )
    metrics = sandbox.get_metrics()
    result = sandbox.simulate()

    assert metrics["nodes"] >= 3
    assert "score_before" in result
    assert "score_after" in result


def test_sandbox_insert_service_layer():
    sandbox = SubsystemSandbox(_base_subsystem())
    sandbox.apply_change(
        {
            "action": "insert_service_layer",
            "source": "payment.py::PaymentController",
            "target": "payment.py::PaymentRepository",
            "service_node": "payment.py::PaymentServiceFacade",
        }
    )
    metrics = sandbox.get_metrics()
    assert metrics["nodes"] == 4
