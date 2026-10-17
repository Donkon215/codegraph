"""Focused tests for issue #71 — deterministic fixtures and local evaluation.

Covers:
* the local evaluation command over ``tests/fixtures/architecture`` matching
  every fixture against its verbatim recorded expected output;
* that every metric kind (coupling, cycles, hubs, bridges, coverage map) has
  at least one fixture;
* that the hostile fixture deliberately contains a cycle, a hub, a bridge, an
  untested boundary, and a forbidden-path violation in its input graph, and
  that the production analysis surfaces the cycle, bridge, and untested
  boundary in its output;
* that corrupting a fixture's expected output makes evaluation fail (the
  check has teeth);
* determinism of the analysis across runs;
* that the evaluation command is covered by a test.

No production files or the shared CLI are changed. All analysis is produced by
the production APIs (:func:`codegraph.build_architecture_overview`,
:func:`codegraph.compute_architecture_metrics`,
:func:`codegraph.map_execution_coverage`); this harness defines no metric
formulas of its own.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "architecture"

_spec = importlib.util.spec_from_file_location(
    "architecture_evaluation", FIXTURES_DIR / "evaluate.py"
)
_evaluate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_evaluate)
evaluate_all = _evaluate.evaluate_all
analyze = _evaluate.analyze

FIXTURE_NAMES = sorted(
    directory.name
    for directory in FIXTURES_DIR.iterdir()
    if directory.is_dir() and (directory / "input.json").exists()
)

METRIC_KINDS = ("coupling", "cycles", "hubs", "bridges", "coverage")


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _fixture_meta(name: str) -> dict:
    return _load_json(FIXTURES_DIR / name / "meta.json")


def _load_expected(name: str) -> dict:
    return _load_json(FIXTURES_DIR / name / "expected.json")


def _load_input(name: str) -> dict:
    return _load_json(FIXTURES_DIR / name / "input.json")


# ── Suite 1: evaluation matches recorded output ──────────────────────


def test_evaluation_matches_recorded_output():
    report = evaluate_all(FIXTURES_DIR)
    assert report["ok"], report["results"]
    assert set(report["fixtures"]) == set(FIXTURE_NAMES)
    for name in FIXTURE_NAMES:
        assert report["results"][name]["ok"], name


def test_every_metric_kind_has_a_fixture():
    kinds = {_fixture_meta(name).get("metric_kind") for name in FIXTURE_NAMES}
    # "coverage" is demonstrated by the untested_boundary fixture.
    for kind in ("coupling", "cycles", "hubs", "bridges"):
        assert kind in kinds, f"no fixture for metric kind {kind!r}"
    assert any(
        "untested_boundary" == name or "hostile" == name for name in FIXTURE_NAMES
    ), "no fixture exercising the coverage map"


# ── Suite 2: each fixture demonstrates its metric kind ───────────────


def test_coupling_fixture_reports_crossing_edges():
    expected = _load_expected("coupling")
    coupling = expected["metrics"]["coupling"]
    assert any(
        module["module"] == "orders.py" and module["crossing_edges"] >= 1
        for module in coupling
    )
    assert any(
        module["module"] == "payments.py" and module["crossing_edges"] >= 1
        for module in coupling
    )


def test_cycles_fixture_reports_the_cycle():
    expected = _load_expected("cycles")
    cycles = expected["metrics"]["cycles"]
    assert len(cycles) == 1
    assert cycles[0]["nodes"] == ["loop.py::A", "loop.py::B", "loop.py::C"]
    assert cycles[0]["size"] == 3


def test_hubs_fixture_reports_the_hub():
    expected = _load_expected("hubs")
    hubs = expected["metrics"]["hubs"]
    assert len(hubs) == 1
    assert hubs[0]["node_id"] == "hub.py::Hub"
    assert hubs[0]["in_degree"] == 4


def test_bridges_fixture_reports_the_bridge():
    expected = _load_expected("bridges")
    bridges = expected["metrics"]["bridges"]
    assert any(
        bridge["source"] == "left.py::L2"
        and bridge["target"] == "bridge.py::Bridge"
        for bridge in bridges
    )


def test_untested_boundary_fixture_reports_zero_coverage_boundary():
    expected = _load_expected("untested_boundary")
    coverage = expected["coverage_map"]
    assert coverage["evidence"] == "present"
    statuses = {b["boundary_id"]: b["coverage_status"] for b in coverage["boundaries"]}
    assert any(
        status == "zero_coverage" and "unt_py" in boundary_id
        for boundary_id, status in statuses.items()
    ), statuses


def test_forbidden_path_fixture_records_the_layer_violation_in_input():
    """The forbidden-path violation is carried in the fixture input (declared
    layers ui=1 -> api=3) AND surfaced as a produced forbidden_path record in
    the recorded expected output, not merely as a layer field."""
    expected = _load_expected("forbidden_path")
    input_data = _load_input("forbidden_path")
    edges = {(e["source"], e["target"]) for e in input_data["edges"]}
    assert ("ui.py::UI", "api.py::API") in edges
    layers = {n["id"]: n["layer"] for n in input_data["intent"]}
    assert layers["ui.py::UI"] == 1 and layers["api.py::API"] == 3
    # The produced output records the actual forbidden-path violation.
    violations = expected.get("forbidden_path", [])
    assert len(violations) == 1
    assert violations[0] == {
        "source": "ui.py::UI",
        "target": "api.py::API",
        "source_layer": 1,
        "target_layer": 3,
    }
    # Production output still round-trips verbatim.
    assert expected["graph"]["node_count"] == 2
    assert expected["graph"]["edge_count"] == 1


def test_hostile_fixture_contains_all_deliberate_hostile_features():
    input_data = _load_input("hostile")
    edges = {(e["source"], e["target"]) for e in input_data["edges"]}
    layers = {n["id"]: n["layer"] for n in input_data["intent"]}

    # cycle: loop.py::A -> loop.py::B -> loop.py::C -> loop.py::A
    assert ("loop.py::A", "loop.py::B") in edges
    assert ("loop.py::B", "loop.py::C") in edges
    assert ("loop.py::C", "loop.py::A") in edges

    # hub: hub.py::Hub has four direct callers
    fan_in = sum(1 for source, target in edges if target == "hub.py::Hub")
    assert fan_in == 4

    # bridge: left.py::L2 -> bridge.py::Bridge
    assert ("left.py::L2", "bridge.py::Bridge") in edges

    # untested boundary: boundary.py::Gateway calls out but no test reaches it
    assert ("boundary.py::Gateway", "db.py::DB") in edges

    # forbidden path: ui layer 1 -> api layer 3
    assert ("ui.py::UI", "api.py::API") in edges
    assert layers["ui.py::UI"] == 1 and layers["api.py::API"] == 3

    expected = _load_expected("hostile")
    # Production analysis surfaces the cycle, a bridge, and an untested
    # boundary (zero-coverage) in the recorded output.
    cycle_node_lists = [c["nodes"] for c in expected["metrics"]["cycles"]]
    assert ["loop.py::A", "loop.py::B", "loop.py::C"] in cycle_node_lists
    assert any(
        b["source"] == "left.py::L2" and b["target"] == "bridge.py::Bridge"
        for b in expected["metrics"]["bridges"]
    )
    statuses = {
        b["boundary_id"]: b["coverage_status"] for b in expected["coverage_map"]["boundaries"]
    }
    assert any(
        status == "zero_coverage" and "boundary_py" in boundary_id
        for boundary_id, status in statuses.items()
    ), statuses


def test_structural_effect_simulation_output():
    """The structural_effect fixture records the issue #70 simulation output
    (connection added, cycle created, hubs touched, affected nodes) verbatim,
    and the simulator's hard-reject on the new cycle is reflected."""
    expected = _load_expected("structural_effect")
    simulation = expected["simulation"]
    assert simulation["verdict"] == "REJECT"
    assert simulation["cycle_risk"] == 1
    assert simulation["simulated"] is False  # index absent: checks unavailable
    kinds = {c["kind"] for c in simulation["structural_effect"]}
    assert {"connection_added", "cycle_created", "hub_touched", "affected_nodes"} <= kinds
    cycle_created = [
        c for c in simulation["structural_effect"] if c["kind"] == "cycle_created"
    ]
    assert cycle_created == [
        {
            "kind": "cycle_created",
            "description": "new cycle via c.py::C -> a.py::A",
            "nodes": ["c.py::C", "a.py::A"],
            "edges": [{"source": "c.py::C", "target": "a.py::A"}],
        }
    ]


