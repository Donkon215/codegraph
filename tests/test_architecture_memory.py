"""Tests for codegraph.architecture_memory — unified architecture memory.

Includes the losslessness invariant: saving a decision must never
silently discard fields written by another valid producer
(health_delta / metrics_before / metrics_after / related_nodes).
"""

from pathlib import Path

import json

from codegraph.architecture_memory import (
    DecisionRecord,
    ExperimentRecord,
    ArchitectureMemory,
    save_decision,
    load_decisions,
    record_experiment,
    load_experiments,
    load_simulations,
    get_experiment_success_rate,
    load_memory,
    save_memory,
)


def _mem_dir(root: Path) -> Path:
    return root / ".codegraph" / "memory"


class TestDecisionRoundTrip:
    def test_save_and_load_defaults(self, tmp_path: Path) -> None:
        rec = save_decision(tmp_path, "split module X", "high coupling")
        loaded = load_decisions(tmp_path)
        assert len(loaded) == 1
        assert loaded[0].decision == "split module X"
        assert rec.decision_id == "d0001"

    def test_rich_fields_survive_own_roundtrip(self, tmp_path: Path) -> None:
        save_decision(
            tmp_path, "split module X", "high coupling",
            result="success", tags=["module_split"],
            health_delta=0.12,
        )
        d = load_decisions(tmp_path)[0]
        assert d.health_delta == 0.12
        data = json.loads((_mem_dir(tmp_path) / "decisions.json").read_text("utf-8"))
        assert data["decisions"][0]["health_delta"] == 0.12


class TestLosslessRewrite:
    """Regression: architecture_memory used to strip rich fields on rewrite."""

    def test_legacy_rich_record_survives_rewrite(self, tmp_path: Path) -> None:
        legacy = {
            "decision_id": "d0001",
            "decision": "break cycle A->B",
            "reason": "cycle detected",
            "result": "success",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "tags": ["cycle_break"],
            "health_delta": 0.08,
            "metrics_before": {"cycles": 2},
            "metrics_after": {"cycles": 1},
            "related_nodes": ["n1", "n2"],
        }
        _mem_dir(tmp_path).mkdir(parents=True)
        (_mem_dir(tmp_path) / "decisions.json").write_text(
            json.dumps({"decisions": [legacy]}), encoding="utf-8"
        )

        loaded = load_decisions(tmp_path)
        assert loaded[0].health_delta == 0.08
        assert loaded[0].metrics_before == {"cycles": 2}

        save_decision(tmp_path, "new decision", "trigger rewrite")

        reloaded = {d.decision_id: d for d in load_decisions(tmp_path)}
        old = reloaded["d0001"]
        assert old.health_delta == 0.08, "health_delta lost on rewrite"
        assert old.metrics_before == {"cycles": 2}, "metrics_before lost"
        assert old.metrics_after == {"cycles": 1}, "metrics_after lost"
        assert old.related_nodes == ["n1", "n2"], "related_nodes lost"

        raw = json.loads((_mem_dir(tmp_path) / "decisions.json").read_text("utf-8"))
        by_id = {d["decision_id"]: d for d in raw["decisions"]}
        assert by_id["d0001"]["health_delta"] == 0.08
        assert by_id["d0001"]["metrics_after"] == {"cycles": 1}


class TestFilters:
    def test_filter_by_result(self, tmp_path: Path) -> None:
        save_decision(tmp_path, "a", "", result="success", tags=["t1"])
        save_decision(tmp_path, "b", "", result="failed", tags=["t2"])
        assert [d.decision for d in load_decisions(tmp_path, result_filter="success")] == ["a"]
        assert [d.decision for d in load_decisions(tmp_path, tags=["t2"])] == ["b"]

    def test_empty_root_returns_empty(self, tmp_path: Path) -> None:
        assert load_decisions(tmp_path) == []
        assert get_experiment_success_rate(tmp_path) == 0.0


class TestExperiments:
    def test_record_and_load(self, tmp_path: Path) -> None:
        rec = record_experiment(
            tmp_path, branch_name="feat/split-x", description="split X",
            outcome="merged", lesson="splits help", health_before=0.5,
            health_after=0.65, cycles_before=1, cycles_after=0,
        )
        assert rec.experiment_id == "e0001"
        loaded = load_experiments(tmp_path)
        assert len(loaded) == 1
        assert loaded[0]["outcome"] == "merged"
        assert get_experiment_success_rate(tmp_path) == 1.0

    def test_ids_increment(self, tmp_path: Path) -> None:
        a = record_experiment(tmp_path, "b1", "d", "merged")
        b = record_experiment(tmp_path, "b2", "d", "rejected")
        assert (a.experiment_id, b.experiment_id) == ("e0001", "e0002")


class TestSimulations:
    def test_simulation_round_trip(self, tmp_path: Path) -> None:
        from codegraph.architecture_memory import record_simulation

        record_simulation(tmp_path, "subsystem-a", "accept", True,
                          reasons=["no new cycles"], predictions=[{"x": 1}])
        loaded = load_simulations(tmp_path)
        assert len(loaded) == 1
        assert loaded[0]["recommendation"] == "accept"
        assert loaded[0]["predictions"] == [{"x": 1}]


class TestAggregate:
    def test_load_memory_aggregates(self, tmp_path: Path) -> None:
        save_decision(tmp_path, "d1", "", result="success", health_delta=0.2)
        record_experiment(tmp_path, "b1", "desc", "merged")
        mem = load_memory(tmp_path)
        assert isinstance(mem, ArchitectureMemory)
        assert len(mem.decisions) == 1
        assert len(mem.experiments) == 1
        text = mem.format()
        assert "Decisions: 1" in text and "Success rate: 1/1" in text

    def test_save_memory_lossless(self, tmp_path: Path) -> None:
        mem = ArchitectureMemory(
            decisions=[DecisionRecord("d1", "x", "y", "success",
                                      health_delta=0.3,
                                      metrics_before={"a": 1})],
            experiments=[ExperimentRecord("e1", "b", "desc", "merged")],
        )
        save_memory(tmp_path, mem)
        reloaded = load_memory(tmp_path)
        assert reloaded.decisions[0].health_delta == 0.3
        assert reloaded.decisions[0].metrics_before == {"a": 1}
        assert reloaded.experiments[0].outcome == "merged"


class TestIntelligenceCompat:
    """The intelligence layer must work against the merged records."""

    def test_score_strategies_uses_health_delta(self, tmp_path: Path) -> None:
        from codegraph.arch_memory_intelligence import (
            analyze_memory, score_strategies,
        )

        save_decision(tmp_path, "split X", "", result="success",
                      tags=["module_split"], health_delta=0.1)
        memory = load_memory(tmp_path)
        scores = score_strategies(memory)
        assert len(scores) == 1
        assert scores[0].strategy == "module_split"
        assert scores[0].avg_score_improvement == 0.1

        report = analyze_memory(tmp_path)
        assert report.recommendations is not None
