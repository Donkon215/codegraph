from __future__ import annotations

import json

from codegraph.copilot_context_builder import (
    build_enriched_context,
    focus_context,
    hotspot_context,
    scope_context,
)


def _setup_minimal_graph(tmp_path):
    """Create a minimal .codegraph tree for testing."""
    arch_dir = tmp_path / ".codegraph" / "architecture"
    graph_dir = tmp_path / ".codegraph" / "graphs"
    workflow_dir = tmp_path / ".codegraph" / "workflow"
    analysis_dir = tmp_path / ".codegraph" / "analysis"
    proofs_dir = tmp_path / ".codegraph" / "proofs"

    for d in (arch_dir, graph_dir, workflow_dir, analysis_dir, proofs_dir):
        d.mkdir(parents=True, exist_ok=True)

    graph_dir.joinpath("graph0.json").write_text(
        json.dumps({
            "graph_version": 2,
            "nodes": [
                {"id": "svc/order.py::OrderService", "body_hash": "x",
                 "file": "svc/order.py", "type": "class", "line": 1},
                {"id": "svc/order.py::OrderService::create", "body_hash": "y",
                 "file": "svc/order.py", "type": "function", "line": 10},
                {"id": "svc/payment.py::PaymentService", "body_hash": "z",
                 "file": "svc/payment.py", "type": "class", "line": 1},
                {"id": "svc/payment.py::PaymentService::charge", "body_hash": "w",
                 "file": "svc/payment.py", "type": "function", "line": 5},
            ],
        }),
        encoding="utf-8",
    )
    graph_dir.joinpath("graph1.json").write_text(
        json.dumps({
            "nodes": [
                {"id": "svc/order.py::OrderService", "intent": "service",
                 "layer": 3, "arch_layer": "service", "intent_body_hash": "y"},
            ]
        }),
        encoding="utf-8",
    )
    workflow_dir.joinpath("workflow.json").write_text(
        json.dumps({
            "edges": [
                {"source": "svc/order.py::OrderService::create",
                 "target": "svc/payment.py::PaymentService::charge",
                 "edge_type": "call"},
            ]
        }),
        encoding="utf-8",
    )
    arch_dir.joinpath("system.json").write_text(
        json.dumps({
            "subsystems": [
                {"name": "orders", "modules": ["svc/order.py"]},
                {"name": "payments", "modules": ["svc/payment.py"]},
            ],
            "edges": [
                {"source": "orders", "target": "payments"},
            ],
            "constraints": [
                {"source": "payments", "target": "orders",
                 "type": "forbidden_dependency", "reason": "no circular dep"},
            ],
        }),
        encoding="utf-8",
    )
    analysis_dir.joinpath("violations.json").write_text(
        json.dumps({
            "violations": [
                {"node": "svc/payment.py::PaymentService::charge",
                 "type": "layer_violation", "message": "crosses boundary"},
            ]
        }),
        encoding="utf-8",
    )
    proofs_dir.joinpath("latest_proof.json").write_text(
        json.dumps({"status": "PROVEN_SAFE"}), encoding="utf-8",
    )
    arch_dir.joinpath("architecture_patterns.json").write_text(
        json.dumps({
            "primary_pattern": "layered",
            "patterns": [{"architecture_type": "layered",
                          "confidence": 0.8, "consistency": 0.9}],
        }),
        encoding="utf-8",
    )
    return tmp_path


class TestCopilotContextBuilder:
    def test_enriched_sections_present(self, tmp_path):
        root = _setup_minimal_graph(tmp_path)
        ctx = build_enriched_context(root)
        payload = ctx.to_dict()

        assert "architecture_queries" in payload
        assert len(payload["architecture_queries"]) >= 3
        assert "architecture_stability" in payload
        assert "architecture_patterns" in payload

    def test_save_respects_proven_safe_publish(self, tmp_path):
        root = _setup_minimal_graph(tmp_path)
        ctx = build_enriched_context(root)
        saved_path = ctx.save(root)
        assert saved_path.name == "copilot_context.json"


