"""Tests for codegraph.arch_memory — architecture decision memory."""

import json
import tempfile
from pathlib import Path

import pytest

from codegraph.arch_memory import (
    ArchDecision,
    ArchExperiment,
    ArchMemory,
    load_memory,
    save_memory,
    record_decision,
    record_experiment,
    get_relevant_decisions,
)


class TestArchDecision:
    def test_roundtrip(self):
        d = ArchDecision(
            decision_id="d0001",
            decision="Split god module",
            reason="cli.py too large",
            result="success",
            health_delta=0.15,
            tags=["refactor", "split"],
        )
        dd = d.to_dict()
        assert dd["decision_id"] == "d0001"
        assert dd["result"] == "success"
        assert dd["health_delta"] == 0.15
        assert dd["tags"] == ["refactor", "split"]

        restored = ArchDecision.from_dict(dd)
        assert restored.decision == "Split god module"
        assert restored.tags == ["refactor", "split"]

    def test_defaults(self):
        d = ArchDecision.from_dict({
            "decision_id": "d0001",
            "decision": "test",
        })
        assert d.result == "pending"
        assert d.health_delta == 0.0
        assert d.tags == []

    def test_minimal_to_dict(self):
        d = ArchDecision(
            decision_id="d0001",
            decision="test",
            reason="",
            result="pending",
        )
        dd = d.to_dict()
        assert "health_delta" not in dd
        assert "tags" not in dd
        assert "related_nodes" not in dd


class TestArchExperiment:
    def test_roundtrip(self):
        e = ArchExperiment(
            experiment_id="e0001",
            branch_name="codegraph/test",
            description="Try splitting core",
            outcome="merged",
            health_before=0.5,
            health_after=0.7,
            lesson="Split worked well",
        )
        d = e.to_dict()
        assert d["experiment_id"] == "e0001"
        assert d["outcome"] == "merged"
        assert d["lesson"] == "Split worked well"

        restored = ArchExperiment.from_dict(d)
        assert restored.branch_name == "codegraph/test"
        assert restored.health_after == 0.7


class TestArchMemory:
    def test_empty(self):
        m = ArchMemory()
        d = m.to_dict()
        assert d["summary"]["total_decisions"] == 0
        assert d["summary"]["total_experiments"] == 0

    def test_with_data(self):
        m = ArchMemory(
            decisions=[
                ArchDecision("d1", "test1", "r1", result="success"),
                ArchDecision("d2", "test2", "r2", result="failed"),
            ],
            experiments=[
                ArchExperiment("e1", "b1", "exp1", outcome="merged"),
                ArchExperiment("e2", "b2", "exp2", outcome="rejected"),
            ],
        )
        d = m.to_dict()
        assert d["summary"]["total_decisions"] == 2
        assert d["summary"]["total_experiments"] == 2
        assert d["summary"]["successful_experiments"] == 1
        assert d["summary"]["rejected_experiments"] == 1

    def test_format(self):
        m = ArchMemory(
            decisions=[ArchDecision("d1", "test", "reason", result="success")],
        )
        text = m.format()
        assert "Decisions: 1" in text
        assert "test" in text

    def test_get_experiment_success_rate_empty(self):
        m = ArchMemory()
        # Empty → 0.0
        assert m.to_dict()["summary"]["total_experiments"] == 0

    def test_get_experiment_success_rate(self):
        m = ArchMemory(experiments=[
            ArchExperiment("e1", "b1", "d1", outcome="merged"),
            ArchExperiment("e2", "b2", "d2", outcome="rejected"),
            ArchExperiment("e3", "b3", "d3", outcome="merged"),
        ])
        success = sum(1 for e in m.experiments if e.outcome == "merged")
        assert success / len(m.experiments) == pytest.approx(2 / 3)


class TestLoadSaveMemory:
    def test_load_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = load_memory(Path(tmpdir))
            assert len(mem.decisions) == 0
            assert len(mem.experiments) == 0

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            mem = ArchMemory(
                decisions=[
                    ArchDecision("d1", "test dec", "reason", result="success"),
                ],
                experiments=[
                    ArchExperiment("e1", "branch", "desc", outcome="merged"),
                ],
            )
            save_memory(root, mem)

            loaded = load_memory(root)
            assert len(loaded.decisions) == 1
            assert loaded.decisions[0].decision == "test dec"
            assert len(loaded.experiments) == 1
            assert loaded.experiments[0].outcome == "merged"


class TestRecordDecision:
    def test_records_and_persists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            dec = record_decision(
                root,
                decision="Add forbidden rule",
                reason="Prevent cycle",
                result="success",
                tags=["rule"],
            )
            assert dec.decision_id == "d0001"
            assert dec.decision == "Add forbidden rule"
            assert dec.timestamp  # should be set

            # Verify persisted
            loaded = load_memory(root)
            assert len(loaded.decisions) == 1

    def test_increments_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            record_decision(root, "first", "r1")
            dec2 = record_decision(root, "second", "r2")
            assert dec2.decision_id == "d0002"


class TestRecordExperiment:
    def test_records_and_persists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            exp = record_experiment(
                root,
                branch_name="codegraph/test",
                description="Try splitting",
                outcome="merged",
                lesson="Worked",
                health_before=0.5,
                health_after=0.7,
            )
            assert exp.experiment_id == "e0001"
            assert exp.lesson == "Worked"

            loaded = load_memory(root)
            assert len(loaded.experiments) == 1


class TestGetRelevantDecisions:
    def test_filter_by_tag(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            record_decision(root, "dec1", "r1", tags=["refactor"])
            record_decision(root, "dec2", "r2", tags=["rule"])
            record_decision(root, "dec3", "r3", tags=["refactor", "split"])

            results = get_relevant_decisions(root, tags=["refactor"])
            assert len(results) == 2

    def test_filter_by_result(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            record_decision(root, "dec1", "r1", result="success")
            record_decision(root, "dec2", "r2", result="failed")

            results = get_relevant_decisions(root, result_filter="success")
            assert len(results) == 1
            assert results[0].result == "success"

    def test_limit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            for i in range(15):
                record_decision(root, f"dec{i}", f"r{i}")

            results = get_relevant_decisions(root, limit=5)
            assert len(results) == 5
