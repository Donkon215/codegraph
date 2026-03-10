"""Tests for codegraph.drift_detector."""

from __future__ import annotations

from pathlib import Path

from codegraph.arch_schema import (
    ArchComponent,
    ArchEdge,
    SubsystemDef,
    SystemArchitecture,
)
from codegraph.drift_detector import (
    DriftFinding,
    DriftReport,
    detect_drift,
)
from codegraph.models.graph0 import Graph0, Graph0Node


# ── helpers ────────────────────────────────────────────────────────────


def _make_arch() -> SystemArchitecture:
    return SystemArchitecture(
        name="test",
        subsystems=[
            SubsystemDef(
                name="core",
                components=[
                    ArchComponent(name="engine", module="codegraph/engine.py"),
                ],
            ),
            SubsystemDef(
                name="models",
                components=[
                    ArchComponent(name="graph0", module="codegraph/models/graph0.py"),
                ],
            ),
        ],
        edges=[
            ArchEdge(source="core", target="models"),
        ],
    )


def _make_graph0(files: list[str]) -> Graph0:
    nodes = []
    for i, f in enumerate(files):
        nodes.append(Graph0Node(
            id=f"{f}::func_{i}",
            body_hash=f"hash_{i}",
            file=f,
            type="function",
            line=i + 1,
        ))
    return Graph0(nodes=nodes)


# ── DriftFinding ───────────────────────────────────────────────────────


class TestDriftFinding:
    def test_to_dict(self):
        f = DriftFinding(
            drift_type="undeclared_module",
            severity="warning",
            description="Module foo.py not in arch",
            module="foo.py",
        )
        d = f.to_dict()
        assert d["drift_type"] == "undeclared_module"
        assert d["severity"] == "warning"

    def test_to_dict_minimal(self):
        f = DriftFinding(drift_type="missing_module", description="gone")
        d = f.to_dict()
        assert "module" not in d  # empty string omitted


# ── DriftReport ────────────────────────────────────────────────────────


class TestDriftReport:
    def test_no_drift(self):
        r = DriftReport()
        assert not r.has_drift
        assert r.error_count == 0
        assert r.warning_count == 0

    def test_with_findings(self):
        r = DriftReport(findings=[
            DriftFinding(drift_type="undeclared_module", severity="warning", description="a"),
            DriftFinding(drift_type="missing_module", severity="error", description="b"),
        ])
        assert r.has_drift
        assert r.error_count == 1
        assert r.warning_count == 1

    def test_findings_by_type(self):
        r = DriftReport(findings=[
            DriftFinding(drift_type="undeclared_module", severity="warning", description="a"),
            DriftFinding(drift_type="undeclared_module", severity="warning", description="b"),
            DriftFinding(drift_type="missing_module", severity="error", description="c"),
        ])
        by_type = r.findings_by_type
        assert by_type["undeclared_module"] == 2
        assert by_type["missing_module"] == 1

    def test_save(self, tmp_path: Path):
        r = DriftReport(
            findings=[DriftFinding(drift_type="undeclared_module", description="a")],
            drift_score=0.5,
        )
        path = r.save(tmp_path)
        assert path.exists()

    def test_format(self):
        r = DriftReport(
            findings=[DriftFinding(drift_type="undeclared_module", severity="warning", description="foo")],
            drift_score=0.1,
            declared_module_count=10,
            actual_module_count=12,
        )
        text = r.format()
        assert "DRIFT DETECTED" in text
        assert "10.0%" in text

    def test_format_no_drift(self):
        r = DriftReport()
        text = r.format()
        assert "NO DRIFT" in text


# ── detect_drift ───────────────────────────────────────────────────────


class TestDetectDrift:
    def test_no_drift(self):
        arch = _make_arch()
        graph0 = _make_graph0(["codegraph/engine.py", "codegraph/models/graph0.py"])
        edges = [("codegraph/engine.py", "codegraph/models/graph0.py")]
        report = detect_drift(arch, graph0, edges)
        # No undeclared, no missing deps (core→models exists)
        undeclared = [f for f in report.findings if f.drift_type == "undeclared_module"]
        assert len(undeclared) == 0

    def test_undeclared_module(self):
        arch = _make_arch()
        graph0 = _make_graph0([
            "codegraph/engine.py",
            "codegraph/models/graph0.py",
            "other_pkg/unknown.py",  # not in any subsystem or known prefix
        ])
        report = detect_drift(arch, graph0, [])
        undeclared = [f for f in report.findings if f.drift_type == "undeclared_module"]
        assert len(undeclared) >= 1
        assert "unknown.py" in undeclared[0].description

    def test_skips_test_files(self):
        arch = _make_arch()
        graph0 = _make_graph0([
            "codegraph/engine.py",
            "tests/test_engine.py",  # should be skipped
        ])
        report = detect_drift(arch, graph0, [])
        undeclared = [f for f in report.findings if f.drift_type == "undeclared_module"]
        test_findings = [f for f in undeclared if "tests/" in f.description]
        assert len(test_findings) == 0

    def test_missing_module(self, tmp_path: Path):
        arch = _make_arch()
        graph0 = _make_graph0(["codegraph/engine.py"])
        # codegraph/models/graph0.py is declared but doesn't exist on disk
        report = detect_drift(arch, graph0, [], project_root=tmp_path)
        missing = [f for f in report.findings if f.drift_type == "missing_module"]
        assert len(missing) >= 1

    def test_undeclared_dependency(self):
        arch = _make_arch()
        graph0 = _make_graph0(["codegraph/engine.py", "codegraph/models/graph0.py"])
        # models → core is not a declared edge
        edges = [("codegraph/models/graph0.py", "codegraph/engine.py")]
        report = detect_drift(arch, graph0, edges)
        undeclared_deps = [f for f in report.findings if f.drift_type == "undeclared_dependency"]
        assert len(undeclared_deps) >= 1

    def test_missing_dependency(self):
        arch = _make_arch()
        graph0 = _make_graph0(["codegraph/engine.py", "codegraph/models/graph0.py"])
        # core → models is declared but no actual edges exist
        edges = []
        report = detect_drift(arch, graph0, edges)
        missing_deps = [f for f in report.findings if f.drift_type == "missing_dependency"]
        assert len(missing_deps) >= 1

    def test_drift_score(self):
        arch = _make_arch()
        graph0 = _make_graph0([
            "codegraph/engine.py",
            "codegraph/models/graph0.py",
            "other_pkg/unknown.py",
        ])
        report = detect_drift(arch, graph0, [])
        assert report.drift_score > 0.0
        assert report.drift_score <= 1.0

    def test_module_counts(self):
        arch = _make_arch()
        graph0 = _make_graph0(["codegraph/engine.py", "codegraph/models/graph0.py"])
        report = detect_drift(arch, graph0, [])
        assert report.declared_module_count == 2
        assert report.actual_module_count == 2
