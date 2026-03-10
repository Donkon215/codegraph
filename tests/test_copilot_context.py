"""Tests for codegraph.copilot_context."""

from __future__ import annotations

import json
from pathlib import Path

from codegraph.copilot_context import (
    CopilotContext,
    SubsystemSummary,
    build_copilot_context,
)


# ── SubsystemSummary ───────────────────────────────────────────────────


class TestSubsystemSummary:
    def test_to_dict(self):
        s = SubsystemSummary(
            name="core",
            description="Core engine",
            component_count=3,
            module_paths=["a.py", "b.py"],
            allowed_dependencies=["models"],
            forbidden_dependencies=["infra"],
        )
        d = s.to_dict()
        assert d["name"] == "core"
        assert d["component_count"] == 3
        assert d["modules"] == ["a.py", "b.py"]
        assert d["allowed_deps"] == ["models"]
        assert d["forbidden_deps"] == ["infra"]


# ── CopilotContext ─────────────────────────────────────────────────────


class TestCopilotContext:
    def test_empty(self):
        ctx = CopilotContext()
        assert ctx.graph_version == 0
        assert ctx.node_count == 0

    def test_to_dict(self):
        ctx = CopilotContext(
            graph_version=5,
            node_count=100,
            edge_count=200,
            subsystems=[SubsystemSummary(name="core", component_count=3)],
            constraints=[{"type": "forbidden", "source": "a", "target": "b"}],
            policy_rules=[{"id": "rule_001", "type": "forbidden_call"}],
        )
        d = ctx.to_dict()
        assert d["graph_version"] == 5
        assert d["graph_stats"]["nodes"] == 100
        assert len(d["architecture"]["subsystems"]) == 1
        assert len(d["architecture"]["constraints"]) == 1
        assert len(d["policy_rules"]) == 1

    def test_roundtrip(self):
        ctx = CopilotContext(
            graph_version=5,
            node_count=100,
            edge_count=200,
            subsystems=[
                SubsystemSummary(name="core", description="Core",
                                 component_count=3, module_paths=["a.py"],
                                 allowed_dependencies=["models"],
                                 forbidden_dependencies=["infra"]),
            ],
        )
        d = ctx.to_dict()
        ctx2 = CopilotContext.from_dict(d)
        assert ctx2.graph_version == 5
        assert ctx2.node_count == 100
        assert len(ctx2.subsystems) == 1
        assert ctx2.subsystems[0].name == "core"
        assert ctx2.subsystems[0].allowed_dependencies == ["models"]

    def test_save_load(self, tmp_path: Path):
        ctx = CopilotContext(graph_version=3, node_count=50, edge_count=100)
        ctx.save(tmp_path)
        loaded = CopilotContext.load(tmp_path)
        assert loaded is not None
        assert loaded.graph_version == 3

    def test_load_missing(self, tmp_path: Path):
        assert CopilotContext.load(tmp_path) is None

    def test_format(self):
        ctx = CopilotContext(
            graph_version=5,
            node_count=100,
            edge_count=200,
            subsystems=[
                SubsystemSummary(name="core", component_count=3,
                                 allowed_dependencies=["models"],
                                 forbidden_dependencies=["infra"]),
            ],
            health_summary={"score": 85, "grade": "B"},
            drift_summary={"drift_score": 0.05},
        )
        text = ctx.format()
        assert "v5" in text
        assert "core" in text
        assert "FORBIDDEN" in text


# ── build_copilot_context ──────────────────────────────────────────────


