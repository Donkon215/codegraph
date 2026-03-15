from __future__ import annotations

import json

from codegraph.copilot_context_builder import build_enriched_context


class TestCopilotContextBuilder:
    def test_enriched_sections_present(self, tmp_path):
        arch_dir = tmp_path / ".codegraph" / "architecture"
        graph_dir = tmp_path / ".codegraph" / "graphs"
        workflow_dir = tmp_path / ".codegraph" / "workflow"
        proofs_dir = tmp_path / ".codegraph" / "proofs"

        arch_dir.mkdir(parents=True)
        graph_dir.mkdir(parents=True)
        workflow_dir.mkdir(parents=True)
        proofs_dir.mkdir(parents=True)

        graph_dir.joinpath("graph0.json").write_text(
            json.dumps(
                {
                    "graph_version": 2,
                    "nodes": [
                        {"id": "svc/order.py::OrderService", "body_hash": "x", "file": "svc/order.py", "type": "class", "line": 1}
                    ],
                }
            ),
            encoding="utf-8",
        )
        graph_dir.joinpath("graph1.json").write_text(
            json.dumps(
                {
                    "nodes": [
                        {"id": "svc/order.py::OrderService", "intent": "service", "layer": 3, "intent_body_hash": "y"}
                    ]
                }
            ),
            encoding="utf-8",
        )
        workflow_dir.joinpath("workflow.json").write_text(
            json.dumps({"edges": []}), encoding="utf-8"
        )
        proofs_dir.joinpath("latest_proof.json").write_text(
            json.dumps({"status": "PROVEN_SAFE"}), encoding="utf-8"
        )
        arch_dir.joinpath("architecture_patterns.json").write_text(
            json.dumps(
                {
                    "primary_pattern": "layered",
                    "patterns": [{"architecture_type": "layered", "confidence": 0.8, "consistency": 0.9}],
                }
            ),
            encoding="utf-8",
        )

        ctx = build_enriched_context(tmp_path)
        payload = ctx.to_dict()

        assert "architecture_queries" in payload
        assert len(payload["architecture_queries"]) >= 3
        assert "architecture_stability" in payload
        assert "architecture_patterns" in payload

    def test_save_respects_proven_safe_publish(self, tmp_path):
        proofs_dir = tmp_path / ".codegraph" / "proofs"
        proofs_dir.mkdir(parents=True)
        proofs_dir.joinpath("latest_proof.json").write_text(
            json.dumps({"status": "PROVEN_SAFE"}), encoding="utf-8"
        )

        ctx = build_enriched_context(tmp_path)
        saved_path = ctx.save(tmp_path)
        assert saved_path.name == "copilot_context.json"
