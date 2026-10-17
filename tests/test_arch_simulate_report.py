"""Regression tests for issue #70.

Simulated changes report their structural effect on the predicted graph with
node/edge evidence, and separate hard policy findings (may block) from
heuristic signals (never block). Unavailable/skipped checks are reported as
skilled and never presented as a pass.
"""

from __future__ import annotations

from codegraph.architecture_graph import ArchitectureGraph
from codegraph.architecture_simulator import simulate_changes


class _FakeGraph:
    """Minimal stand-in for ArchitectureGraph: only the fields the sandbox reads."""

    def __init__(self, node_ids, edges):
        self.nodes = [{"id": nid} for nid in node_ids]
        self.edges = [dict(e) for e in edges]
        self.adj_out = {}
        for e in edges:
            self.adj_out.setdefault(e["source"], set()).add(e["target"])


def _use_graph(monkeypatch, graph):
    monkeypatch.setattr(ArchitectureGraph, "load", staticmethod(lambda root: graph))


def _use_fuller(
    monkeypatch,
    *,
    available=True,
    blocking=False,
    advisory=False,
    reasons=(),
    violations=(),
):
    result = {
        "available": available,
        "blocking": blocking,
        "advisory": advisory,
        "reasons": list(reasons),
        "blast_radius": 0,
        "violations": [
            {
                "type": v.get("type", ""),
                "severity": v.get("severity", "error"),
                "description": v.get("description", ""),
                "affected_nodes": v.get("affected_nodes", []),
            }
            for v in violations
        ],
    }
    monkeypatch.setattr(
        "codegraph.architecture_simulator._fuller_checks",
        lambda root, changes, sandbox_ids, graph_ids: dict(result),
    )


def _chain():
    return [
        {"source": "chain.py::A", "target": "chain.py::B", "edge_type": "call"},
        {"source": "chain.py::B", "target": "chain.py::C", "edge_type": "call"},
        {"source": "chain.py::C", "target": "chain.py::D", "edge_type": "call"},
    ]


# ── Heuristic signals never block ──────────────────────────────────────


def test_heuristic_score_drop_never_blocks(monkeypatch, tmp_path):
    # Adding A -> D to an acyclic chain raises fan-out (score drops) but
    # creates no cycle, so the verdict must stay clean.
    _use_graph(monkeypatch, _FakeGraph(["chain.py::A", "chain.py::B", "chain.py::C", "chain.py::D"], _chain()))
    _use_fuller(monkeypatch)

    result = simulate_changes(
        tmp_path, [{"change": "add_edge", "node": "chain.py::A", "target": "chain.py::D"}]
    )

    assert result["verdict"] != "REJECT", result["reasons"]
    signals = {s["signal"] for s in result["heuristic_signals"]}
    assert "score_drop" in signals, result["heuristic_signals"]
    assert "coupling_increase" in signals, result["heuristic_signals"]
    assert result["policy_findings"] == [], result["policy_findings"]


def test_heuristic_only_clean_verdict_stays_clean(monkeypatch, tmp_path):
    # No hard constraint is violated: a heuristic move must not turn a clean
    # plan into a rejection, however unfavourable the score delta is.
    _use_graph(monkeypatch, _FakeGraph(["chain.py::A", "chain.py::B", "chain.py::C", "chain.py::D"], _chain()))
    _use_fuller(monkeypatch)

    result = simulate_changes(
        tmp_path, [{"change": "add_edge", "node": "chain.py::A", "target": "chain.py::D"}]
    )

    assert result["verdict"] != "REJECT"
    assert result["policy_findings"] == []
    assert any(s["kind"] == "heuristic" for s in result["heuristic_signals"])


# ── Hard policy findings block and name the rule ───────────────────────


def test_hard_policy_blocks_and_names_rule(monkeypatch, tmp_path):
    _use_graph(monkeypatch, _FakeGraph(["chain.py::A", "chain.py::B", "chain.py::C", "chain.py::D"], _chain()))
    _use_fuller(
        monkeypatch,
        blocking=True,
        reasons=["REJECT new_cycle: A -> D closes a cycle"],
        violations=[
            {
                "type": "new_cycle",
                "severity": "error",
                "description": "A -> D closes a cycle",
                "affected_nodes": ["chain.py::A", "chain.py::D"],
            }
        ],
    )

    result = simulate_changes(
        tmp_path, [{"change": "add_edge", "node": "chain.py::A", "target": "chain.py::D"}]
    )

    assert result["verdict"] == "REJECT"
    assert result["policy_findings"]
    assert result["policy_findings"][0]["kind"] == "policy"
    assert result["policy_findings"][0]["rule"] == "new_cycle"
    assert "A -> D closes a cycle" in result["policy_findings"][0]["description"]


