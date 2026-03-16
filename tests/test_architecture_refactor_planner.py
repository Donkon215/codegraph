from __future__ import annotations

import json

from codegraph.architecture_refactor_planner import (
    detect_architecture_violations,
    generate_refactor_plan,
)


class TestArchitectureRefactorPlanner:
    def test_detect_architecture_violations(self, tmp_path):
        wf_dir = tmp_path / ".codegraph" / "workflow"
        wf_dir.mkdir(parents=True)

        wf_dir.joinpath("workflow.json").write_text(
            json.dumps(
                {
                    "edges": [
                        {"source": "controller/orders.py::OrdersController::list", "target": "repository/orders.py::OrderRepo::get"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        wf_dir.joinpath("suggested_workflow.json").write_text(
            json.dumps(
                {
                    "rules": [
                        {
                            "type": "layer_boundary",
                            "source": "controller/*",
                            "target": "repository/*",
                            "reason": "controllers must use service layer",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        violations = detect_architecture_violations(tmp_path)
        assert len(violations) == 1
        assert violations[0].violation == "layer_boundary"
        assert violations[0].recommended_fix == "introduce service layer"

    def test_generate_refactor_plan_shape(self, tmp_path):
        graphs_dir = tmp_path / ".codegraph" / "graphs"
        wf_dir = tmp_path / ".codegraph" / "workflow"
        graphs_dir.mkdir(parents=True)
        wf_dir.mkdir(parents=True)

        graphs_dir.joinpath("graph0.json").write_text(
            json.dumps(
                {
                    "graph_version": 1,
                    "format_version": 1,
                    "nodes": [
                        {"id": "svc/order.py::OrderService", "body_hash": "a", "file": "svc/order.py", "type": "class", "line": 1},
                        {"id": "svc/payment.py::PaymentService", "body_hash": "b", "file": "svc/payment.py", "type": "class", "line": 1},
                    ],
                }
            ),
            encoding="utf-8",
        )
        graphs_dir.joinpath("graph1.json").write_text(
            json.dumps(
                {
                    "format_version": 1,
                    "nodes": [
                        {"id": "svc/order.py::OrderService", "intent": "order service", "layer": 3},
                        {"id": "svc/payment.py::PaymentService", "intent": "payment service", "layer": 3},
                    ],
                }
            ),
            encoding="utf-8",
        )
        wf_dir.joinpath("workflow.json").write_text(
            json.dumps(
                {
                    "format_version": 1,
                    "edges": [
                        {"source": "svc/order.py::OrderService", "target": "svc/payment.py::PaymentService", "edge_type": "call", "confidence": "static"},
                        {"source": "svc/payment.py::PaymentService", "target": "svc/order.py::OrderService", "edge_type": "call", "confidence": "static"},
                    ]
                }
            ),
            encoding="utf-8",
        )

        plan = generate_refactor_plan(tmp_path, max_items=5)
        assert "refactor_plan" in plan
        assert "architecture_violations" in plan
        assert "summary" in plan
