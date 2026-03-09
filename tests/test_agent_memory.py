"""Tests for codegraph.agent_memory — persistent agent memory."""

import pytest

from codegraph.agent_memory import (
    AgentMemory,
    AgentStats,
    Convention,
    RepairPattern,
    load_memory,
    save_memory,
)


class TestRepairPattern:
    def test_to_dict(self):
        p = RepairPattern(pattern_id="p1", task_type="orphan", action_taken="flag")
        d = p.to_dict()
        assert d["pattern_id"] == "p1"
        assert d["task_type"] == "orphan"


class TestConvention:
    def test_to_dict(self):
        c = Convention(name="naming", description="snake_case", confidence=0.8)
        d = c.to_dict()
        assert d["name"] == "naming"
        assert d["confidence"] == 0.8


class TestAgentStats:
    def test_to_dict(self):
        s = AgentStats(total_cycles=5, total_intents_applied=100)
        d = s.to_dict()
        assert d["total_cycles"] == 5
        assert d["total_intents_applied"] == 100


class TestAgentMemory:
    def test_add_pattern(self):
        m = AgentMemory()
        m.add_pattern("orphan", "flag_for_human_review", "tests/*")
        assert len(m.patterns) == 1
        assert m.patterns[0].success_count == 1

    def test_add_duplicate_pattern_increments(self):
        m = AgentMemory()
        m.add_pattern("orphan", "flag", "tests/*")
        m.add_pattern("orphan", "flag", "tests/*")
        assert len(m.patterns) == 1
        assert m.patterns[0].success_count == 2

    def test_add_convention(self):
        m = AgentMemory()
        m.add_convention("snake_case", "Use snake_case for functions")
        assert len(m.conventions) == 1
        assert m.conventions[0].confidence == 0.5

    def test_add_duplicate_convention_boosts_confidence(self):
        m = AgentMemory()
        m.add_convention("snake_case", "Use snake_case")
        m.add_convention("snake_case", "Use snake_case")
        assert len(m.conventions) == 1
        assert m.conventions[0].confidence == 0.6

    def test_add_note(self):
        m = AgentMemory()
        m.add_note("Fixed a tricky cycle")
        assert len(m.notes) == 1
        assert "Fixed a tricky cycle" in m.notes[0]

    def test_record_cycle(self):
        m = AgentMemory()
        m.record_cycle(intents=10, repairs=2, flags=5)
        assert m.stats.total_cycles == 1
        assert m.stats.total_intents_applied == 10
        assert m.stats.total_repairs_applied == 2
        assert m.stats.total_flags == 5

    def test_format(self):
        m = AgentMemory()
        m.add_pattern("orphan", "flag", "x")
        text = m.format()
        assert "Agent Memory" in text
        assert "Patterns: 1" in text

    def test_to_json(self):
        m = AgentMemory()
        j = m.to_json()
        assert '"version": 1' in j


class TestSaveLoadMemory:
    def test_round_trip(self, tmp_path):
        cg_dir = tmp_path / ".codegraph"
        cg_dir.mkdir()

        m = AgentMemory()
        m.add_pattern("intent_missing", "add_intent", "*")
        m.add_convention("docstrings", "Always add docstrings")
        m.add_note("Test note")
        m.record_cycle(intents=5, repairs=1, flags=2)

        save_memory(m, tmp_path)
        loaded = load_memory(tmp_path)

        assert len(loaded.patterns) == 1
        assert loaded.patterns[0].task_type == "intent_missing"
        assert len(loaded.conventions) == 1
        assert loaded.conventions[0].name == "docstrings"
        assert len(loaded.notes) == 1
        assert loaded.stats.total_cycles == 1

    def test_load_nonexistent(self, tmp_path):
        m = load_memory(tmp_path)
        assert m.version == 1
        assert len(m.patterns) == 0