# ── Unavailable / skipped checks ───────────────────────────────────────


def test_skipped_check_is_never_a_pass(monkeypatch, tmp_path):
    _use_graph(monkeypatch, _FakeGraph(["chain.py::A", "chain.py::B", "chain.py::C", "chain.py::D"], _chain()))
    _use_fuller(
        monkeypatch,
        available=False,
        reasons=["rewire_edge is not covered by the function-level checks"],
    )

    result = simulate_changes(
        tmp_path, [{"change": "rewire_edge", "node": "chain.py::A", "target": "chain.py::C"}]
    )

    assert result["simulated"] is False
    assert result["function_checks_available"] is False
    assert result["verdict"] == "REVIEW"
    checks = result["checks"]
    function_checks = [c for c in checks if c["name"] == "function_level_policy_checks"]
    assert function_checks and function_checks[0]["status"] == "skipped", checks
    # The architecture-cycle check is computed on the sandbox and is reported
    # independently of the (skipped) function-level checks.
    cycle_checks = [c for c in checks if c["name"] == "architecture-cycle"]
    assert cycle_checks and cycle_checks[0]["status"] in {"passed", "failed"}, cycle_checks
    # A skipped check is never presented as a pass: the skipped function-level
    # check carries a skip reason, not "passed".
    assert function_checks[0].get("reason"), function_checks


# ── Structural effect ──────────────────────────────────────────────────


def test_structural_effect_carries_node_and_edge_ids(monkeypatch, tmp_path):
    _use_graph(monkeypatch, _FakeGraph(["chain.py::A", "chain.py::B", "chain.py::C", "chain.py::D"], _chain()))
    _use_fuller(monkeypatch)

    result = simulate_changes(
        tmp_path, [{"change": "add_edge", "node": "chain.py::A", "target": "chain.py::D"}]
    )

    effect = result["structural_effect"]
    assert effect, effect
    added = [c for c in effect if c["kind"] == "connection_added"]
    assert added
    assert added[0]["nodes"] == ["chain.py::A", "chain.py::D"]
    assert len(added[0]["edges"]) == 1
    assert added[0]["edges"][0]["source"] == "chain.py::A"
    assert added[0]["edges"][0]["target"] == "chain.py::D"
    # Full edge record is preserved as evidence.
    assert "edge_type" in added[0]["edges"][0]
    # A cycle was not created by an acyclic addition; no cycle_created kind.
    assert not any(c["kind"] == "cycle_created" for c in effect), effect


def test_structural_effect_is_deterministic(monkeypatch, tmp_path):
    _use_graph(monkeypatch, _FakeGraph(["chain.py::A", "chain.py::B", "chain.py::C", "chain.py::D"], _chain()))
    _use_fuller(monkeypatch)

    first = simulate_changes(
        tmp_path, [{"change": "add_edge", "node": "chain.py::A", "target": "chain.py::D"}]
    )
    second = simulate_changes(
        tmp_path, [{"change": "add_edge", "node": "chain.py::A", "target": "chain.py::D"}]
    )

    assert first["structural_effect"] == second["structural_effect"]


def test_cycle_is_explicit_new_cycle_policy_finding_when_function_checks_unavailable(
    monkeypatch, tmp_path
):
    # D -> A closes the chain into a cycle: an architectural cycle rejection.
    # Function-level checks are unavailable, so the cycle must still surface as
    # an explicit hard policy finding named new_cycle and a failed
    # architecture-cycle check.
    _use_graph(
        monkeypatch,
        _FakeGraph(
            ["chain.py::A", "chain.py::B", "chain.py::C", "chain.py::D"], _chain()
        ),
    )
    _use_fuller(
        monkeypatch,
        available=False,
        reasons=["function-level checks could not run"],
    )

    result = simulate_changes(
        tmp_path, [{"change": "add_edge", "node": "chain.py::D", "target": "chain.py::A"}]
    )

    assert result["verdict"] == "REJECT", result["reasons"]
    cycle_findings = [f for f in result["policy_findings"] if f["rule"] == "new_cycle"]
    assert cycle_findings, result["policy_findings"]
    assert cycle_findings[0]["kind"] == "policy"
    assert cycle_findings[0]["details"]["severity"] == "error"

    cycle_checks = [c for c in result["checks"] if c["name"] == "architecture-cycle"]
    assert cycle_checks
    assert cycle_checks[0]["status"] == "failed", cycle_checks

    # The function-level check is explicitly skipped, never passed.
    function_checks = [c for c in result["checks"] if c["name"] == "function_level_policy_checks"]
    assert function_checks
    assert function_checks[0]["status"] == "skipped", function_checks


