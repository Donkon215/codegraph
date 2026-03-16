"""Unit tests for the query system.

Task O-015: Query functions with known graph data.
"""

from __future__ import annotations

import pytest

from codegraph.query import ParsedQuery, QueryOptions, execute_query, parse_query


class TestQueryParser:
    """Test query string parsing."""

    def test_simple_function(self) -> None:
        q = parse_query('callers("mod.py::func")')
        assert q.function == "callers"
        assert "mod.py::func" in q.args

    def test_no_args(self) -> None:
        q = parse_query("orphans()")
        assert q.function == "orphans"
        assert len(q.args) == 0

    def test_layer_query(self) -> None:
        q = parse_query("layer(4)")
        assert q.function == "layer"
        assert "4" in q.args or 4 in q.args

    def test_path_query(self) -> None:
        q = parse_query('path("a", "b")')
        assert q.function == "path"
        assert len(q.args) == 2

    def test_with_options(self) -> None:
        q = parse_query('dependencies("a", depth=3)')
        assert q.function == "dependencies"
        assert "depth" in q.options

    def test_explain(self) -> None:
        q = parse_query('explain("mod.py::func")')
        assert q.function == "explain"

    def test_single_quoted(self) -> None:
        q = parse_query("callers('mod.py::func')")
        assert q.function == "callers"
        assert "mod.py::func" in q.args


class TestQueryImports:
    """Test that query module is importable."""

    def test_import_run_query(self) -> None:
        from codegraph.query import run_query
        assert callable(run_query)

    def test_import_execute_query(self) -> None:
        from codegraph.query import execute_query
        assert callable(execute_query)

    def test_import_format_query_result(self) -> None:
        from codegraph.query import format_query_result
        assert callable(format_query_result)


class _FakeIndex:
    def __init__(self) -> None:
        self._nodes = {
            "svc/payment.py::PaymentService": {"arch_layer": "service", "file": "svc/payment.py"},
            "svc/order.py::OrderService": {"arch_layer": "service", "file": "svc/order.py"},
            "svc/order.py::create_order": {"arch_layer": "service", "file": "svc/order.py"},
            "core/helpers.py::helper": {"arch_layer": "domain", "file": "core/helpers.py"},
            "api/orders.py::OrdersController": {"arch_layer": "controller", "file": "api/orders.py"},
        }
        self._callers = {
            "svc/payment.py::PaymentService": [
                "svc/order.py::OrderService",
                "svc/order.py::create_order",
            ],
            "svc/order.py::OrderService": ["svc/payment.py::PaymentService"],
        }
        self._callees = {
            "svc/order.py::OrderService": ["svc/payment.py::PaymentService"],
            "svc/payment.py::PaymentService": ["svc/order.py::OrderService"],
            "svc/order.py::create_order": ["svc/payment.py::PaymentService"],
        }

    def get_node(self, node_id: str):
        data = self._nodes.get(node_id)
        if not data:
            return None
        return {"id": node_id, **data}

    def search_nodes(self, pattern: str, limit: int = 100):
        needle = pattern.replace("*", "")
        return [n for n in self._nodes if needle in n][:limit]

    def get_callers(self, node_id: str):
        return list(self._callers.get(node_id, []))

    def get_callees(self, node_id: str):
        return list(self._callees.get(node_id, []))

    def get_all_node_ids(self):
        return sorted(self._nodes.keys())


class TestAQL:
    def test_parse_aql(self) -> None:
        q = parse_query("SELECT services WHERE depends_on(PaymentService)")
        assert q.function == "aql"
        assert q.options["subject"] == "services"
        assert q.options["predicate"] == "depends_on"
        assert q.options["predicate_arg"] == "PaymentService"

    def test_parse_aql_calls_api(self) -> None:
        q = parse_query("SELECT frontend_components WHERE calls_api('/api/orders')")
        assert q.function == "aql"
        assert q.options["subject"] == "frontend_components"
        assert q.options["predicate"] == "calls_api"
        assert q.options["predicate_arg"] == "/api/orders"

    def test_parse_aql_smell_filter(self) -> None:
        q = parse_query("SELECT smells WHERE type='god_module'")
        assert q.function == "aql"
        assert q.options["subject"] == "smells"
        assert q.options["filter_key"] == "type"
        assert q.options["filter_value"] == "god_module"

    def test_execute_aql_services_depends_on(self) -> None:
        index = _FakeIndex()
        parsed = parse_query("SELECT services WHERE depends_on(PaymentService)")
        result = execute_query(parsed, index, QueryOptions())
        assert result.function == "aql"
        assert "svc/order.py::OrderService" in result.nodes
        assert "svc/order.py::create_order" in result.nodes

    def test_execute_aql_cycles_service_layer(self) -> None:
        index = _FakeIndex()
        parsed = parse_query("SELECT cycles WHERE in_layer(service)")
        result = execute_query(parsed, index, QueryOptions())
        assert result.function == "aql"
        assert result.total >= 1

        def test_execute_aql_modules_in_layer(self) -> None:
                index = _FakeIndex()
                parsed = parse_query("SELECT modules WHERE in_layer(service)")
                result = execute_query(parsed, index, QueryOptions())
                assert "svc/order.py::OrderService" in result.nodes
                assert all("svc/" in node for node in result.nodes)

        def test_execute_aql_events_produced_by(self, tmp_path) -> None:
                runtime_dir = tmp_path / ".codegraph" / "graphs"
                runtime_dir.mkdir(parents=True)
                runtime_dir.joinpath("graph3_runtime.json").write_text(
                        """
                        {
                            "edges": [
                                {"source_file": "svc/order.py", "source_node": "svc/order.py::OrderService::emit", "edge_type": "event_produce", "target": "OrderCreated"}
                            ],
                            "files_scanned": 1,
                            "edge_types": {"event_produce": 1}
                        }
                        """,
                        encoding="utf-8",
                )
                index = _FakeIndex()
                parsed = parse_query("SELECT events WHERE produced_by(OrderService)")
                result = execute_query(parsed, index, QueryOptions(), project_root=tmp_path)
                assert result.total == 1
                assert "OrderCreated" in result.nodes[0]

        def test_execute_aql_smells_by_type(self, tmp_path) -> None:
                arch_dir = tmp_path / ".codegraph" / "architecture"
                arch_dir.mkdir(parents=True)
                arch_dir.joinpath("architecture_smells.json").write_text(
                        """
                        {
                            "smells": [
                                {"smell_type": "god_module", "node": "codegraph/query.py"},
                                {"smell_type": "dependency_cycles", "node": "svc/order.py"}
                            ]
                        }
                        """,
                        encoding="utf-8",
                )
                index = _FakeIndex()
                parsed = parse_query("SELECT smells WHERE type='god_module'")
                result = execute_query(parsed, index, QueryOptions(), project_root=tmp_path)
                assert result.total == 1
                assert result.nodes[0].startswith("god_module")
