"""Tests for codegraph.arch_policy — Architecture Policy Engine."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from codegraph.arch_policy import (
    ArchPolicy,
    PolicyViolation,
    PolicyReport,
    add_policy,
    evaluate_policies,
    init_default_policies,
    load_policies,
    remove_policy,
    save_policies,
    VALID_POLICY_TYPES,
    VALID_ACTIONS,
)


# ── Helpers ────────────────────────────────────────────────────────────


def _setup_codegraph(tmp_path: Path) -> None:
    """Create .codegraph structure for policy tests."""
    (tmp_path / ".codegraph" / "policies").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".codegraph" / "graphs").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".codegraph" / "architecture").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".codegraph" / "health").mkdir(parents=True, exist_ok=True)

    # Minimal graph0.json
    graph0 = {
        "nodes": [
            {"id": "a.py::f1", "file": "a.py", "type": "function"},
            {"id": "a.py::f2", "file": "a.py", "type": "function"},
            {"id": "b.py::g1", "file": "b.py", "type": "function"},
        ],
    }
    (tmp_path / ".codegraph" / "graphs" / "graph0.json").write_text(
        json.dumps(graph0), encoding="utf-8",
    )

    # Minimal system.json
    arch = {
        "subsystems": [
            {"name": "core", "components": [
                {"name": "a", "module": "a.py"},
                {"name": "b", "module": "b.py"},
            ]},
        ],
    }
    (tmp_path / ".codegraph" / "architecture" / "system.json").write_text(
        json.dumps(arch), encoding="utf-8",
    )

    # Minimal health report
    health = {"overall_score": 0.7, "coupling": 0.3}
    (tmp_path / ".codegraph" / "health" / "health_report.json").write_text(
        json.dumps(health), encoding="utf-8",
    )


# ── Policy Data Class ─────────────────────────────────────────────────


class TestArchPolicy:
    def test_round_trip(self):
        p = ArchPolicy(
            policy_id="pol_001", name="test",
            policy_type="no_large_modules", rule="limit 50",
            action="warn", threshold=50,
        )
        d = p.to_dict()
        restored = ArchPolicy.from_dict(d)
        assert restored.name == "test"
        assert restored.threshold == 50

    def test_defaults(self):
        p = ArchPolicy(
            policy_id="p1", name="n",
            policy_type="custom", rule="r",
        )
        assert p.action == "warn"
        assert p.enabled is True


class TestPolicyViolation:
    def test_to_dict(self):
        v = PolicyViolation(
            policy_id="pol_001", policy_name="test",
            description="big module", action="warn",
        )
        d = v.to_dict()
        assert d["action"] == "warn"


class TestPolicyReport:
    def test_format_passed(self):
        r = PolicyReport(policies_checked=3, passed=True)
        text = r.format()
        assert "PASSED" in text

    def test_format_blocked(self):
        r = PolicyReport(
            policies_checked=1, passed=False,
            violations=[
                PolicyViolation(
                    policy_id="pol_001", policy_name="gate",
                    description="score too low", action="block",
                ),
            ],
        )
        text = r.format()
        assert "BLOCKED" in text

    def test_to_dict_summary(self):
        r = PolicyReport(policies_checked=2, violations=[
            PolicyViolation("p1", "n", "d", "warn"),
            PolicyViolation("p2", "n", "d", "block"),
        ])
        d = r.to_dict()
        assert d["summary"]["blocking"] == 1
        assert d["summary"]["warnings"] == 1


# ── Policy Store ──────────────────────────────────────────────────────


class TestPolicyStore:
    def test_save_and_load(self, tmp_path: Path):
        _setup_codegraph(tmp_path)
        policies = [
            ArchPolicy("p1", "test", "custom", "rule", "warn"),
        ]
        save_policies(tmp_path, policies)
        loaded = load_policies(tmp_path)
        assert len(loaded) == 1
        assert loaded[0].name == "test"

    def test_load_empty(self, tmp_path: Path):
        loaded = load_policies(tmp_path)
        assert loaded == []

    def test_add_policy(self, tmp_path: Path):
        _setup_codegraph(tmp_path)
        p = add_policy(tmp_path, "test_pol", "no_large_modules",
                        "limit 50", "warn", 50)
        assert p.policy_id.startswith("pol_")
        loaded = load_policies(tmp_path)
        assert len(loaded) == 1

    def test_add_invalid_type(self, tmp_path: Path):
        _setup_codegraph(tmp_path)
        with pytest.raises(ValueError, match="Invalid policy type"):
            add_policy(tmp_path, "bad", "nonexistent_type", "rule")

    def test_add_invalid_action(self, tmp_path: Path):
        _setup_codegraph(tmp_path)
        with pytest.raises(ValueError, match="Invalid action"):
            add_policy(tmp_path, "bad", "custom", "rule", "explode")

    def test_remove_policy(self, tmp_path: Path):
        _setup_codegraph(tmp_path)
        add_policy(tmp_path, "removeme", "custom", "rule")
        assert remove_policy(tmp_path, "pol_001") is True
        assert load_policies(tmp_path) == []

    def test_remove_nonexistent(self, tmp_path: Path):
        _setup_codegraph(tmp_path)
        assert remove_policy(tmp_path, "pol_999") is False


# ── Init Default Policies ─────────────────────────────────────────────


class TestInitDefaults:
    def test_creates_defaults(self, tmp_path: Path):
        _setup_codegraph(tmp_path)
        policies = init_default_policies(tmp_path)
        assert len(policies) >= 3
        types = {p.policy_type for p in policies}
        assert "no_large_modules" in types
        assert "score_gate" in types

    def test_idempotent(self, tmp_path: Path):
        _setup_codegraph(tmp_path)
        first = init_default_policies(tmp_path)
        second = init_default_policies(tmp_path)
        assert len(first) == len(second)


# ── Policy Evaluation ─────────────────────────────────────────────────


class TestEvaluatePolicies:
    def test_no_policies(self, tmp_path: Path):
        _setup_codegraph(tmp_path)
        report = evaluate_policies(tmp_path)
        assert report.passed is True
        assert report.policies_checked == 0

    def test_no_large_modules_pass(self, tmp_path: Path):
        _setup_codegraph(tmp_path)
        add_policy(tmp_path, "size_check", "no_large_modules",
                    "Max 50 nodes", "warn", 50)
        report = evaluate_policies(tmp_path)
        assert report.passed is True
        assert len(report.violations) == 0

    def test_no_large_modules_violation(self, tmp_path: Path):
        _setup_codegraph(tmp_path)
        add_policy(tmp_path, "strict_size", "no_large_modules",
                    "Max 1 node per file", "warn", 1)
        report = evaluate_policies(tmp_path)
        # a.py has 2 nodes, b.py has 1  →  a.py violates
        assert len(report.violations) == 1
        assert report.violations[0].details["file"] == "a.py"

    def test_score_gate_pass(self, tmp_path: Path):
        _setup_codegraph(tmp_path)
        add_policy(tmp_path, "gate", "score_gate",
                    "Min score 0.5", "block", 0.5)
        report = evaluate_policies(tmp_path)
        assert report.passed is True

    def test_score_gate_block(self, tmp_path: Path):
        _setup_codegraph(tmp_path)
        add_policy(tmp_path, "gate", "score_gate",
                    "Min score 0.9", "block", 0.9)
        report = evaluate_policies(tmp_path)
        assert report.passed is False
        assert any(v.action == "block" for v in report.violations)

    def test_coupling_limit_pass(self, tmp_path: Path):
        _setup_codegraph(tmp_path)
        add_policy(tmp_path, "coupling", "coupling_limit",
                    "Max coupling 0.5", "warn", 0.5)
        report = evaluate_policies(tmp_path)
        assert report.passed is True

    def test_disabled_policy_skipped(self, tmp_path: Path):
        _setup_codegraph(tmp_path)
        p = add_policy(tmp_path, "disabled", "no_large_modules",
                        "Max 0 nodes", "block", 0)
        # Disable the policy
        policies = load_policies(tmp_path)
        policies[0].enabled = False
        save_policies(tmp_path, policies)
        report = evaluate_policies(tmp_path)
        assert report.policies_checked == 0

    def test_layer_isolation_violation(self, tmp_path: Path):
        _setup_codegraph(tmp_path)
        # Add a second subsystem and an edge to architecture
        arch = {
            "subsystems": [
                {"name": "core", "components": [{"name": "a", "module": "a.py"}]},
                {"name": "utils", "components": [{"name": "b", "module": "b.py"}]},
            ],
            "edges": [{"from": "core", "to": "utils"}],
            "constraints": [],
        }
        (tmp_path / ".codegraph" / "architecture" / "system.json").write_text(
            json.dumps(arch))
        add_policy(tmp_path, "layer_iso", "layer_isolation",
                    "Core must not depend on utils", "block",
                    target="core->utils")
        report = evaluate_policies(tmp_path)
        assert report.passed is False
        assert any(v.policy_name == "layer_iso" for v in report.violations)

    def test_layer_isolation_pass(self, tmp_path: Path):
        _setup_codegraph(tmp_path)
        arch = {
            "subsystems": [
                {"name": "core", "components": [{"name": "a", "module": "a.py"}]},
                {"name": "utils", "components": [{"name": "b", "module": "b.py"}]},
            ],
            "edges": [{"from": "core", "to": "utils"}],
            "constraints": [],
        }
        (tmp_path / ".codegraph" / "architecture" / "system.json").write_text(
            json.dumps(arch))
        # Forbid a direction that doesn't exist
        add_policy(tmp_path, "layer_iso", "layer_isolation",
                    "Utils must not depend on core", "block",
                    target="utils->core")
        report = evaluate_policies(tmp_path)
        assert report.passed is True

    def test_layer_isolation_invalid_target(self, tmp_path: Path):
        _setup_codegraph(tmp_path)
        # No arrow in target
        add_policy(tmp_path, "bad", "layer_isolation",
                    "Invalid target", "warn", target="core")
        report = evaluate_policies(tmp_path)
        assert len(report.violations) == 0

    def test_forbidden_subsystem_dep_violation(self, tmp_path: Path):
        _setup_codegraph(tmp_path)
        arch = {
            "subsystems": [
                {"name": "core", "components": [{"name": "a", "module": "a.py"}]},
                {"name": "utils", "components": [{"name": "b", "module": "b.py"}]},
            ],
            "edges": [{"from": "core", "to": "utils"}],
            "constraints": [],
        }
        (tmp_path / ".codegraph" / "architecture" / "system.json").write_text(
            json.dumps(arch))
        # core -> utils edge exists
        add_policy(tmp_path, "no_dep", "forbidden_subsystem_dep",
                    "Core must not depend on utils", "block",
                    target="core->utils")
        report = evaluate_policies(tmp_path)
        assert report.passed is False

    def test_forbidden_subsystem_dep_pass(self, tmp_path: Path):
        _setup_codegraph(tmp_path)
        arch = {
            "subsystems": [
                {"name": "core", "components": [{"name": "a", "module": "a.py"}]},
                {"name": "utils", "components": [{"name": "b", "module": "b.py"}]},
            ],
            "edges": [{"from": "core", "to": "utils"}],
            "constraints": [],
        }
        (tmp_path / ".codegraph" / "architecture" / "system.json").write_text(
            json.dumps(arch))
        # This edge doesn't exist
        add_policy(tmp_path, "ok_dep", "forbidden_subsystem_dep",
                    "Utils must not depend on core", "warn",
                    target="utils->core")
        report = evaluate_policies(tmp_path)
        assert len(report.violations) == 0

    def test_valid_policy_types_updated(self):
        assert "layer_isolation" in VALID_POLICY_TYPES
        assert "forbidden_subsystem_dep" in VALID_POLICY_TYPES
