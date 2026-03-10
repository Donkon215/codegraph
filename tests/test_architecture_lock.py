"""Tests for codegraph.architecture_lock."""

from __future__ import annotations

from codegraph.arch_schema import (
    ArchComponent,
    ArchConstraint,
    ArchEdge,
    SubsystemDef,
    SystemArchitecture,
)
from codegraph.architecture_lock import (
    LockReport,
    LockViolation,
    check_dependency_allowed,
    check_lock,
    check_module_placement,
)


# ── helpers ────────────────────────────────────────────────────────────


def _make_arch() -> SystemArchitecture:
    return SystemArchitecture(
        name="test",
        subsystems=[
            SubsystemDef(
                name="core",
                components=[
                    ArchComponent(name="engine", module="codegraph/engine.py"),
                    ArchComponent(name="extractor", module="codegraph/extractor.py"),
                ],
            ),
            SubsystemDef(
                name="models",
                components=[
                    ArchComponent(name="graph0", module="codegraph/models/graph0.py"),
                ],
            ),
            SubsystemDef(
                name="infra",
                components=[
                    ArchComponent(name="cli", module="codegraph/cli.py"),
                ],
            ),
        ],
        edges=[
            ArchEdge(source="core", target="models"),
            ArchEdge(source="infra", target="core"),
        ],
        constraints=[
            ArchConstraint(
                constraint_type="forbidden",
                source="models",
                target="core",
                reason="Models must not import core",
            ),
        ],
    )


# ── LockViolation ─────────────────────────────────────────────────────


class TestLockViolation:
    def test_to_dict(self):
        v = LockViolation(
            violation_type="forbidden_dependency",
            severity="error",
            description="Bad import",
            module="foo.py",
            subsystem="core",
            suggestion="Remove it",
        )
        d = v.to_dict()
        assert d["type"] == "forbidden_dependency"
        assert d["severity"] == "error"
        assert d["module"] == "foo.py"
        assert d["suggestion"] == "Remove it"

    def test_to_dict_minimal(self):
        v = LockViolation(violation_type="undeclared_module", description="Undeclared")
        d = v.to_dict()
        assert "module" not in d  # empty fields omitted


# ── LockReport ─────────────────────────────────────────────────────────


class TestLockReport:
    def test_empty_is_locked(self):
        r = LockReport()
        assert r.is_locked
        assert r.error_count == 0

    def test_with_errors_unlocked(self):
        r = LockReport(violations=[
            LockViolation(violation_type="forbidden_dependency", severity="error", description="bad"),
        ])
        assert not r.is_locked
        assert r.error_count == 1

    def test_warnings_still_locked(self):
        r = LockReport(violations=[
            LockViolation(violation_type="undeclared_module", severity="warning", description="missing"),
        ])
        assert r.is_locked
        assert r.warning_count == 1

    def test_to_dict(self):
        r = LockReport(checked_modules=5, checked_edges=10)
        d = r.to_dict()
        assert d["locked"] is True
        assert d["checked_modules"] == 5

    def test_format(self):
        r = LockReport(violations=[
            LockViolation(violation_type="forbidden_dependency", severity="error",
                          description="bad dep", suggestion="fix it"),
        ])
        text = r.format()
        assert "UNLOCKED" in text
        assert "bad dep" in text
        assert "fix it" in text


# ── check_lock ─────────────────────────────────────────────────────────


