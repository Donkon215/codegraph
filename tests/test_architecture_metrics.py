from __future__ import annotations

import json
from typing import Any, Dict, List

from codegraph.architecture_graph import ArchitectureGraph
from codegraph.architecture_metrics import (
    HUB_BAND,
    REACH_DEPTH,
    compute_architecture_metrics,
    compute_bridges,
    compute_coupling,
    compute_cycles,
    compute_hubs,
    load_report,
    save_report,
)


def _graph(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> ArchitectureGraph:
    return ArchitectureGraph(nodes=nodes, edges=edges)


def _nodes(*ids: str) -> List[Dict[str, Any]]:
    return [{"id": nid, "file": nid.split("::", 1)[0], "type": "function"} for nid in ids]


def test_hub_reports_callers_with_direct_edges():
    # "core::Hub" is a known hub: a::A, b::B, c::C all call it directly.
    graph = _graph(
        _nodes("core::Hub", "a::A", "b::B", "c::C", "leaf::L"),
        [
            {"source": "a::A", "target": "core::Hub", "edge_type": "call"},
            {"source": "b::B", "target": "core::Hub", "edge_type": "call"},
            {"source": "c::C", "target": "core::Hub", "edge_type": "call"},
            {"source": "core::Hub", "target": "leaf::L", "edge_type": "call"},
        ],
    )
    hubs = compute_hubs(graph)
    hub = next((h for h in hubs if h.node_id == "core::Hub"), None)
    assert hub is not None, f"core::Hub should be a hub, got {[h.node_id for h in hubs]}"
    assert set(hub.callers) == {"a::A", "b::B", "c::C"}
    # every listed caller has a direct edge to the hub
    direct = {
        (e["source"], e["target"])
        for e in graph.edges
        if e["target"] == "core::Hub"
    }
    for caller in hub.callers:
        assert (caller, "core::Hub") in direct


def test_bridge_reports_components_it_joins():
    # Two cyclic components joined by a single bridge c::c1 -> d::d1.
    # Internal edges form directed cycles, so only the inter-component edge
    # is a bridge; the internal edges are not.
    graph = _graph(
        _nodes("c::c1", "c::c2", "c::c3", "d::d1", "d::d2", "d::d3"),
        [
            {"source": "c::c1", "target": "c::c2", "edge_type": "call"},
            {"source": "c::c2", "target": "c::c3", "edge_type": "call"},
            {"source": "c::c3", "target": "c::c1", "edge_type": "call"},
            {"source": "c::c3", "target": "d::d1", "edge_type": "call"},  # bridge
            {"source": "d::d1", "target": "d::d2", "edge_type": "call"},
            {"source": "d::d2", "target": "d::d3", "edge_type": "call"},
            {"source": "d::d3", "target": "d::d1", "edge_type": "call"},
        ],
    )
    bridges = compute_bridges(graph)
    assert len(bridges) == 1, f"expected exactly one bridge, got {bridges}"
    bridge = bridges[0]
    assert {bridge.source, bridge.target} == {"c::c3", "d::d1"}
    components = {tuple(bridge.component_a), tuple(bridge.component_b)}
    assert components == {("c::c1", "c::c2", "c::c3"), ("d::d1", "d::d2", "d::d3")}


def test_two_node_cycle_is_one_scc():
    graph = _graph(
        _nodes("a::A", "b::B"),
        [
            {"source": "a::A", "target": "b::B", "edge_type": "call"},
            {"source": "b::B", "target": "a::A", "edge_type": "call"},
        ],
    )
    cycles = compute_cycles(graph)
    assert len(cycles) == 1, f"expected one cycle component, got {cycles}"
    assert cycles[0].nodes == ["a::A", "b::B"]
    assert cycles[0].size == 2
    assert { (e["source"], e["target"]) for e in cycles[0].edges } == {
        ("a::A", "b::B"),
        ("b::B", "a::A"),
    }


def test_self_loop_does_not_form_a_reported_cycle():
    graph = _graph(
        _nodes("a::A"),
        [{"source": "a::A", "target": "a::A", "edge_type": "call"}],
    )
    assert compute_cycles(graph) == []


def test_coupling_matches_definition_and_stores_evidence():
    # module m: x1->x2 internal, x2->y1 crosses, y-internal edge.
    graph = _graph(
        _nodes("m::x1", "m::x2", "n::y1", "n::y2"),
        [
            {"source": "m::x1", "target": "m::x2", "edge_type": "call"},
            {"source": "m::x2", "target": "n::y1", "edge_type": "call"},  # crosses
            {"source": "n::y1", "target": "n::y2", "edge_type": "call"},
        ],
    )
    couplings = {c.module: c for c in compute_coupling(graph)}
    # m has 2 members and 1 crossing edge -> coupling 1/2 = 0.5
    m = couplings["m"]
    assert m.node_count == 2
    assert m.crossing_edges == 1
    assert abs(m.coupling - 0.5) < 1e-9
    assert m.edges == [{"source": "m::x2", "target": "n::y1", "edge_type": "call"}]
    # n has 2 members and 1 crossing edge -> 0.5
    n = couplings["n"]
    assert abs(n.coupling - 0.5) < 1e-9
    assert n.edges == [{"source": "m::x2", "target": "n::y1", "edge_type": "call"}]


def test_coupling_normalises_by_size():
    # small module with few crossings vs large module: crossing / size.
    graph = _graph(
        _nodes("small::s", "big::b1", "big::b2", "big::b3", "big::b4", "out::o"),
        [
            {"source": "small::s", "target": "out::o", "edge_type": "call"},  # 1 crossing / 1 node
            {"source": "big::b1", "target": "out::o", "edge_type": "call"},
            {"source": "big::b2", "target": "out::o", "edge_type": "call"},
            {"source": "big::b3", "target": "out::o", "edge_type": "call"},
            {"source": "big::b4", "target": "out::o", "edge_type": "call"},  # 4 crossing / 4 nodes
        ],
    )
    couplings = {c.module: c for c in compute_coupling(graph)}
    assert abs(couplings["small"].coupling - 1.0) < 1e-9
    assert abs(couplings["big"].coupling - 1.0) < 1e-9
    # a large loosely coupled module: many crossings but big size stays lower than 1 per node
    graph2 = _graph(
        _nodes("big::b1", "big::b2", "big::b3", "out::o"),
        [
            {"source": "big::b1", "target": "out::o", "edge_type": "call"},
            {"source": "big::b2", "target": "out::o", "edge_type": "call"},
            {"source": "big::b3", "target": "out::o", "edge_type": "call"},
        ],
    )
    couplings2 = {c.module: c for c in compute_coupling(graph2)}
    assert abs(couplings2["big"].coupling - (3 / 3)) < 1e-9


def test_hub_tie_breaking_is_stable_and_sorted():
    # a::A and b::B have identical scores; both must appear, ordered by node id.
    graph = _graph(
        _nodes("a::A", "b::B", "c::C", "d::D", "e::E", "f::F", "g::G", "h::H", "i::I", "j::J"),
        [
            {"source": "c::C", "target": "a::A", "edge_type": "call"},
            {"source": "d::D", "target": "a::A", "edge_type": "call"},
            {"source": "e::E", "target": "b::B", "edge_type": "call"},
            {"source": "f::F", "target": "b::B", "edge_type": "call"},
        ],
    )
    hubs = compute_hubs(graph, hub_band=HUB_BAND)
    ids = [h.node_id for h in hubs]
    assert ids == sorted(ids), f"hubs must be sorted: {ids}"
    # top band of 10 nodes = 1, ties at cutoff included
    assert "a::A" in ids and "b::B" in ids


def test_isolated_nodes_are_never_hubs():
    graph = _graph(
        _nodes("lonely::L", "connected::C"),
        [{"source": "connected::C", "target": "connected::C", "edge_type": "call"}],
    )
    hubs = compute_hubs(graph)
    assert all(h.node_id != "lonely::L" for h in hubs)


def test_deterministic_byte_identical_output():
    graph = _graph(
        _nodes("m::x1", "m::x2", "n::y1", "core::Hub", "a::A"),
        [
            {"source": "a::A", "target": "core::Hub", "edge_type": "call"},
            {"source": "m::x1", "target": "m::x2", "edge_type": "call"},
            {"source": "m::x2", "target": "n::y1", "edge_type": "call"},
            {"source": "core::Hub", "target": "m::x1", "edge_type": "call"},
        ],
    )
    report1 = compute_architecture_metrics(graph)
    report2 = compute_architecture_metrics(graph)
    payload1 = json.dumps(report1.to_dict(), sort_keys=True)
    payload2 = json.dumps(report2.to_dict(), sort_keys=True)
    assert payload1 == payload2
    # no timestamps anywhere in the payload
    assert "generated_at" not in payload1
    assert "timestamp" not in payload1


def test_report_metadata_counts_match_lists():
    graph = _graph(
        _nodes("m::x1", "m::x2", "n::y1", "core::Hub", "a::A"),
        [
            {"source": "a::A", "target": "core::Hub", "edge_type": "call"},
            {"source": "m::x1", "target": "m::x2", "edge_type": "call"},
            {"source": "m::x2", "target": "n::y1", "edge_type": "call"},
        ],
    )
    report = compute_architecture_metrics(graph)
    assert report.metadata["node_count"] == _all_node_ids_safe(graph)
    assert report.metadata["edge_count"] == len(graph.edges)
    assert report.metadata["cycle_component_count"] == len(report.cycles)
    assert report.metadata["hub_count"] == len(report.hubs)
    assert report.metadata["bridge_count"] == len(report.bridges)
    assert report.metadata["reach_depth"] == REACH_DEPTH
    assert report.metadata["hub_band"] == HUB_BAND


def test_coupling_counts_parallel_edge_records():
    # Two parallel records x1->y1 cross the m boundary: both count as units.
    graph = _graph(
        _nodes("m::x1", "n::y1"),
        [
            {"source": "m::x1", "target": "n::y1", "edge_type": "call"},
            {"source": "m::x1", "target": "n::y1", "edge_type": "call"},
        ],
    )
    couplings = {c.module: c for c in compute_coupling(graph)}
    m = couplings["m"]
    assert m.node_count == 1
    assert m.crossing_edges == 2
    assert abs(m.coupling - 2.0) < 1e-9
    assert len(m.edges) == 2
    assert all(e["source"] == "m::x1" and e["target"] == "n::y1" for e in m.edges)


def test_coupling_counts_reverse_direction_records():
    # x1->y1 and y1->x1 both cross the m boundary (x1 in m, y1 outside).
    graph = _graph(
        _nodes("m::x1", "n::y1"),
        [
            {"source": "m::x1", "target": "n::y1", "edge_type": "call"},
            {"source": "n::y1", "target": "m::x1", "edge_type": "call"},
        ],
    )
    couplings = {c.module: c for c in compute_coupling(graph)}
    m = couplings["m"]
    assert m.crossing_edges == 2
    assert abs(m.coupling - 2.0) < 1e-9
    assert len(m.edges) == 2


def test_parallel_edges_are_not_bridges():
    # Two records between a and b keep them connected when one is removed;
    # only b->c is a bridge.
    graph = _graph(
        _nodes("a::A", "b::B", "c::C"),
        [
            {"source": "a::A", "target": "b::B", "edge_type": "call"},
            {"source": "a::A", "target": "b::B", "edge_type": "call"},  # parallel
            {"source": "b::B", "target": "c::C", "edge_type": "call"},  # bridge
        ],
    )
    bridges = compute_bridges(graph)
    assert len(bridges) == 1, f"expected one bridge, got {bridges}"
    assert bridges[0].source == "b::B" and bridges[0].target == "c::C"
    assert tuple(bridges[0].component_a) == ("a::A", "b::B")
    assert tuple(bridges[0].component_b) == ("c::C",)


def test_reverse_direction_edges_are_not_bridges():
    # a->b and b->a: removing one leaves the other, so not a bridge.
    # b->c is the only bridge.
    graph = _graph(
        _nodes("a::A", "b::B", "c::C"),
        [
            {"source": "a::A", "target": "b::B", "edge_type": "call"},
            {"source": "b::B", "target": "a::A", "edge_type": "call"},  # reverse
            {"source": "b::B", "target": "c::C", "edge_type": "call"},  # bridge
        ],
    )
    bridges = compute_bridges(graph)
    assert len(bridges) == 1, f"expected one bridge, got {bridges}"
    assert bridges[0].source == "b::B" and bridges[0].target == "c::C"
    assert tuple(bridges[0].component_a) == ("a::A", "b::B")
    assert tuple(bridges[0].component_b) == ("c::C",)


def test_bridge_preserves_actual_edge_orientation():
    # Single record c->d: evidence reports the record's actual source/target.
    graph = _graph(
        _nodes("c::C", "d::D"),
        [{"source": "c::C", "target": "d::D", "edge_type": "call"}],
    )
    bridges = compute_bridges(graph)
    assert len(bridges) == 1, f"expected one bridge, got {bridges}"
    assert bridges[0].source == "c::C"
    assert bridges[0].target == "d::D"
    assert tuple(bridges[0].component_a) == ("c::C",)
    assert tuple(bridges[0].component_b) == ("d::D",)


def test_edge_record_attrs_retained_in_coupling_evidence():
    # An edge carrying source_detail must survive into coupling evidence so a
    # reviewer can recompute from graph.edges and distinguish parallel records.
    graph = _graph(
        _nodes("m::x1", "n::y1"),
        [
            {
                "source": "m::x1",
                "target": "n::y1",
                "edge_type": "call",
                "source_detail": "m::x1::foo",
                "confidence": "static",
            }
        ],
    )
    couplings = {c.module: c for c in compute_coupling(graph)}
    m = couplings["m"]
    assert m.crossing_edges == 1
    assert m.edges[0]["source_detail"] == "m::x1::foo"
    assert m.edges[0]["confidence"] == "static"
    assert m.edges[0]["source"] == "m::x1"
    assert m.edges[0]["target"] == "n::y1"


def test_edge_record_attrs_retained_in_cycle_evidence():
    graph = _graph(
        _nodes("a::A", "b::B"),
        [
            {
                "source": "a::A",
                "target": "b::B",
                "edge_type": "call",
                "source_detail": "a::A::call_b",
            },
            {
                "source": "b::B",
                "target": "a::A",
                "edge_type": "call",
                "source_detail": "b::B::call_a",
            },
        ],
    )
    cycles = compute_cycles(graph)
    assert len(cycles) == 1
    details = {(e["source"], e["target"]): e for e in cycles[0].edges}
    assert details[("a::A", "b::B")]["source_detail"] == "a::A::call_b"
    assert details[("b::B", "a::A")]["source_detail"] == "b::B::call_a"


def test_cycle_evidence_keeps_parallel_same_type_records():
    # Parallel a->b records with distinct source_detail must both survive.
    graph = _graph(
        _nodes("a::A", "b::B"),
        [
            {
                "source": "a::A",
                "target": "b::B",
                "edge_type": "call",
                "source_detail": "a::A::call_b_one",
            },
            {
                "source": "a::A",
                "target": "b::B",
                "edge_type": "call",
                "source_detail": "a::A::call_b_two",
            },
            {
                "source": "b::B",
                "target": "a::A",
                "edge_type": "call",
                "source_detail": "b::B::call_a",
            },
        ],
    )
    cycles = compute_cycles(graph)
    assert len(cycles) == 1
    assert len(cycles[0].edges) == 3, cycles[0].edges
    details = [(e["source"], e["target"], e["source_detail"]) for e in cycles[0].edges]
    assert ("a::A", "b::B", "a::A::call_b_one") in details
    assert ("a::A", "b::B", "a::A::call_b_two") in details
    assert ("b::B", "a::A", "b::B::call_a") in details


def test_parallel_cycle_edges_survive_save_and_load(tmp_path):
    graph = _graph(
        _nodes("a::A", "b::B"),
        [
            {
                "source": "a::A",
                "target": "b::B",
                "edge_type": "call",
                "source_detail": "a::A::call_b_one",
            },
            {
                "source": "a::A",
                "target": "b::B",
                "edge_type": "call",
                "source_detail": "a::A::call_b_two",
            },
            {
                "source": "b::B",
                "target": "a::A",
                "edge_type": "call",
                "source_detail": "b::B::call_a",
            },
        ],
    )
    report = compute_architecture_metrics(graph)
    path = save_report(tmp_path, report)
    loaded = load_report(tmp_path)
    assert loaded is not None
    assert len(loaded.cycles) == 1
    edges = loaded.cycles[0].edges
    assert len(edges) == 3
    details = [(e["source"], e["target"], e["source_detail"]) for e in edges]
    assert ("a::A", "b::B", "a::A::call_b_one") in details
    assert ("a::A", "b::B", "a::A::call_b_two") in details
    assert ("b::B", "a::A", "b::B::call_a") in details


def test_bridge_evidence_preserves_full_edge_record():
    graph = _graph(
        _nodes("c::C", "d::D"),
        [
            {
                "source": "c::C",
                "target": "d::D",
                "edge_type": "call",
                "source_detail": "c::C::invoke_d",
                "confidence": "dynamic",
            }
        ],
    )
    bridges = compute_bridges(graph)
    assert len(bridges) == 1
    assert bridges[0].source == "c::C"
    assert bridges[0].target == "d::D"
    assert bridges[0].edge["source_detail"] == "c::C::invoke_d"
    assert bridges[0].edge["confidence"] == "dynamic"
    assert tuple(bridges[0].component_a) == ("c::C",)
    assert tuple(bridges[0].component_b) == ("d::D",)


def test_full_edge_record_survives_save_report(tmp_path):
    graph = _graph(
        _nodes("c::C", "d::D"),
        [
            {
                "source": "c::C",
                "target": "d::D",
                "edge_type": "call",
                "source_detail": "c::C::invoke_d",
            }
        ],
    )
    report = compute_architecture_metrics(graph)
    path = save_report(tmp_path, report)
    payload = json.loads(path.read_text(encoding="utf-8"))
    bridge = payload["bridges"][0]
    assert bridge["edge"]["source_detail"] == "c::C::invoke_d"
    assert bridge["source"] == "c::C"
    assert bridge["target"] == "d::D"


def _all_node_ids_safe(graph: ArchitectureGraph) -> int:
    ids = set()
    for node in graph.nodes:
        ids.add(str(node.get("id", "")).strip())
    for edge in graph.edges:
        ids.add(str(edge.get("source", "")).strip())
        ids.add(str(edge.get("target", "")).strip())
    ids.discard("")
    return len(ids)


def test_save_report_roundtrip_is_byte_identical(tmp_path):
    graph = _graph(
        _nodes("m::x1", "m::x2"),
        [{"source": "m::x1", "target": "m::x2", "edge_type": "call"}],
    )
    report = compute_architecture_metrics(graph)
    path = save_report(tmp_path, report)
    first = path.read_text(encoding="utf-8")
    save_report(tmp_path, report)
    second = path.read_text(encoding="utf-8")
    assert first == second
    reparsed = json.loads(first)
    assert set(reparsed.keys()) == {"coupling", "cycles", "hubs", "bridges", "metadata"}
