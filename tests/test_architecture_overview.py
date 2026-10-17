"""Tests for codegraph.architecture_overview — structural architecture overview.

Covers: deterministic community summaries, cross-community coupling evidence,
declared-subsystem reporting separate from detected structure, round-trip
serialization, and that metrics never act as hard rejects.
"""

from __future__ import annotations

from pathlib import Path

from codegraph.architecture_graph import ArchitectureGraph
from codegraph.architecture_overview import (
    ArchitectureOverview,
    build_architecture_overview,
)


def _clique(ids: list[str]) -> list[dict]:
    """Bidirectional edges between every pair in *ids* (directed both ways)."""
    edges: list[dict] = []
    for source in ids:
        for target in ids:
            if source != target:
                edges.append(
                    {"source": source, "target": target, "edge_type": "call"}
                )
    return edges


def _graph(with_metadata: bool = True) -> ArchitectureGraph:
    """Two tightly-coupled 4-node modules plus one undeclared helper.

    Each module is a clique so internal edges dominate the single cross edge,
    making label-propagation communities deterministic (≥2 communities).
    """
    payments = [
        "payments.py::PaymentService",
        "payments.py::PaymentRepo",
        "payments.py::PaymentValidator",
        "payments.py::PaymentGateway",
    ]
    orders = [
        "orders.py::OrderService",
        "orders.py::OrderRepo",
        "orders.py::OrderValidator",
        "orders.py::OrderGateway",
    ]
    metadata: dict = {"subsystems": ["Payments", "Orders"]} if with_metadata else {}
    return ArchitectureGraph(
        nodes=[
            {"id": nid, "file": "payments.py", "type": "class", "line": 1, "subsystem": "Payments"}
            for nid in payments
        ]
        + [
            {"id": nid, "file": "orders.py", "type": "class", "line": 1, "subsystem": "Orders"}
            for nid in orders
        ]
        + [{"id": "reports.py::ReportBuilder", "file": "reports.py", "type": "function", "line": 1}],
        edges=(
            _clique(payments)
            + _clique(orders)
            + [
                # cross-community dependency evidence
                {"source": "orders.py::OrderService", "target": "payments.py::PaymentService",
                 "edge_type": "call"},
                {"source": "reports.py::ReportBuilder", "target": "orders.py::OrderService",
                 "edge_type": "call"},
            ]
        ),
        metadata=metadata,
    )


def test_community_summaries_detected_separate_from_declared() -> None:
    graph = _graph()
    overview = build_architecture_overview(graph)

    assert overview.method == "label_propagation"
    communities = overview.communities
    assert len(communities) >= 2

    payments_comm = next(
        c for c in communities if any("payments.py" in n for n in c.node_ids)
    )
    assert payments_comm.declared_subsystem == "Payments"
    assert payments_comm.internal_edge_count >= 1

    reports_comm = next(
        c for c in communities if any("reports.py" in n for n in c.node_ids)
    )
    # Mixed/undeclared community: no single declared subsystem.
    assert reports_comm.declared_subsystem is None

    # Declared subsystems are reported alongside, never merged into communities.
    assert "Payments" in overview.declared_subsystems
    assert "Orders" in overview.declared_subsystems

    for community in communities:
        assert community.node_ids
        assert community.size == len(community.node_ids)
        assert community.analysis
        assert isinstance(community.node_type_counts, dict)
        # New #67 fields: distinct files/directories plus boundary edge evidence.
        assert isinstance(community.files, list) and community.files
        assert isinstance(community.directories, list) and community.directories
        assert isinstance(community.boundary_edges, list)
        d = community.to_dict()
        assert set(d) >= {
            "community_id", "size", "node_ids", "internal_edge_count",
            "boundary_nodes", "declared_subsystem", "node_type_counts",
            "files", "directories", "boundary_edges", "analysis",
        }


