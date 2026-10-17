"""codegraph issue #71 — deterministic local fixture evaluation.

Single local command that runs the structural analysis over every fixture
in this directory and reports expected-versus-actual differences.

The analysis is produced only by the production analysis APIs:

* :func:`codegraph.build_architecture_overview` — detected communities and
  cross-community coupling evidence;
* :func:`codegraph.compute_architecture_metrics` — standing structural
  metrics (coupling, cycles, hubs, bridges), each shipped with the node ids
  and edges that produced it as evidence;
* :func:`codegraph.map_execution_coverage` — coverage map over architecture
  boundaries (issue #69), advisory only;
* :func:`codegraph.architecture_simulator.simulate_changes` — the issue #70
  ``structural_effect`` output for a proposed change (issue #70), advisory
  only: its consequences describe the change and never influence the verdict.

No metric formula is re-implemented here, and nothing in this harness is a
new metric. Every output list is sorted by the production code and floats are
rounded by the production code, so two runs of an unchanged fixture produce
byte-identical output.

It reads only local fixture files, needs no network or remote service, and
finishes in milliseconds.

Usage:

    python tests/fixtures/architecture/evaluate.py [fixtures_dir]

Exit status is non-zero when any fixture differs from its recorded expected
output. The module is also importable: :func:`evaluate_all` returns the full
report as data.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Set

from codegraph.architecture_execution import map_execution_coverage
from codegraph.architecture_graph import ArchitectureGraph
from codegraph.architecture_metrics import compute_architecture_metrics
from codegraph.architecture_overview import build_architecture_overview
from codegraph.architecture_simulator import simulate_changes
from codegraph.graph_partitioning import build_partitions
from codegraph.models.graph0 import Graph0, Graph0Node
from codegraph.models.graph1 import Graph1, Graph1Node
from codegraph.models.workflow import Workflow, WorkflowEdge

INPUT_FILE = "input.json"
EXPECTED_FILE = "expected.json"

# Graph layer reserved for test code (codegraph.layers.LAYER_TEST == 4).
_TEST_LAYER = 4

# Keys written to the temp project root when a fixture declares a simulation.
_GRAPHS_DIR = Path(".codegraph") / "graphs"
_WORKFLOW_DIR = Path(".codegraph") / "workflow"


# ── Loading ──────────────────────────────────────────────────────────


def _load_json_file(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_graph(fixture_dir: Path) -> ArchitectureGraph:
    """Build a deterministic :class:`ArchitectureGraph` from *fixture_dir/input.json*.

    ``nodes`` are Graph_0 nodes. ``intent`` entries are Graph_1 overlays and may
    carry a ``layer``; nodes at layer 4 are treated as test nodes by the
    coverage map. ``edges`` are workflow edges.
    """

    data = _load_json_file(fixture_dir / INPUT_FILE)

    g0_nodes = [
        Graph0Node(
            id=str(node["id"]),
            body_hash=str(node.get("body_hash", "000000")),
            file=str(node.get("file", "")),
            type=str(node.get("type", "function")),
            line=int(node.get("line", 1)),
        )
        for node in data.get("nodes", [])
    ]
    g1_nodes = [
        Graph1Node(
            id=str(node["id"]),
            layer=int(node.get("layer", 3)),
            intent=str(node.get("intent", "")),
        )
        for node in data.get("intent", [])
    ]
    edges = [
        WorkflowEdge(
            source=str(edge["source"]),
            target=str(edge["target"]),
            edge_type=str(edge.get("edge_type", "call")),
        )
        for edge in data.get("edges", [])
    ]
    return ArchitectureGraph.from_views(
        structure_graph=Graph0(nodes=g0_nodes),
        intent_graph=Graph1(nodes=g1_nodes),
        workflow_graph=Workflow(edges=edges),
    )


def _test_index(graph: ArchitectureGraph) -> SimpleNamespace:
    """Index-store stub exposing graph-assigned layer-4 test nodes.

    Test-ness comes from the graph's layer-4 assignment only, never from a
    ``test_`` file name, matching :func:`map_execution_coverage`.
    """
    test_node_ids: Set[str] = {
        str(node.get("id", "")).strip()
        for node in graph.nodes
        if int(node.get("layer", 3)) == _TEST_LAYER and str(node.get("id", "")).strip()
    }

    def get_nodes_at_layer(layer: int) -> List[str]:
        if layer == _TEST_LAYER:
            return sorted(test_node_ids)
        return []

    return SimpleNamespace(get_nodes_at_layer=get_nodes_at_layer)


def _sim_project_files(data: Dict[str, Any]) -> Dict[str, Any]:
    """Return the graph0/graph1/workflow payloads for *data* (fixture input).

    These are the on-disk views that :func:`ArchitectureGraph.load` reads when
    :func:`codegraph.architecture_simulator.simulate_changes` runs in a temp
    project root. Nothing is written to the source repository.
    """

    g0_nodes = [
        {
            "id": str(node["id"]),
            "body_hash": str(node.get("body_hash", "000000")),
            "file": str(node.get("file", "")),
            "type": str(node.get("type", "function")),
            "line": int(node.get("line", 1)),
        }
        for node in data.get("nodes", [])
    ]
    g1_nodes = [
        {
            "id": str(node["id"]),
            "layer": int(node.get("layer", 3)),
            "intent": str(node.get("intent", "")),
        }
        for node in data.get("intent", [])
    ]
    edges = [
        {
            "source": str(edge["source"]),
            "target": str(edge["target"]),
            "edge_type": str(edge.get("edge_type", "call")),
        }
        for edge in data.get("edges", [])
    ]
    return {
        "graph0": {
            "format_version": 1,
            "graph_version": 1,
            "extracted_at": "",
            "source_files": [],
            "nodes": g0_nodes,
        },
        "graph1": {"format_version": 1, "nodes": g1_nodes},
        "workflow": {
            "format_version": 1,
            "built_at": "",
            "level": "function",
            "edges": edges,
        },
    }


def _simulate_effect(
    fixture_dir: Path, data: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Run the issue #70 simulator over a temp copy of the fixture graph.

    Returns a deterministic subset of the :func:`simulate_changes` result
    (verdict plus the ``structural_effect`` consequences), or ``None`` when
    the fixture does not declare a ``simulation`` scenario.

    A minimal project root is created in a temp directory with only the
    graph views the simulator reads; the index store is absent, so the
    function-level checks are unavailable but the structural effect is still
    computed. Nothing is written to the source repository.
    """

    simulation = data.get("simulation")
    if not simulation:
        return None
    changes = simulation.get("changes")
    if not changes:
        return None

    files = _sim_project_files(data)
    with tempfile.TemporaryDirectory(prefix="arch_eval_sim_") as tmp:
        root = Path(tmp)
        (root / _GRAPHS_DIR).mkdir(parents=True)
        (root / _WORKFLOW_DIR).mkdir(parents=True)
        (root / _GRAPHS_DIR / "graph0.json").write_text(
            json.dumps(files["graph0"], indent=2), encoding="utf-8"
        )
        (root / _GRAPHS_DIR / "graph1.json").write_text(
            json.dumps(files["graph1"], indent=2), encoding="utf-8"
        )
        (root / _WORKFLOW_DIR / "workflow.json").write_text(
            json.dumps(files["workflow"], indent=2), encoding="utf-8"
        )
        result = simulate_changes(root, [dict(change) for change in changes])

    return {
        "status": result.get("status"),
        "simulated": result.get("simulated"),
        "verdict": result.get("verdict"),
        "cycle_risk": result.get("cycle_risk"),
        "coupling_delta": result.get("coupling_delta"),
        "layer_violations_delta": result.get("layer_violations_delta"),
        "score_delta": result.get("score_delta"),
        "structural_effect": result.get("structural_effect", []),
    }