class TestCheckLock:
    def test_clean_lock(self):
        arch = _make_arch()
        modules = ["codegraph/engine.py", "codegraph/models/graph0.py", "codegraph/cli.py"]
        edges = [("codegraph/engine.py", "codegraph/models/graph0.py")]
        report = check_lock(arch, modules, edges)
        assert report.is_locked

    def test_undeclared_module_warning(self):
        arch = _make_arch()
        modules = ["codegraph/engine.py", "unknown/module.py"]
        edges = []
        report = check_lock(arch, modules, edges)
        undeclared = [v for v in report.violations if v.violation_type == "undeclared_module"]
        assert len(undeclared) >= 1
        assert undeclared[0].severity == "warning"

    def test_undeclared_module_strict(self):
        arch = _make_arch()
        modules = ["codegraph/engine.py", "unknown/module.py"]
        edges = []
        report = check_lock(arch, modules, edges, strict=True)
        undeclared = [v for v in report.violations if v.violation_type == "undeclared_module"]
        assert len(undeclared) >= 1
        assert undeclared[0].severity == "error"

    def test_forbidden_dependency_error(self):
        arch = _make_arch()
        modules = ["codegraph/models/graph0.py", "codegraph/engine.py"]
        edges = [("codegraph/models/graph0.py", "codegraph/engine.py")]
        report = check_lock(arch, modules, edges)
        forbidden = [v for v in report.violations if v.violation_type == "forbidden_dependency"]
        assert len(forbidden) >= 1
        assert forbidden[0].severity == "error"

    def test_boundary_violation(self):
        arch = _make_arch()
        modules = ["codegraph/models/graph0.py", "codegraph/cli.py"]
        # models → infra is not a declared edge
        edges = [("codegraph/models/graph0.py", "codegraph/cli.py")]
        report = check_lock(arch, modules, edges)
        boundary = [v for v in report.violations if v.violation_type == "boundary_violation"]
        assert len(boundary) >= 1

    def test_allowed_edge_no_violation(self):
        arch = _make_arch()
        modules = ["codegraph/engine.py", "codegraph/models/graph0.py"]
        # core → models is declared
        edges = [("codegraph/engine.py", "codegraph/models/graph0.py")]
        report = check_lock(arch, modules, edges)
        # Should have no boundary or forbidden violations
        problems = [v for v in report.violations
                     if v.violation_type in ("forbidden_dependency", "boundary_violation")]
        assert len(problems) == 0


# ── check_module_placement ─────────────────────────────────────────────


class TestCheckModulePlacement:
    def test_declared_module_ok(self):
        arch = _make_arch()
        result = check_module_placement("codegraph/engine.py", arch)
        assert result is None

    def test_undeclared_module(self):
        arch = _make_arch()
        result = check_module_placement("unknown/module.py", arch)
        assert result is not None
        assert result.violation_type == "undeclared_module"

    def test_module_under_known_prefix(self):
        arch = _make_arch()
        # codegraph/models/graph0.py is declared, so codegraph/models/other.py
        # should be under a known prefix
        result = check_module_placement("codegraph/models/other.py", arch)
        assert result is None


# ── check_dependency_allowed ───────────────────────────────────────────


class TestCheckDependencyAllowed:
    def test_allowed_dependency(self):
        arch = _make_arch()
        result = check_dependency_allowed(
            "codegraph/engine.py", "codegraph/models/graph0.py", arch
        )
        assert result is None

    def test_forbidden_dependency(self):
        arch = _make_arch()
        result = check_dependency_allowed(
            "codegraph/models/graph0.py", "codegraph/engine.py", arch
        )
        assert result is not None
        assert result.violation_type == "forbidden_dependency"

    def test_same_subsystem(self):
        arch = _make_arch()
        result = check_dependency_allowed(
            "codegraph/engine.py", "codegraph/extractor.py", arch
        )
        assert result is None  # intra-subsystem always allowed

    def test_undeclared_modules(self):
        arch = _make_arch()
        result = check_dependency_allowed(
            "unknown/a.py", "unknown/b.py", arch
        )
        assert result is None  # can't check undeclared

    def test_undeclared_cross_subsystem(self):
        arch = _make_arch()
        # models → infra is not a declared edge and not forbidden
        result = check_dependency_allowed(
            "codegraph/models/graph0.py", "codegraph/cli.py", arch
        )
        assert result is not None
        assert result.violation_type == "boundary_violation"