class TestFocusContext:
    def test_focus_by_file(self, tmp_path):
        root = _setup_minimal_graph(tmp_path)
        ctx = focus_context(root, "svc/order.py")
        assert ctx.target_type == "file"
        assert len(ctx.nodes) >= 2  # OrderService + create
        assert ctx.fan_out >= 0

    def test_focus_by_node(self, tmp_path):
        root = _setup_minimal_graph(tmp_path)
        ctx = focus_context(root, "svc/order.py::OrderService::create")
        assert ctx.target_type == "node"
        assert any(n["id"] == "svc/order.py::OrderService::create"
                   for n in ctx.nodes)

    def test_focus_includes_callers_callees(self, tmp_path):
        root = _setup_minimal_graph(tmp_path)
        ctx = focus_context(root, "svc/order.py::OrderService::create")
        assert "svc/payment.py::PaymentService::charge" in ctx.callees

    def test_focus_picks_up_violations(self, tmp_path):
        root = _setup_minimal_graph(tmp_path)
        ctx = focus_context(root, "svc/payment.py::PaymentService::charge")
        assert len(ctx.violations) >= 1

    def test_focus_subsystem_detection(self, tmp_path):
        root = _setup_minimal_graph(tmp_path)
        ctx = focus_context(root, "svc/order.py::OrderService")
        assert ctx.subsystem == "orders"

    def test_focus_layer_detection(self, tmp_path):
        root = _setup_minimal_graph(tmp_path)
        ctx = focus_context(root, "svc/order.py::OrderService")
        assert ctx.layer == "service"

    def test_focus_format_output(self, tmp_path):
        root = _setup_minimal_graph(tmp_path)
        ctx = focus_context(root, "svc/order.py")
        text = ctx.format()
        assert "Focus:" in text
        assert "svc/order.py" in text

    def test_focus_empty_project(self, tmp_path):
        ctx = focus_context(tmp_path, "nonexistent.py")
        assert ctx.target_type == "file"
        assert len(ctx.nodes) == 0

    def test_focus_depth_expansion(self, tmp_path):
        root = _setup_minimal_graph(tmp_path)
        ctx_d0 = focus_context(root, "svc/order.py::OrderService", depth=0)
        ctx_d1 = focus_context(root, "svc/order.py::OrderService", depth=1)
        # Deeper expansion should include more nodes
        assert len(ctx_d1.nodes) >= len(ctx_d0.nodes)

    def test_focus_json_serializable(self, tmp_path):
        root = _setup_minimal_graph(tmp_path)
        ctx = focus_context(root, "svc/order.py")
        d = ctx.to_dict()
        # Should not raise
        serialized = json.dumps(d)
        assert isinstance(json.loads(serialized), dict)


class TestHotspotContext:
    def test_hotspot_report_structure(self, tmp_path):
        root = _setup_minimal_graph(tmp_path)
        report = hotspot_context(root)
        d = report.to_dict()
        assert "violation_hotspots" in d
        assert "coupling_hotspots" in d
        assert "top_priority_actions" in d

    def test_hotspot_picks_up_violations(self, tmp_path):
        root = _setup_minimal_graph(tmp_path)
        report = hotspot_context(root)
        assert len(report.violation_hotspots) >= 1

    def test_hotspot_priority_actions(self, tmp_path):
        root = _setup_minimal_graph(tmp_path)
        report = hotspot_context(root)
        assert len(report.top_priority_actions) >= 1

    def test_hotspot_format_output(self, tmp_path):
        root = _setup_minimal_graph(tmp_path)
        report = hotspot_context(root)
        text = report.format()
        assert "Hotspots" in text

    def test_hotspot_empty_project(self, tmp_path):
        report = hotspot_context(tmp_path)
        assert report.score == 0.0
        assert isinstance(report.to_dict(), dict)


class TestScopeContext:
    def test_scope_finds_subsystem(self, tmp_path):
        root = _setup_minimal_graph(tmp_path)
        ctx = scope_context(root, "orders")
        assert ctx.subsystem_name == "orders"
        assert "svc/order.py" in ctx.modules

    def test_scope_includes_boundary_edges(self, tmp_path):
        root = _setup_minimal_graph(tmp_path)
        ctx = scope_context(root, "orders")
        # The order->payment call crosses subsystem boundary
        assert len(ctx.boundary_edges) >= 1

    def test_scope_allowed_deps(self, tmp_path):
        root = _setup_minimal_graph(tmp_path)
        ctx = scope_context(root, "orders")
        assert "payments" in ctx.allowed_deps

    def test_scope_forbidden_deps(self, tmp_path):
        root = _setup_minimal_graph(tmp_path)
        ctx = scope_context(root, "payments")
        assert "orders" in ctx.forbidden_deps

    def test_scope_constraints(self, tmp_path):
        root = _setup_minimal_graph(tmp_path)
        ctx = scope_context(root, "payments")
        assert len(ctx.constraints) >= 1

    def test_scope_format_output(self, tmp_path):
        root = _setup_minimal_graph(tmp_path)
        ctx = scope_context(root, "orders")
        text = ctx.format()
        assert "Scope:" in text
        assert "orders" in text

    def test_scope_unknown_subsystem(self, tmp_path):
        root = _setup_minimal_graph(tmp_path)
        ctx = scope_context(root, "nonexistent")
        # Subsystem not found — no modules populated
        assert len(ctx.modules) == 0
        assert ctx.node_count == 0

    def test_scope_fuzzy_match(self, tmp_path):
        root = _setup_minimal_graph(tmp_path)
        ctx = scope_context(root, "order")  # partial match
        assert ctx.subsystem_name == "orders"

    def test_scope_json_serializable(self, tmp_path):
        root = _setup_minimal_graph(tmp_path)
        ctx = scope_context(root, "orders")
        d = ctx.to_dict()
        serialized = json.dumps(d)
        assert isinstance(json.loads(serialized), dict)
