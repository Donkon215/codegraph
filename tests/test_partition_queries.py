from __future__ import annotations

from codegraph.architecture_graph import ArchitectureGraph
from codegraph.graph_partitioning import build_partitions, save_partitions
from codegraph.models.graph0 import Graph0, Graph0Node
from codegraph.models.graph1 import Graph1
from codegraph.models.workflow import Workflow, WorkflowEdge
from codegraph.query import ParsedQuery, QueryResult, _execute_aql


class _DummyIndex:
    def get_all_node_ids(self):
        return []


def _write_graph(tmp_path):
    g0 = Graph0(
        nodes=[
            Graph0Node(id="payment.py::PaymentService", body_hash="a", file="payment.py", type="class", line=1),
            Graph0Node(id="payment.py::PaymentRepo", body_hash="b", file="payment.py", type="class", line=2),
            Graph0Node(id="order.py::OrderService", body_hash="c", file="order.py", type="class", line=1),
        ]
    )
    wf = Workflow(
        edges=[
            WorkflowEdge(source="payment.py::PaymentService", target="payment.py::PaymentRepo", edge_type="call"),
        ]
    )
    graph = ArchitectureGraph.from_views(structure_graph=g0, intent_graph=Graph1(nodes=[]), workflow_graph=wf)
    graph.save_derived_views(tmp_path)
    save_partitions(tmp_path, build_partitions(graph, min_size=1))


def test_services_depends_on_uses_partition_filter(monkeypatch, tmp_path):
    _write_graph(tmp_path)

    import codegraph.query as query_mod

    monkeypatch.setattr(query_mod, "_resolve_target_nodes", lambda arg, index: ["payment.py::PaymentService"])
    monkeypatch.setattr(
        query_mod,
        "query_dependents",
        lambda target, index: QueryResult(nodes=["payment.py::PaymentRepo", "order.py::OrderService"]),
    )
    monkeypatch.setattr(query_mod, "_is_service_node", lambda node_id, index: True)

    parsed = ParsedQuery(
        function="aql",
        options={"subject": "services", "predicate": "depends_on", "predicate_arg": "PaymentService"},
    )
    result = _execute_aql(parsed, _DummyIndex(), project_root=tmp_path, limit=None)

    assert "payment.py::PaymentRepo" in result.nodes
    assert "order.py::OrderService" not in result.nodes
    assert result.metadata.get("target_partitions")