def test_cycle_passes_architecture_cycle_check_when_no_cycle(monkeypatch, tmp_path):
    _use_graph(
        monkeypatch,
        _FakeGraph(
            ["chain.py::A", "chain.py::B", "chain.py::C", "chain.py::D"], _chain()
        ),
    )
    _use_fuller(monkeypatch, available=False, reasons=["index missing"])

    result = simulate_changes(
        tmp_path, [{"change": "add_edge", "node": "chain.py::A", "target": "chain.py::D"}]
    )

    assert result["verdict"] != "REJECT", result["reasons"]
    assert not any(f["rule"] == "new_cycle" for f in result["policy_findings"]), result[
        "policy_findings"
    ]
    cycle_checks = [c for c in result["checks"] if c["name"] == "architecture-cycle"]
    assert cycle_checks and cycle_checks[0]["status"] == "passed", cycle_checks


def test_parallel_edges_diff_is_multigraph_aware(monkeypatch, tmp_path):
    # Two parallel A -> B records; adding a third reports exactly one added
    # record rather than collapsing the pair away.
    graph = _FakeGraph(
        ["star.py::A", "star.py::B"],
        [
            {"source": "star.py::A", "target": "star.py::B", "edge_type": "call"},
            {"source": "star.py::A", "target": "star.py::B", "edge_type": "call"},
        ],
    )
    _use_graph(monkeypatch, graph)
    _use_fuller(monkeypatch)

    result = simulate_changes(
        tmp_path, [{"change": "add_edge", "node": "star.py::A", "target": "star.py::B"}]
    )

    added = [c for c in result["structural_effect"] if c["kind"] == "connection_added"]
    assert len(added) == 1, result["structural_effect"]
    assert added[0]["edges"][0]["source"] == "star.py::A"
    assert added[0]["edges"][0]["target"] == "star.py::B"

    # Removing one of three parallel records reports exactly one removed record
    # and leaves the pair connected.
    graph3 = _FakeGraph(
        ["star.py::A", "star.py::B"],
        [
            {"source": "star.py::A", "target": "star.py::B", "edge_type": "call"},
            {"source": "star.py::A", "target": "star.py::B", "edge_type": "call"},
            {"source": "star.py::A", "target": "star.py::B", "edge_type": "call"},
        ],
    )
    _use_graph(monkeypatch, graph3)

    result3 = simulate_changes(
        tmp_path, [{"change": "remove_edge", "node": "star.py::A", "target": "star.py::B"}]
    )

    removed = [c for c in result3["structural_effect"] if c["kind"] == "connection_removed"]
    # remove_edge drops every matching parallel record; each is preserved as evidence.
    assert len(removed) == 3, result3["structural_effect"]
    assert all(
        c["edges"][0]["source"] == "star.py::A" and c["edges"][0]["target"] == "star.py::B"
        for c in removed
    )


def test_parallel_edges_with_different_attributes_diff_by_full_record(
    monkeypatch, tmp_path
):
    # Same endpoints and type but different source_detail are distinct records;
    # adding one must report the actual new full record, not collapse by endpoint.
    graph = _FakeGraph(
        ["star.py::A", "star.py::B"],
        [
            {
                "source": "star.py::A",
                "target": "star.py::B",
                "edge_type": "call",
                "source_detail": "existing",
            },
            {
                "source": "star.py::A",
                "target": "star.py::B",
                "edge_type": "call",
                "source_detail": "existing",
            },
        ],
    )
    _use_graph(monkeypatch, graph)
    _use_fuller(monkeypatch)

    result = simulate_changes(
        tmp_path,
        [
            {
                "change": "add_edge",
                "node": "star.py::A",
                "target": "star.py::B",
                # Full record passed through as the change's edge evidence.
            },
        ],
    )

    added = [c for c in result["structural_effect"] if c["kind"] == "connection_added"]
    assert len(added) == 1, result["structural_effect"]
    record = added[0]["edges"][0]
    assert record["source"] == "star.py::A"
    assert record["target"] == "star.py::B"
    assert record["source_detail"] == "simulated"


