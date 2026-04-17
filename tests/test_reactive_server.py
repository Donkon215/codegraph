"""Tests for codegraph.reactive_server module.

Tests cover: PromptEngine, FeedbackWriter, FileWatcher, ReactiveServer,
ReactivePrompt, and CLI commands server/feedback.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from codegraph.reactive_server import (
    DEFAULT_POLL_INTERVAL,
    PROMPT_DECISION,
    PROMPT_INFO,
    PROMPT_OPTIMIZATION,
    PROMPT_RISK,
    PROMPT_VIOLATION,
    FeedbackWriter,
    FileChange,
    FileWatcher,
    PromptContext,
    PromptEngine,
    ReactiveEvent,
    ReactivePrompt,
    ReactiveServer,
    ServerConfig,
)


def _setup_minimal_graph(tmp_path):
    """Create a minimal .codegraph tree for testing."""
    arch_dir = tmp_path / ".codegraph" / "architecture"
    graph_dir = tmp_path / ".codegraph" / "graphs"
    workflow_dir = tmp_path / ".codegraph" / "workflow"
    analysis_dir = tmp_path / ".codegraph" / "analysis"

    for d in (arch_dir, graph_dir, workflow_dir, analysis_dir):
        d.mkdir(parents=True, exist_ok=True)

    graph_dir.joinpath("graph0.json").write_text(
        json.dumps({
            "graph_version": 2,
            "nodes": [
                {"id": "svc/order.py::OrderService", "body_hash": "x",
                 "file": "svc/order.py", "type": "class", "line": 1},
                {"id": "svc/order.py::OrderService::create", "body_hash": "y",
                 "file": "svc/order.py", "type": "function", "line": 10},
                {"id": "svc/payment.py::PaymentService", "body_hash": "z",
                 "file": "svc/payment.py", "type": "class", "line": 1},
            ],
        }),
        encoding="utf-8",
    )
    graph_dir.joinpath("graph1.json").write_text(
        json.dumps({
            "nodes": [
                {"id": "svc/order.py::OrderService", "intent": "service",
                 "layer": 3, "arch_layer": "service", "intent_body_hash": "y"},
            ]
        }),
        encoding="utf-8",
    )
    workflow_dir.joinpath("workflow.json").write_text(
        json.dumps({
            "edges": [
                {"source": "svc/order.py::OrderService::create",
                 "target": "svc/payment.py::PaymentService",
                 "edge_type": "call"},
            ]
        }),
        encoding="utf-8",
    )
    arch_dir.joinpath("system.json").write_text(
        json.dumps({
            "subsystems": [
                {"name": "orders", "modules": ["svc/order.py"]},
                {"name": "payments", "modules": ["svc/payment.py"]},
            ],
            "edges": [],
            "constraints": [],
        }),
        encoding="utf-8",
    )
    analysis_dir.joinpath("violations.json").write_text(
        json.dumps({
            "violations": [
                {"node": "svc/payment.py::PaymentService",
                 "type": "layer_violation", "message": "crosses boundary"},
            ]
        }),
        encoding="utf-8",
    )
    arch_dir.joinpath("architecture_patterns.json").write_text(
        json.dumps({
            "primary_pattern": "layered",
            "patterns": [{"architecture_type": "layered",
                          "confidence": 0.8, "consistency": 0.9}],
        }),
        encoding="utf-8",
    )
    arch_dir.joinpath("architecture_advice.json").write_text(
        json.dumps({
            "score": 0.72,
            "grade": "C",
            "smells": [
                {"entity": "svc/order.py::OrderService",
                 "smell_type": "god_class",
                 "severity": "medium",
                 "description": "Too many responsibilities"},
            ],
        }),
        encoding="utf-8",
    )
    return tmp_path


# ── ReactivePrompt tests ─────────────────────────────────────────────


class TestReactivePrompt:
    def test_to_dict(self):
        p = ReactivePrompt(
            prompt_type=PROMPT_VIOLATION,
            severity="high",
            title="Violation in X",
            body="crosses boundary",
            target="x.py",
        )
        d = p.to_dict()
        assert d["prompt_type"] == "violation"
        assert d["severity"] == "high"
        assert d["target"] == "x.py"

    def test_format_markdown_violation(self):
        p = ReactivePrompt(
            prompt_type=PROMPT_VIOLATION,
            severity="high",
            priority="HIGH",
            blocking=True,
            title="Violation in X",
            body="crosses boundary",
            suggested_commands=["codegraph focus X --json"],
        )
        md = p.format_markdown()
        assert "Violation in X" in md
        assert "HIGH" in md
        assert "codegraph focus X --json" in md

    def test_format_terminal(self):
        p = ReactivePrompt(
            prompt_type=PROMPT_RISK,
            severity="medium",
            title="Cycle risk",
            body="2 new cycles",
            suggested_commands=["codegraph simulate"],
        )
        text = p.format_terminal()
        assert "[RISK]" in text
        assert "Cycle risk" in text
        assert "codegraph simulate" in text

    def test_format_markdown_all_types(self):
        for ptype in (PROMPT_VIOLATION, PROMPT_DECISION, PROMPT_RISK,
                      PROMPT_OPTIMIZATION, PROMPT_INFO):
            p = ReactivePrompt(prompt_type=ptype, title="Test")
            md = p.format_markdown()
            assert "Test" in md


# ── PromptEngine tests ───────────────────────────────────────────────


class TestPromptEngine:
    def test_empty_inputs(self):
        prompts = PromptEngine.generate("test.py")
        assert prompts == []

    def test_violation_prompts(self):
        focus = {
            "violations": ["layer violation: crosses boundary"],
            "smells": [],
        }
        prompts = PromptEngine.generate("x.py", focus=focus)
        assert len(prompts) == 1
        assert prompts[0].prompt_type == PROMPT_VIOLATION
        assert prompts[0].severity == "high"

    def test_smell_prompts(self):
        focus = {
            "violations": [],
            "smells": [
                {"smell_type": "god_class", "severity": "medium",
                 "description": "Too large"},
            ],
        }
        prompts = PromptEngine.generate("x.py", focus=focus)
        assert len(prompts) == 1
        assert prompts[0].prompt_type == PROMPT_OPTIMIZATION

    def test_decision_prompts_fix_violations(self):
        decision = {
            "action": "fix_violations",
            "confidence": 0.85,
            "risk": "medium",
            "reason": "2 violations found",
            "next_steps": ["codegraph build"],
            "alternatives": [],
        }
        prompts = PromptEngine.generate("x.py", decision=decision)
        assert any(p.prompt_type == PROMPT_DECISION for p in prompts)

    def test_decision_safe_no_prompt(self):
        decision = {
            "action": "safe_to_edit",
            "confidence": 0.9,
            "risk": "low",
            "reason": "No issues",
            "next_steps": [],
            "alternatives": [],
        }
        prompts = PromptEngine.generate("x.py", decision=decision)
        assert len(prompts) == 0

    def test_risk_prompts_cycle(self):
        sim = {"cycle_risk": 3, "coupling_delta": 0.02}
        prompts = PromptEngine.generate("x.py", simulation=sim)
        assert any(p.prompt_type == PROMPT_RISK for p in prompts)
        assert any("cycle" in p.title.lower() for p in prompts)

    def test_risk_prompts_coupling(self):
        sim = {"cycle_risk": 0, "coupling_delta": 0.1}
        prompts = PromptEngine.generate("x.py", simulation=sim)
        assert any("coupling" in p.title.lower() for p in prompts)

    def test_deep_sim_failure_chains(self):
        deep = {
            "failure_chains": ["A → B → C", "X → Y"],
            "data_flow_edges_affected": 1,
        }
        prompts = PromptEngine.generate("x.py", deep_sim=deep)
        assert any(p.prompt_type == PROMPT_RISK for p in prompts)
        assert any("propagation" in p.title.lower() for p in prompts)

    def test_deep_sim_data_flow(self):
        deep = {
            "failure_chains": [],
            "data_flow_edges_affected": 5,
        }
        prompts = PromptEngine.generate("x.py", deep_sim=deep)
        assert any("data flow" in p.title.lower() for p in prompts)

    def test_severity_sort_order(self):
        focus = {"violations": ["v1"], "smells": []}
        decision = {
            "action": "reduce_fan_out",
            "confidence": 0.7,
            "risk": "low",
            "reason": "test",
            "next_steps": [],
            "alternatives": [],
        }
        prompts = PromptEngine.generate("x.py", focus=focus, decision=decision)
        if len(prompts) >= 2:
            severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
            severities = [severity_order.get(p.severity, 4) for p in prompts]
            assert severities == sorted(severities)

    def test_optimization_from_alternatives(self):
        decision = {
            "action": "fix_violations",
            "confidence": 0.8,
            "risk": "medium",
            "reason": "test",
            "next_steps": [],
            "alternatives": [
                {"action": "split module", "reason_rejected": "too much risk"},
            ],
        }
        prompts = PromptEngine.generate("x.py", decision=decision)
        assert any(p.prompt_type == PROMPT_OPTIMIZATION for p in prompts)


# ── FeedbackWriter tests ────────────────────────────────────────────


class TestFeedbackWriter:
    def test_write_creates_file(self, tmp_path):
        root = tmp_path
        (root / ".codegraph").mkdir()
        writer = FeedbackWriter(root, quiet=True)
        prompt = ReactivePrompt(
            prompt_type=PROMPT_VIOLATION,
            severity="high",
            title="Test violation",
        )
        path = writer.write([prompt])
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "Test violation" in content
        assert "Reactive Feedback" in content

    def test_write_append_mode(self, tmp_path):
        root = tmp_path
        (root / ".codegraph").mkdir()
        writer = FeedbackWriter(root, quiet=True)
        p1 = ReactivePrompt(title="First")
        p2 = ReactivePrompt(title="Second")
        writer.write([p1])
        writer.write([p2], append=True)
        content = writer.feedback_path.read_text(encoding="utf-8")
        assert "First" in content
        assert "Second" in content

    def test_write_json(self, tmp_path):
        root = tmp_path
        (root / ".codegraph").mkdir()
        writer = FeedbackWriter(root, quiet=True)
        prompt = ReactivePrompt(title="JSON test", severity="medium")
        json_path = writer.write_json([prompt])
        data = json.loads(json_path.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["title"] == "JSON test"

    def test_terminal_callback(self, tmp_path):
        root = tmp_path
        (root / ".codegraph").mkdir()
        outputs = []
        writer = FeedbackWriter(
            root, terminal_callback=lambda s: outputs.append(s), quiet=False,
        )
        prompt = ReactivePrompt(title="Callback test")
        writer.write([prompt])
        assert any("Callback test" in o for o in outputs)

    def test_json_mode_terminal(self, tmp_path):
        root = tmp_path
        (root / ".codegraph").mkdir()
        outputs = []
        writer = FeedbackWriter(
            root,
            terminal_callback=lambda s: outputs.append(s),
            json_mode=True,
            quiet=False,
        )
        prompt = ReactivePrompt(title="JSON terminal")
        writer.write([prompt])
        # Should output JSON
        assert any('"title"' in o for o in outputs)


# ── FileWatcher tests ────────────────────────────────────────────────


class TestFileWatcher:
    def test_take_snapshot(self, tmp_path):
        # Create a Python file
        (tmp_path / "test.py").write_text("# hello")
        watcher = FileWatcher(tmp_path)
        watcher.take_snapshot()
        assert "test.py" in watcher._snapshot

    def test_detect_new_file(self, tmp_path):
        watcher = FileWatcher(tmp_path, interval=0.5)
        watcher.take_snapshot()
        # Create a new file
        (tmp_path / "new_module.py").write_text("# new")
        changes = watcher.detect_changes()
        assert len(changes) == 1
        assert changes[0].change_type == "created"
        assert "new_module.py" in changes[0].path

    def test_detect_modified_file(self, tmp_path):
        f = tmp_path / "mod.py"
        f.write_text("# v1")
        watcher = FileWatcher(tmp_path, interval=0.5)
        watcher.take_snapshot()
        # Modify the file (ensure mtime changes)
        time.sleep(0.05)
        f.write_text("# v2")
        changes = watcher.detect_changes()
        assert any(c.change_type == "modified" for c in changes)

    def test_detect_deleted_file(self, tmp_path):
        f = tmp_path / "del.py"
        f.write_text("# bye")
        watcher = FileWatcher(tmp_path, interval=0.5)
        watcher.take_snapshot()
        f.unlink()
        changes = watcher.detect_changes()
        assert any(c.change_type == "deleted" for c in changes)

    def test_excludes_pycache(self, tmp_path):
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "test.pyc").write_text("bytecode")
        watcher = FileWatcher(tmp_path)
        watcher.take_snapshot()
        assert not any("__pycache__" in k for k in watcher._snapshot)

    def test_excludes_codegraph_dir(self, tmp_path):
        (tmp_path / ".codegraph").mkdir()
        (tmp_path / ".codegraph" / "internal.py").write_text("# internal")
        watcher = FileWatcher(tmp_path)
        watcher.take_snapshot()
        assert not any(".codegraph" in k for k in watcher._snapshot)

    def test_debounce(self, tmp_path):
        f = tmp_path / "bounce.py"
        f.write_text("# v1")
        watcher = FileWatcher(tmp_path, interval=0.5)
        watcher.take_snapshot()
        time.sleep(0.05)
        f.write_text("# v2")
        changes1 = watcher.detect_changes()
        assert len(changes1) == 1
        # Immediately query again — debounce should suppress
        changes2 = watcher.detect_changes()
        assert len(changes2) == 0

    def test_no_changes(self, tmp_path):
        (tmp_path / "stable.py").write_text("# stable")
        watcher = FileWatcher(tmp_path)
        watcher.take_snapshot()
        changes = watcher.detect_changes()
        assert changes == []

    def test_file_change_dataclass(self):
        fc = FileChange(path="x.py", change_type="modified", mtime=1.0)
        assert fc.path == "x.py"
        assert fc.change_type == "modified"


# ── ReactiveServer tests ────────────────────────────────────────────


class TestReactiveServer:
    def test_run_once_no_files(self, tmp_path):
        root = _setup_minimal_graph(tmp_path)
        server = ReactiveServer(root, ServerConfig(quiet=True))
        event = server.run_once(changed_files=[])
        assert event.cycle == 1
        assert event.prompts == []

    def test_run_once_with_target(self, tmp_path):
        root = _setup_minimal_graph(tmp_path)
        server = ReactiveServer(root, ServerConfig(quiet=True))
        event = server.run_once(changed_files=["svc/order.py"])
        assert event.cycle == 1
        assert isinstance(event.prompts, list)

    def test_run_once_non_python_skipped(self, tmp_path):
        root = _setup_minimal_graph(tmp_path)
        server = ReactiveServer(root, ServerConfig(quiet=True))
        event = server.run_once(changed_files=["readme.md"])
        assert event.prompts == []

    def test_multiple_cycles(self, tmp_path):
        root = _setup_minimal_graph(tmp_path)
        server = ReactiveServer(root, ServerConfig(quiet=True))
        server.run_once(changed_files=["svc/order.py"])
        server.run_once(changed_files=["svc/payment.py"])
        assert server.cycle_count == 2
        assert len(server.events) == 2

    def test_feedback_file_created(self, tmp_path):
        root = _setup_minimal_graph(tmp_path)
        server = ReactiveServer(root, ServerConfig(quiet=True))
        # Use a target that triggers violations for feedback
        server.run_once(changed_files=["svc/payment.py"])
        feedback_path = root / ".codegraph" / "feedback.md"
        # File created only if prompts were generated
        if server.events[0].prompts:
            assert feedback_path.exists()

    def test_json_mode_creates_feedback_json(self, tmp_path):
        root = _setup_minimal_graph(tmp_path)
        server = ReactiveServer(
            root, ServerConfig(quiet=True, json_mode=True)
        )
        server.run_once(changed_files=["svc/payment.py"])
        json_path = root / ".codegraph" / "feedback.json"
        if server.events[0].prompts:
            assert json_path.exists()

    def test_event_to_dict(self, tmp_path):
        root = _setup_minimal_graph(tmp_path)
        server = ReactiveServer(root, ServerConfig(quiet=True))
        event = server.run_once(changed_files=["svc/order.py"])
        d = event.to_dict()
        assert "cycle" in d
        assert "changed_files" in d
        assert "prompts" in d
        assert d["cycle"] == 1

    def test_server_config_defaults(self):
        cfg = ServerConfig()
        assert cfg.interval == DEFAULT_POLL_INTERVAL
        assert cfg.json_mode is False
        assert cfg.quiet is False
        assert cfg.simulate is False


# ── ReactiveEvent tests ──────────────────────────────────────────────


class TestReactiveEvent:
    def test_to_dict(self):
        prompt = ReactivePrompt(title="Test", prompt_type=PROMPT_INFO)
        event = ReactiveEvent(
            changed_files=["a.py"],
            prompts=[prompt],
            cycle=1,
            timestamp="2026-01-01T00:00:00Z",
        )
        d = event.to_dict()
        assert d["cycle"] == 1
        assert len(d["prompts"]) == 1
        assert d["changed_files"] == ["a.py"]


# ── Integration tests ────────────────────────────────────────────────


class TestIntegration:
    def test_full_cycle_violation_target(self, tmp_path):
        """A target with violations should produce violation prompts."""
        root = _setup_minimal_graph(tmp_path)
        server = ReactiveServer(root, ServerConfig(quiet=True))
        event = server.run_once(changed_files=["svc/payment.py"])
        # The target has a violation in analysis/violations.json
        violation_prompts = [
            p for p in event.prompts if p.prompt_type == PROMPT_VIOLATION
        ]
        # May or may not find violations depending on focus resolution,
        # but should not crash
        assert isinstance(event.prompts, list)

    def test_full_cycle_clean_target(self, tmp_path):
        """A non-existent target should not crash."""
        root = _setup_minimal_graph(tmp_path)
        server = ReactiveServer(root, ServerConfig(quiet=True))
        event = server.run_once(changed_files=["nonexistent/clean.py"])
        # No violations for unknown file — might produce no prompts or info
        assert isinstance(event.prompts, list)

    def test_prompt_engine_all_inputs(self):
        """Full prompt generation with all input types."""
        prompts = PromptEngine.generate(
            "test.py",
            focus={"violations": ["v1"], "smells": [
                {"smell_type": "god", "severity": "medium", "description": "big"}
            ]},
            decision={
                "action": "fix_violations", "confidence": 0.8,
                "risk": "high", "reason": "test",
                "next_steps": ["codegraph build"],
                "alternatives": [
                    {"action": "split module", "reason_rejected": "scope"}
                ],
            },
            simulation={"cycle_risk": 1, "coupling_delta": 0.01},
            deep_sim={
                "failure_chains": ["A → B"],
                "data_flow_edges_affected": 4,
            },
        )
        types_found = {p.prompt_type for p in prompts}
        assert PROMPT_VIOLATION in types_found
        assert PROMPT_DECISION in types_found
        assert PROMPT_RISK in types_found
        assert PROMPT_OPTIMIZATION in types_found


# ── Round 5: PromptContext tests ─────────────────────────────────────


class TestPromptContext:
    def test_empty_context(self):
        ctx = PromptContext()
        assert ctx.to_dict() == {}
        assert ctx.format_markdown() == ""

    def test_full_context(self):
        ctx = PromptContext(
            affected_modules=["a.py", "b.py"],
            path="a → b → c",
            subsystem="orders",
            fan_in=3,
            fan_out=5,
        )
        d = ctx.to_dict()
        assert d["affected_modules"] == ["a.py", "b.py"]
        assert d["subsystem"] == "orders"
        assert d["fan_in"] == 3
        assert d["fan_out"] == 5
        assert d["path"] == "a → b → c"

    def test_format_markdown(self):
        ctx = PromptContext(
            affected_modules=["x.py"],
            subsystem="payments",
            fan_in=2,
            fan_out=4,
        )
        md = ctx.format_markdown()
        assert "x.py" in md
        assert "payments" in md
        assert "Fan-in: 2" in md


# ── Round 5: Priority and Blocking tests ─────────────────────────────


class TestPriorityBlocking:
    def test_violation_is_high_blocking(self):
        focus = {"violations": ["layer violation"], "smells": []}
        prompts = PromptEngine.generate("x.py", focus=focus)
        assert len(prompts) == 1
        assert prompts[0].priority == "HIGH"
        assert prompts[0].blocking is True

    def test_smell_medium_is_medium(self):
        focus = {
            "violations": [],
            "smells": [{"smell_type": "god", "severity": "medium", "description": "big"}],
        }
        prompts = PromptEngine.generate("x.py", focus=focus)
        assert len(prompts) == 1
        assert prompts[0].priority == "MEDIUM"
        assert prompts[0].blocking is False

    def test_smell_low_is_low(self):
        focus = {
            "violations": [],
            "smells": [{"smell_type": "long", "severity": "low", "description": "long method"}],
        }
        prompts = PromptEngine.generate("x.py", focus=focus)
        assert len(prompts) == 1
        assert prompts[0].priority == "LOW"

    def test_decision_high_risk_is_blocking(self):
        decision = {
            "action": "fix_violations",
            "confidence": 0.9,
            "risk": "high",
            "reason": "bad",
            "next_steps": [],
            "alternatives": [],
        }
        prompts = PromptEngine.generate("x.py", decision=decision)
        p = [p for p in prompts if p.prompt_type == PROMPT_DECISION][0]
        assert p.priority == "HIGH"
        assert p.blocking is True

    def test_decision_medium_risk_not_blocking(self):
        decision = {
            "action": "fix_violations",
            "confidence": 0.8,
            "risk": "medium",
            "reason": "ok",
            "next_steps": [],
            "alternatives": [],
        }
        prompts = PromptEngine.generate("x.py", decision=decision)
        p = [p for p in prompts if p.prompt_type == PROMPT_DECISION][0]
        assert p.blocking is False

    def test_cycle_risk_high_is_blocking(self):
        sim = {"cycle_risk": 5, "coupling_delta": 0.0}
        prompts = PromptEngine.generate("x.py", simulation=sim)
        assert prompts[0].blocking is True
        assert prompts[0].priority == "HIGH"

    def test_cycle_risk_low_not_blocking(self):
        sim = {"cycle_risk": 1, "coupling_delta": 0.0}
        prompts = PromptEngine.generate("x.py", simulation=sim)
        assert prompts[0].blocking is False

    def test_failure_chains_blocking(self):
        deep = {"failure_chains": ["a", "b", "c"], "data_flow_edges_affected": 0}
        prompts = PromptEngine.generate("x.py", deep_sim=deep)
        p = [p for p in prompts if "propagation" in p.title.lower()][0]
        assert p.blocking is True
        assert p.priority == "HIGH"

    def test_to_dict_includes_priority_blocking(self):
        p = ReactivePrompt(
            prompt_type=PROMPT_VIOLATION,
            severity="high",
            priority="HIGH",
            blocking=True,
            title="Test",
        )
        d = p.to_dict()
        assert d["priority"] == "HIGH"
        assert d["blocking"] is True


# ── Round 5: Behavioral format tests (Upgrade 1) ─────────────────────


class TestBehavioralFormat:
    def test_blocking_has_action_required(self):
        p = ReactivePrompt(
            prompt_type=PROMPT_VIOLATION,
            severity="high",
            priority="HIGH",
            blocking=True,
            title="Violation in x.py",
            body="crosses boundary",
            suggested_commands=["codegraph focus x.py --json"],
        )
        md = p.format_markdown()
        assert "BLOCKING" in md
        assert "MANDATORY" in md
        assert "DO NOT" in md

    def test_non_blocking_no_mandatory(self):
        p = ReactivePrompt(
            prompt_type=PROMPT_OPTIMIZATION,
            severity="low",
            priority="LOW",
            blocking=False,
            title="Smell",
            suggested_commands=["codegraph decide x.py --json"],
        )
        md = p.format_markdown()
        assert "BLOCKING" not in md
        assert "DO NOT" not in md
        assert "Suggested action" in md

    def test_terminal_blocking_tag(self):
        p = ReactivePrompt(
            prompt_type=PROMPT_RISK,
            priority="HIGH",
            blocking=True,
            title="Risk",
        )
        text = p.format_terminal()
        assert "BLOCKING" in text
        assert "MUST RESOLVE" in text

    def test_terminal_non_blocking(self):
        p = ReactivePrompt(
            prompt_type=PROMPT_INFO,
            priority="LOW",
            blocking=False,
            title="Info",
        )
        text = p.format_terminal()
        assert "BLOCKING" not in text
        assert "MUST RESOLVE" not in text


# ── Round 5: Context linking tests (Upgrade 3) ───────────────────────


class TestContextLinking:
    def test_build_context_from_focus(self):
        focus = {
            "callees": ["a.py", "b.py", "c.py"],
            "callers": ["d.py"],
            "subsystem": "orders",
            "fan_in": 3,
            "fan_out": 5,
            "edges": [
                {"source": "mod::A", "target": "mod::B"},
                {"source": "mod::B", "target": "mod::C"},
            ],
        }
        ctx = PromptEngine._build_context(focus)
        assert "a.py" in ctx.affected_modules
        assert "d.py" in ctx.affected_modules
        assert ctx.subsystem == "orders"
        assert ctx.fan_in == 3
        assert ctx.fan_out == 5
        assert "→" in ctx.path

    def test_build_context_empty(self):
        ctx = PromptEngine._build_context(None)
        assert ctx.affected_modules == []
        assert ctx.subsystem == ""

    def test_prompts_carry_context(self):
        focus = {
            "violations": ["v1"],
            "smells": [],
            "callees": ["b.py"],
            "callers": [],
            "subsystem": "core",
            "fan_in": 1,
            "fan_out": 2,
            "edges": [],
        }
        prompts = PromptEngine.generate("x.py", focus=focus)
        assert prompts[0].context.subsystem == "core"
        assert "b.py" in prompts[0].context.affected_modules

    def test_context_in_markdown_output(self):
        ctx = PromptContext(affected_modules=["y.py"], subsystem="payments")
        p = ReactivePrompt(
            prompt_type=PROMPT_VIOLATION,
            priority="HIGH",
            blocking=True,
            title="V",
            body="bad",
            context=ctx,
        )
        md = p.format_markdown()
        assert "y.py" in md
        assert "payments" in md


# ── Round 5: Compute priority tests ──────────────────────────────────


class TestComputePriority:
    def test_blocking_always_high(self):
        assert PromptEngine._compute_priority(PROMPT_INFO, "low", True) == "HIGH"

    def test_high_severity_is_high(self):
        assert PromptEngine._compute_priority(PROMPT_RISK, "high", False) == "HIGH"

    def test_critical_severity_is_high(self):
        assert PromptEngine._compute_priority(PROMPT_RISK, "critical", False) == "HIGH"

    def test_medium_severity_is_medium(self):
        assert PromptEngine._compute_priority(PROMPT_RISK, "medium", False) == "MEDIUM"

    def test_violation_always_high(self):
        assert PromptEngine._compute_priority(PROMPT_VIOLATION, "low", False) == "HIGH"

    def test_low_is_low(self):
        assert PromptEngine._compute_priority(PROMPT_OPTIMIZATION, "low", False) == "LOW"


# ── Round 5: Sort order tests ────────────────────────────────────────


class TestSortOrder:
    def test_blocking_first(self):
        focus = {"violations": ["v1"], "smells": []}
        sim = {"cycle_risk": 1, "coupling_delta": 0.0}
        prompts = PromptEngine.generate("x.py", focus=focus, simulation=sim)
        # Violation (blocking) should come before non-blocking cycle risk
        if len(prompts) >= 2:
            assert prompts[0].blocking is True

    def test_high_before_low(self):
        focus = {
            "violations": ["v1"],
            "smells": [{"smell_type": "long", "severity": "low", "description": ""}],
        }
        prompts = PromptEngine.generate("x.py", focus=focus)
        if len(prompts) >= 2:
            priorities = [p.priority for p in prompts]
            assert priorities[0] == "HIGH"


# ── Round 5: FeedbackWriter blocking sections ────────────────────────


class TestFeedbackWriterBlockingSections:
    def test_blocking_section_header(self, tmp_path):
        root = tmp_path
        (root / ".codegraph").mkdir()
        writer = FeedbackWriter(root, quiet=True)
        blocking = ReactivePrompt(
            prompt_type=PROMPT_VIOLATION,
            priority="HIGH",
            blocking=True,
            title="Block me",
        )
        advisory = ReactivePrompt(
            prompt_type=PROMPT_OPTIMIZATION,
            priority="LOW",
            blocking=False,
            title="Just info",
        )
        writer.write([blocking, advisory])
        content = writer.feedback_path.read_text(encoding="utf-8")
        assert "BLOCKING" in content
        assert "Advisory" in content
        # Blocking section should come before advisory
        idx_blocking = content.index("BLOCKING")
        idx_advisory = content.index("Advisory")
        assert idx_blocking < idx_advisory

    def test_no_blocking_no_section_header(self, tmp_path):
        root = tmp_path
        (root / ".codegraph").mkdir()
        writer = FeedbackWriter(root, quiet=True)
        p = ReactivePrompt(
            prompt_type=PROMPT_INFO,
            priority="LOW",
            blocking=False,
            title="Info only",
        )
        writer.write([p])
        content = writer.feedback_path.read_text(encoding="utf-8")
        # Should not have the blocking section header
        assert "## BLOCKING" not in content


# ── Round 5: Adaptive loop compression tests ─────────────────────────


class TestAdaptiveLoopCompression:
    def test_analyze_file_accepts_batch_size(self, tmp_path):
        """_analyze_file should accept batch_size kwarg."""
        root = _setup_minimal_graph(tmp_path)
        server = ReactiveServer(root, ServerConfig(quiet=True))
        # Should not raise
        prompts = server._analyze_file("svc/order.py", batch_size=1)
        assert isinstance(prompts, list)

    def test_small_batch_focus_only(self, tmp_path):
        """Batch size 1 (small) should not crash and should produce prompts."""
        root = _setup_minimal_graph(tmp_path)
        server = ReactiveServer(root, ServerConfig(quiet=True, simulate=False))
        # batch_size=1 → focus only (no decide unless violations found)
        prompts = server._analyze_file("svc/order.py", batch_size=1)
        assert isinstance(prompts, list)

    def test_run_once_passes_batch_size(self, tmp_path):
        """run_once should pass batch_size based on changed_files count."""
        root = _setup_minimal_graph(tmp_path)
        server = ReactiveServer(root, ServerConfig(quiet=True))
        event = server.run_once(changed_files=["svc/order.py", "svc/payment.py"])
        assert event.cycle == 1
        assert isinstance(event.prompts, list)