class TestBuildCopilotContext:
    def test_empty_project(self, tmp_path: Path):
        ctx = build_copilot_context(tmp_path)
        assert ctx.graph_version == 0
        assert len(ctx.subsystems) == 0

    def test_with_architecture(self, tmp_path: Path):
        arch_dir = tmp_path / ".codegraph" / "architecture"
        arch_dir.mkdir(parents=True)
        arch_data = {
            "name": "test",
            "version": 1,
            "subsystems": [
                {"name": "core", "description": "Core", "components": [
                    {"name": "engine", "module": "codegraph/engine.py"},
                ]},
                {"name": "models", "components": [
                    {"name": "graph0", "module": "codegraph/models/graph0.py"},
                ]},
            ],
            "edges": [{"source": "core", "target": "models"}],
            "constraints": [{"type": "forbidden", "source": "models", "target": "core", "reason": "No"}],
        }
        (arch_dir / "system.json").write_text(json.dumps(arch_data), encoding="utf-8")
        ctx = build_copilot_context(tmp_path)
        assert len(ctx.subsystems) == 2
        assert ctx.subsystems[0].name == "core"
        assert ctx.subsystems[0].allowed_dependencies == ["models"]
        assert len(ctx.constraints) == 1

    def test_with_graph_stats(self, tmp_path: Path):
        graph_dir = tmp_path / ".codegraph" / "graphs"
        graph_dir.mkdir(parents=True)
        (graph_dir / "graph0.json").write_text(
            json.dumps({"graph_version": 10, "nodes": [{"id": f"n{i}"} for i in range(5)]}),
            encoding="utf-8",
        )
        wf_dir = tmp_path / ".codegraph" / "workflow"
        wf_dir.mkdir(parents=True)
        (wf_dir / "workflow.json").write_text(
            json.dumps({"edges": [{"source": "a", "target": "b"}]}),
            encoding="utf-8",
        )
        ctx = build_copilot_context(tmp_path)
        assert ctx.graph_version == 10
        assert ctx.node_count == 5
        assert ctx.edge_count == 1

    def test_with_policy_rules(self, tmp_path: Path):
        wf_dir = tmp_path / ".codegraph" / "workflow"
        wf_dir.mkdir(parents=True)
        (wf_dir / "suggested_workflow.json").write_text(
            json.dumps({"rules": [
                {"id": "rule_001", "type": "forbidden_call", "source": "a", "target": "b", "reason": "bad"},
            ]}),
            encoding="utf-8",
        )
        ctx = build_copilot_context(tmp_path)
        assert len(ctx.policy_rules) == 1
        assert ctx.policy_rules[0]["id"] == "rule_001"

    def test_with_tasks(self, tmp_path: Path):
        tasks_dir = tmp_path / ".codegraph" / "tasks"
        tasks_dir.mkdir(parents=True)
        (tasks_dir / "tasks.json").write_text(
            json.dumps({"tasks": [
                {"type": "orphan_nodes", "priority": 3, "nodes": ["a", "b"]},
            ]}),
            encoding="utf-8",
        )
        ctx = build_copilot_context(tmp_path)
        assert len(ctx.active_tasks) == 1
        assert ctx.active_tasks[0]["type"] == "orphan_nodes"
        assert ctx.active_tasks[0]["node_count"] == 2

    def test_with_health(self, tmp_path: Path):
        health_dir = tmp_path / ".codegraph" / "architecture"
        health_dir.mkdir(parents=True)
        (health_dir / "health.json").write_text(
            json.dumps({"overall_score": 85, "overall_grade": "B"}),
            encoding="utf-8",
        )
        ctx = build_copilot_context(tmp_path)
        assert ctx.health_summary["score"] == 85
        assert ctx.health_summary["grade"] == "B"

    def test_skip_tasks(self, tmp_path: Path):
        tasks_dir = tmp_path / ".codegraph" / "tasks"
        tasks_dir.mkdir(parents=True)
        (tasks_dir / "tasks.json").write_text(
            json.dumps({"tasks": [{"type": "orphan", "priority": 3, "nodes": ["a"]}]}),
            encoding="utf-8",
        )
        ctx = build_copilot_context(tmp_path, include_tasks=False)
        assert len(ctx.active_tasks) == 0

    def test_with_drift(self, tmp_path: Path):
        drift_dir = tmp_path / ".codegraph" / "architecture"
        drift_dir.mkdir(parents=True)
        (drift_dir / "drift_report.json").write_text(
            json.dumps({
                "has_drift": True,
                "drift_score": 0.15,
                "summary": {"total_findings": 3},
            }),
            encoding="utf-8",
        )
        ctx = build_copilot_context(tmp_path)
        assert ctx.drift_summary["has_drift"] is True
        assert ctx.drift_summary["drift_score"] == 0.15

    def test_with_decisions(self, tmp_path: Path):
        mem_dir = tmp_path / ".codegraph" / "memory"
        mem_dir.mkdir(parents=True)
        (mem_dir / "decisions.json").write_text(
            json.dumps({"decisions": [
                {"decision_id": "d001", "decision": "add rule", "result": "ok"},
                {"decision_id": "d002", "decision": "remove edge", "result": "ok"},
            ]}),
            encoding="utf-8",
        )
        ctx = build_copilot_context(tmp_path)
        assert len(ctx.recent_decisions) == 2