# ── Analysis ─────────────────────────────────────────────────────────


def analyze(fixture_dir: Path) -> Dict[str, Any]:
    """Run the production structural analysis over one fixture.

    The returned dict is the *actual* output that a fixture's
    ``expected.json`` records verbatim. It contains detected communities,
    cross-community coupling evidence, standing structural metrics with
    evidence (coupling, cycles, hubs, bridges), a coverage map over
    architecture boundaries, forbidden-path evidence from the declared graph
    layers, and — when the fixture declares a ``simulation`` scenario — the
    issue #70 ``structural_effect`` produced by
    :func:`codegraph.architecture_simulator.simulate_changes`.
    """

    data = _load_json_file(fixture_dir / INPUT_FILE)
    graph = load_graph(fixture_dir)
    partitions = build_partitions(graph, min_size=1)
    overview = build_architecture_overview(graph, partitions=partitions)
    metrics_report = compute_architecture_metrics(graph)
    coverage_map = map_execution_coverage(graph, _test_index(graph), partitions=partitions)

    output: Dict[str, Any] = {
        "graph": {
            "node_count": len(
                {str(n.get("id", "")) for n in graph.nodes if str(n.get("id", ""))}
            ),
            "edge_count": len(graph.edges),
        },
        "forbidden_path": detect_forbidden_paths(graph),
        "communities": [community.to_dict() for community in overview.communities],
        "cross_community_links": [
            link.to_dict() for link in overview.cross_community_links
        ],
        "metrics": {
            "coupling": [c.to_dict() for c in metrics_report.coupling],
            "cycles": [c.to_dict() for c in metrics_report.cycles],
            "hubs": [h.to_dict() for h in metrics_report.hubs],
            "bridges": [b.to_dict() for b in metrics_report.bridges],
        },
        "coverage_map": coverage_map.to_dict(),
    }
    simulation = _simulate_effect(fixture_dir, data)
    if simulation is not None:
        output["simulation"] = simulation
    return output


