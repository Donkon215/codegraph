from codegraph.architecture_graph import ArchitectureGraph
from codegraph.architecture_reconcile import reconcile_graphs
from codegraph.cli import architecture as arch_cli
from click.testing import CliRunner


def test_reconciliation_matches_applied_prediction():
    predicted = ArchitectureGraph(
        nodes=[{"id": "a"}, {"id": "b"}],
        edges=[{"source": "a", "target": "b", "edge_type": "call"}],
        metadata={"constraints": [{"constraint_type": "forbidden", "source": "x", "target": "y"}]},
    )
    actual = ArchitectureGraph(
        nodes=[{"id": "a"}, {"id": "b"}],
        edges=[{"source": "a", "target": "b", "edge_type": "call"}],
        metadata={"constraints": [{"constraint_type": "forbidden", "source": "x", "target": "y"}]},
    )

    assert reconcile_graphs(predicted, actual)["matches"] is True


def test_reconciliation_reports_divergence():
    predicted = ArchitectureGraph(nodes=[{"id": "a"}, {"id": "b"}], edges=[
        {"source": "a", "target": "b", "edge_type": "call"},
    ])
    actual = ArchitectureGraph(nodes=[{"id": "a"}, {"id": "c"}], edges=[
        {"source": "a", "target": "c", "edge_type": "call"},
    ])

    report = reconcile_graphs(predicted, actual)

    assert report["matches"] is False
    assert report["predicted_only_nodes"] == ["b"]
    assert report["actual_only_nodes"] == ["c"]
    assert report["predicted_only_edges"] == [["a", "b", "call"]]
    assert report["actual_only_edges"] == [["a", "c", "call"]]


def test_arch_reconcile_command_emits_report(monkeypatch, tmp_path):
    predicted = ArchitectureGraph(nodes=[{"id": "predicted.py"}])
    actual = ArchitectureGraph(nodes=[{"id": "actual.py"}])
    monkeypatch.setattr(arch_cli, "_resolve_root", lambda ctx: tmp_path)
    monkeypatch.setattr(ArchitectureGraph, "load_predicted", classmethod(lambda cls, path: predicted))
    monkeypatch.setattr(ArchitectureGraph, "load", classmethod(lambda cls, root: actual))

    result = CliRunner().invoke(arch_cli.arch_reconcile_cmd, ["--json"], obj={"verbose": False})

    assert result.exit_code == 0, result.output
    assert '"matches": false' in result.output
    assert "actual.py" in result.output