# ── Suite 3: the check has teeth ─────────────────────────────────────


def test_corrupting_expected_output_makes_evaluation_fail(tmp_path: Path):
    """Copy a fixture, corrupt its expected output; evaluation must fail."""
    src = FIXTURES_DIR / "cycles"
    parent = tmp_path / "fixtures"
    dst = parent / "cycles"
    dst.mkdir(parents=True)
    for file_name in ("input.json", "expected.json", "meta.json"):
        (dst / file_name).write_text(
            (src / file_name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    expected_path = dst / "expected.json"
    corrupted = _load_expected("cycles")
    corrupted["metrics"]["cycles"][0]["nodes"][0] = "loop.py::ZZZ"  # recorded: loop.py::A
    expected_path.write_text(json.dumps(corrupted, indent=2), encoding="utf-8")

    report = evaluate_all(parent)
    assert not report["ok"]
    differences = report["results"]["cycles"]["differences"]
    assert differences
    assert any("cycles" in difference for difference in differences)


def test_corrupting_structural_effect_makes_evaluation_fail(tmp_path: Path):
    """Corrupting a fixture's recorded structural_effect makes evaluation fail,
    so the #70 simulator output is actually checked, not just recorded."""
    src = FIXTURES_DIR / "structural_effect"
    parent = tmp_path / "fixtures"
    dst = parent / "structural_effect"
    dst.mkdir(parents=True)
    for file_name in ("input.json", "expected.json", "meta.json"):
        (dst / file_name).write_text(
            (src / file_name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    expected_path = dst / "expected.json"
    corrupted = _load_expected("structural_effect")
    corrupted["simulation"]["verdict"] = "ACCEPT"  # recorded: REJECT
    expected_path.write_text(json.dumps(corrupted, indent=2), encoding="utf-8")

    report = evaluate_all(parent)
    assert not report["ok"]
    differences = report["results"]["structural_effect"]["differences"]
    assert differences
    assert any("verdict" in difference for difference in differences)


# ── Suite 4: determinism ─────────────────────────────────────────────


def test_analysis_is_deterministic_across_runs():
    first = {name: analyze(FIXTURES_DIR / name) for name in FIXTURE_NAMES}
    second = {name: analyze(FIXTURES_DIR / name) for name in FIXTURE_NAMES}
    assert first == second


def test_evaluation_command_is_covered():
    """The evaluation command itself is exercised by a test (acceptance
    criterion: the evaluation command is covered by a test)."""
    report = evaluate_all(FIXTURES_DIR)
    assert report["ok"]


def test_documented_evaluator_command_runs_from_outside_repository(tmp_path: Path):
    """The documented script command imports the package from another cwd."""
    script = FIXTURES_DIR / "evaluate.py"
    completed = subprocess.run(
        [sys.executable, str(script)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "OK: all fixtures match their recorded expected output" in completed.stdout
