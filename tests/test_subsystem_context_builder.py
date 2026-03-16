from __future__ import annotations

import json

from codegraph.subsystem_context_builder import (
    MAX_SUBSYSTEM_CONTEXT_BYTES,
    build_subsystem_context,
)


def _write_min_graph(tmp_path):
    graphs_dir = tmp_path / ".codegraph" / "graphs"
    workflow_dir = tmp_path / ".codegraph" / "workflow"
    architecture_dir = tmp_path / ".codegraph" / "architecture"
    graphs_dir.mkdir(parents=True)
    workflow_dir.mkdir(parents=True)
    architecture_dir.mkdir(parents=True)

    graphs_dir.joinpath("graph0.json").write_text(
        json.dumps(
            {
                "graph_version": 1,
                "format_version": 1,
                "nodes": [
                    {"id": "payment.py::PaymentController", "body_hash": "a", "file": "payment.py", "type": "class", "line": 1},
                    {"id": "payment.py::PaymentService", "body_hash": "b", "file": "payment.py", "type": "class", "line": 2},
                    {"id": "payment.py::PaymentRepository", "body_hash": "c", "file": "payment.py", "type": "class", "line": 3},
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
                    {"id": "payment.py::PaymentController", "intent": "controller", "layer": 2, "intent_body_hash": "a"},
                    {"id": "payment.py::PaymentService", "intent": "service", "layer": 3, "intent_body_hash": "b"},
                    {"id": "payment.py::PaymentRepository", "intent": "repo", "layer": 4, "intent_body_hash": "c"},
                ],
            }
        ),
        encoding="utf-8",
    )

    workflow_dir.joinpath("workflow.json").write_text(
        json.dumps(
            {
                "format_version": 1,
                "edges": [
                    {"source": "payment.py::PaymentController", "target": "payment.py::PaymentService", "edge_type": "call", "confidence": "static"},
                    {"source": "payment.py::PaymentService", "target": "payment.py::PaymentRepository", "edge_type": "call", "confidence": "static"},
                ],
            }
        ),
        encoding="utf-8",
    )



def test_subsystem_context_shape_and_size(tmp_path):
    _write_min_graph(tmp_path)
    context = build_subsystem_context(tmp_path, "payment.py::PaymentService", depth=2, max_nodes=200)
    payload = context.to_dict()

    assert payload["subsystem_root"] == "payment.py::PaymentService"
    assert isinstance(payload["nodes"], list)
    assert isinstance(payload["edges"], list)
    assert isinstance(payload["boundary_nodes"], list)

    encoded_size = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    assert encoded_size <= MAX_SUBSYSTEM_CONTEXT_BYTES