def test_hub_touched_uses_compute_hubs_before_and_after(monkeypatch, tmp_path):
    # A is a hub (three inbound callers B, C, D). Touching A via A -> B must
    # produce hub_touched evidence derived from compute_hubs(), including the
    # caller evidence and before/after hub metrics.
    graph = _FakeGraph(
        ["hub.py::A", "hub.py::B", "hub.py::C", "hub.py::D"],
        [
            {"source": "hub.py::B", "target": "hub.py::A", "edge_type": "call"},
            {"source": "hub.py::C", "target": "hub.py::A", "edge_type": "call"},
            {"source": "hub.py::D", "target": "hub.py::A", "edge_type": "call"},
        ],
    )
    _use_graph(monkeypatch, graph)
    _use_fuller(monkeypatch)

    result = simulate_changes(
        tmp_path, [{"change": "add_edge", "node": "hub.py::A", "target": "hub.py::B"}]
    )

    hubs = [c for c in result["structural_effect"] if c["kind"] == "hub_touched"]
    assert hubs, result["structural_effect"]
    hub = hubs[0]
    assert hub["nodes"] == ["hub.py::A"]
    assert sorted(e["source"] for e in hub["edges"]) == ["hub.py::B", "hub.py::C", "hub.py::D"]
    assert hub["evidence"]["after"] is not None
    assert hub["evidence"]["after"]["callers"] == ["hub.py::B", "hub.py::C", "hub.py::D"]
    assert hub["evidence"]["after"]["node_id"] == "hub.py::A"


# ── JSON and human output separation ───────────────────────────────────


def test_json_output_carries_policy_heuristic_structure_and_checks(monkeypatch, tmp_path):
    import json

    from click.testing import CliRunner

    from codegraph.cli import architecture as arch_cli

    _use_graph(monkeypatch, _FakeGraph(["chain.py::A", "chain.py::B", "chain.py::C", "chain.py::D"], _chain()))
    _use_fuller(
        monkeypatch,
        blocking=True,
        reasons=["REJECT new_cycle: A -> D closes a cycle"],
        violations=[
            {
                "type": "new_cycle",
                "severity": "error",
                "description": "A -> D closes a cycle",
                "affected_nodes": ["chain.py::A", "chain.py::D"],
            }
        ],
    )

    plan_file = tmp_path / "plan.json"
    plan_file.write_text(
        '[{"change": "add_edge", "node": "chain.py::A", "target": "chain.py::D"}]',
        encoding="utf-8",
    )
    monkeypatch.setattr(arch_cli, "find_project_root", lambda: tmp_path)

    result = CliRunner().invoke(
        arch_cli.arch_simulate_cmd, ["--plan", str(plan_file), "--json"], obj={"verbose": False}
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    # Machine-detectable separation: top-level keys distinct from the free-text
    # human report, present in every JSON payload.
    assert "policy_findings" in payload
    assert "heuristic_signals" in payload
    assert "structural_effect" in payload
    assert "checks" in payload
    assert payload["policy_findings"][0]["rule"] == "new_cycle"


def test_human_output_labels_policy_and_heuristic_separately(monkeypatch, tmp_path):
    from click.testing import CliRunner

    from codegraph.cli import architecture as arch_cli

    _use_graph(monkeypatch, _FakeGraph(["chain.py::A", "chain.py::B", "chain.py::C", "chain.py::D"], _chain()))
    _use_fuller(
        monkeypatch,
        blocking=True,
        reasons=["REJECT new_cycle: A -> D closes a cycle"],
        violations=[
            {
                "type": "new_cycle",
                "severity": "error",
                "description": "A -> D closes a cycle",
                "affected_nodes": ["chain.py::A", "chain.py::D"],
            }
        ],
    )

    plan_file = tmp_path / "plan.json"
    plan_file.write_text(
        '[{"change": "add_edge", "node": "chain.py::A", "target": "chain.py::D"}]',
        encoding="utf-8",
    )
    monkeypatch.setattr(arch_cli, "find_project_root", lambda: tmp_path)

    result = CliRunner().invoke(
        arch_cli.arch_simulate_cmd, ["--plan", str(plan_file)], obj={"verbose": False}
    )

    assert result.exit_code == 0, result.output
    text = result.output
    assert "Policy findings" in text
    assert "new_cycle" in text
    assert "Heuristic signals" in text
    assert "Structural effect" in text