def detect_forbidden_paths(graph: ArchitectureGraph) -> List[Dict[str, Any]]:
    """Record upward layer violations as forbidden-path evidence.

    An edge ``source -> target`` is a forbidden path when both endpoints carry
    declared graph layers and the source's layer number is lower than the
    target's (a call from a shallower layer into a deeper one, against the
    declared layering). This documents the fixture's declared violation; the
    production enforcement path lives in :mod:`codegraph.analyzer`.
    """
    node_layers: Dict[str, int] = {}
    for node in graph.nodes:
        nid = str(node.get("id", "")).strip()
        layer = node.get("layer")
        if nid and layer is not None:
            try:
                node_layers[nid] = int(layer)
            except (TypeError, ValueError):
                continue
    violations: List[Dict[str, Any]] = []
    for edge in graph.edges:
        source = str(edge.get("source", "")).strip()
        target = str(edge.get("target", "")).strip()
        if not source or not target:
            continue
        source_layer = node_layers.get(source)
        target_layer = node_layers.get(target)
        if source_layer is None or target_layer is None:
            continue
        if source_layer < target_layer:
            violations.append(
                {
                    "source": source,
                    "target": target,
                    "source_layer": source_layer,
                    "target_layer": target_layer,
                }
            )
    violations.sort(key=lambda v: (v["source"], v["target"]))
    return violations


# ── Comparison ───────────────────────────────────────────────────────


def _compare(expected: Any, actual: Any, path: str = "$") -> List[str]:
    """Deep-compare *expected* against *actual*, returning difference
    messages. Floats are compared rounded to 4 decimals."""
    differences: List[str] = []
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key in sorted(set(expected) | set(actual), key=str):
            if key not in expected:
                differences.append(f"{path}.{key}: missing in expected")
            elif key not in actual:
                differences.append(f"{path}.{key}: missing in actual")
            else:
                differences.extend(_compare(expected[key], actual[key], f"{path}.{key}"))
    elif isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            differences.append(f"{path}: list length {len(expected)} != {len(actual)}")
        else:
            for index, (expected_item, actual_item) in enumerate(zip(expected, actual)):
                differences.extend(_compare(expected_item, actual_item, f"{path}[{index}]"))
    elif isinstance(expected, float) or isinstance(actual, float):
        if round(float(expected), 4) != round(float(actual), 4):
            differences.append(f"{path}: {expected!r} != {actual!r}")
    elif expected != actual:
        differences.append(f"{path}: {expected!r} != {actual!r}")
    return differences


def evaluate_all(fixtures_dir: Path) -> Dict[str, Any]:
    """Run the analysis over every fixture and compare with expected output.

    Returns a report dict with per-fixture ``ok`` flags and difference
    lists. A fixture passes when its actual output matches its recorded
    ``expected.json`` verbatim. Directories without an ``input.json`` are
    not treated as fixtures.
    """
    results: Dict[str, Any] = {}
    fixture_dirs = sorted(
        (
            directory
            for directory in fixtures_dir.iterdir()
            if directory.is_dir() and (directory / INPUT_FILE).exists()
        ),
        key=lambda directory: directory.name,
    )
    for fixture_dir in fixture_dirs:
        name = fixture_dir.name
        result: Dict[str, Any] = {"name": name}
        if not (fixture_dir / EXPECTED_FILE).exists():
            result["ok"] = False
            result["differences"] = [f"missing {EXPECTED_FILE}"]
        else:
            expected = _load_json_file(fixture_dir / EXPECTED_FILE)
            actual = analyze(fixture_dir)
            differences = _compare(expected, actual)
            result["ok"] = not differences
            result["differences"] = differences
            result["actual"] = actual
            result["expected"] = expected
        results[name] = result

    return {
        "fixtures": [result["name"] for result in results.values()],
        "results": results,
        "ok": all(result["ok"] for result in results.values()),
    }


# ── Command line ─────────────────────────────────────────────────────


def main(argv: List[str] | None = None) -> int:
    fixtures_dir = Path(argv[0]) if argv else Path(__file__).resolve().parent
    report = evaluate_all(fixtures_dir)
    print(f"Architecture fixture evaluation: {len(report['fixtures'])} fixture(s)")
    for name in report["fixtures"]:
        result = report["results"][name]
        status = "PASS" if result["ok"] else "FAIL"
        print(f"  [{status}] {name}")
        for difference in result["differences"]:
            print(f"      - {difference}")
    if not report["ok"]:
        print("FAIL: expected-versus-actual differences found")
        return 1
    print("OK: all fixtures match their recorded expected output")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