def test_cross_subdirectory_community_files_and_directories() -> None:
    """A connected component spanning subdirectories reports distinct
    file/directory sets (issue #67: cross-subdirectory community)."""
    graph = ArchitectureGraph(
        nodes=[
            {"id": "src/payments/service.py::PaymentService", "file": "src/payments/service.py", "type": "class", "line": 1},
            {"id": "src/payments/repo.py::PaymentRepo", "file": "src/payments/repo.py", "type": "class", "line": 2},
            {"id": "src/shared/util.py::Util", "file": "src/shared/util.py", "type": "function", "line": 1},
            {"id": "src/reports/report.py::Report", "file": "src/reports/report.py", "type": "function", "line": 1},
        ],
        edges=[
            {"source": "src/payments/service.py::PaymentService", "target": "src/payments/repo.py::PaymentRepo", "edge_type": "call"},
            {"source": "src/payments/repo.py::PaymentRepo", "target": "src/shared/util.py::Util", "edge_type": "call"},
            {"source": "src/shared/util.py::Util", "target": "src/payments/service.py::PaymentService", "edge_type": "call"},
            {"source": "src/reports/report.py::Report", "target": "src/payments/service.py::PaymentService", "edge_type": "call"},
        ],
        metadata={},
    )
    overview = build_architecture_overview(graph)
    communities = overview.communities
    assert communities
    big = max(communities, key=lambda c: c.size)
    assert big.size == 4
    assert "src/payments/service.py" in big.files
    assert "src/shared/util.py" in big.files
    assert "src/payments" in big.directories
    assert "src/shared" in big.directories
    # Single detected community: no edges cross its boundary.
    assert big.boundary_edges == []


def test_boundary_edges_cross_the_community_boundary() -> None:
    """Every recorded boundary edge has exactly one endpoint in the community."""
    graph = _graph()
    overview = build_architecture_overview(graph)
    for community in overview.communities:
        member_set = set(community.node_ids)
        for edge in community.boundary_edges:
            source = str(edge.get("source", "")).strip()
            target = str(edge.get("target", "")).strip()
            assert (source in member_set) != (target in member_set)


def test_cross_community_links_are_evidence_not_rejects() -> None:
    graph = _graph()
    overview = build_architecture_overview(graph)

    links = overview.cross_community_links
    assert links, "expected at least one cross-community dependency link"

    for link in links:
        assert link.source_community != link.target_community
        assert link.edge_count >= 1
        assert 0.0 <= link.coupling_score <= 1.0
        assert link.evidence
        assert link.source_nodes and link.target_nodes
        assert len(link.edges) <= 8  # bounded sample
        d = link.to_dict()
        assert set(d) >= {
            "source_community", "target_community", "edge_count", "edges",
            "source_nodes", "target_nodes", "coupling_score", "evidence",
        }

    # No hard-reject / pass/fail fields anywhere in the output.
    for community in overview.communities:
        assert "reject" not in community.analysis.lower()
        d = community.to_dict()
        assert not any(k.endswith(("_reject", "_pass", "_fail")) for k in d)
    assert not overview.analysis.lower().startswith("reject")


def test_round_trip_serialization() -> None:
    graph = _graph()
    overview = build_architecture_overview(graph)
    data = overview.to_dict()
    assert isinstance(data, dict)
    assert "communities" in data and "cross_community_links" in data
    assert "metrics" in data and "method" in data and "analysis" in data
    assert set(data["metrics"]) >= {
        "community_count", "node_count", "edge_count",
        "internal_edges", "cross_edges", "internal_edge_ratio",
        "mean_community_size", "max_coupling_score",
    }
    # Deterministic output.
    assert data == build_architecture_overview(graph).to_dict()


def test_undeclared_graph_reports_none_subsystems() -> None:
    graph = _graph(with_metadata=False)
    overview = build_architecture_overview(graph)
    assert overview.declared_subsystems == []
    # At least one community has no subsystem at all -> None declared.
    assert any(community.declared_subsystem is None for community in overview.communities)


def test_empty_graph_produces_empty_overview() -> None:
    graph = ArchitectureGraph(nodes=[], edges=[], metadata={})
    overview = build_architecture_overview(graph)
    assert overview.communities == []
    assert overview.cross_community_links == []
    assert overview.metrics["node_count"] == 0
    assert overview.metrics["edge_count"] == 0
    assert overview.metrics["internal_edge_ratio"] == 0
    assert overview.method == "label_propagation"
    assert overview.declared_subsystems == []


def test_partitions_can_be_reused() -> None:
    from codegraph.graph_partitioning import build_partitions

    graph = _graph()
    partitions = build_partitions(graph)
    overview_a = build_architecture_overview(graph)
    overview_b = build_architecture_overview(graph, partitions=partitions)
    assert overview_a.to_dict() == overview_b.to_dict()


# ── Issue #67 fixture-based tests ──────────────────────────────────────

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "architecture"


def _load_fixture_input(name: str) -> dict:
    import json

    return json.loads(
        (FIXTURES_DIR / name / "input.json").read_text(encoding="utf-8")
    )


def _graph_from_fixture(name: str) -> ArchitectureGraph:
    data = _load_fixture_input(name)
    return ArchitectureGraph(
        nodes=[
            {
                "id": str(node["id"]),
                "file": str(node.get("file", "")),
                "type": str(node.get("type", "function")),
                "line": int(node.get("line", 1)),
            }
            for node in data.get("nodes", [])
        ],
        edges=[
            {
                "source": str(edge["source"]),
                "target": str(edge["target"]),
                "edge_type": str(edge.get("edge_type", "call")),
            }
            for edge in data.get("edges", [])
        ],
        metadata={},
    )


def test_three_community_exact_structure() -> None:
    """Two tightly coupled subdirectory groups plus one unrelated group
    yield exactly three communities, with a cross-community link between
    the two coupled groups (issue #67 fixture (a))."""
    graph = _graph_from_fixture("three_community")
    overview = build_architecture_overview(graph)

    assert len(overview.communities) == 3
    by_dir = {c.community_id: c for c in overview.communities}

    payments = next(
        c for c in overview.communities if "src/payments" in c.directories
    )
    orders = next(c for c in overview.communities if "src/orders" in c.directories)
    reports = next(c for c in overview.communities if "src/reports" in c.directories)

    assert payments.size == 3
    assert payments.files == ["src/payments/payments.py"]
    assert payments.directories == ["src/payments"]
    assert orders.size == 3
    assert orders.files == ["src/orders/orders.py"]
    assert orders.directories == ["src/orders"]
    assert reports.size == 1
    assert reports.files == ["src/reports/reports.py"]
    assert reports.directories == ["src/reports"]

    # Exactly one cross-community link: payments -> orders.
    assert len(overview.cross_community_links) == 1
    link = overview.cross_community_links[0]
    assert link.source_community == payments.community_id
    assert link.target_community == orders.community_id
    assert link.edge_count == 1
    assert link.coupling_score > 0.0

    # Boundary edges are recorded on each coupled community.
    assert len(payments.boundary_edges) == 1
    assert len(orders.boundary_edges) == 1
    assert reports.boundary_edges == []


def test_cross_dir_single_community_exact_structure() -> None:
    """One logical directory (lib) split across two subdirectories with
    heavy reciprocal references yields exactly one community spanning both
    dirs (issue #67 fixture (b))."""
    graph = _graph_from_fixture("cross_dir_single_community")
    overview = build_architecture_overview(graph)

    assert len(overview.communities) == 1
    community = overview.communities[0]
    assert community.size == 3
    assert community.files == ["lib/billing/bill.py", "lib/payments/pay.py"]
    assert community.directories == ["lib/billing", "lib/payments"]
    assert overview.cross_community_links == []
    assert community.boundary_edges == []
    assert community.declared_subsystem is None
