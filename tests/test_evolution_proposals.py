"""Tests for codegraph.evolution_proposals."""

import json
import pytest
from pathlib import Path

from codegraph.evolution_proposals import (
    EvolutionProposal,
    ProposalStore,
    create_proposal_from_evolution,
    load_proposals,
    save_proposals,
    STATUS_ACCEPTED,
    STATUS_PENDING,
    STATUS_REJECTED,
)


class TestEvolutionProposal:
    def test_to_dict(self):
        p = EvolutionProposal(
            proposal_id="p1",
            strategy="module_split",
            target_modules=["a.py"],
            predicted_score_delta=0.05,
            safety_tier="safe",
            reason="god module detected",
        )
        d = p.to_dict()
        assert d["proposal_id"] == "p1"
        assert d["strategy"] == "module_split"
        assert d["status"] == STATUS_PENDING

    def test_from_dict(self):
        d = {
            "proposal_id": "p2",
            "strategy": "cycle_break",
            "target_modules": ["b.py"],
            "predicted_score_delta": -0.01,
            "safety_tier": "medium",
            "status": STATUS_ACCEPTED,
            "reason": "auto",
        }
        p = EvolutionProposal.from_dict(d)
        assert p.proposal_id == "p2"
        assert p.status == STATUS_ACCEPTED
        assert p.reason == "auto"


class TestProposalStore:
    def test_add_and_pending(self):
        store = ProposalStore()
        p = EvolutionProposal("p1", "split", ["a.py"], 0.03, "safe", "test")
        store.add(p)
        pending = store.pending()
        assert len(pending) == 1
        assert pending[0].proposal_id == "p1"

    def test_accept(self):
        store = ProposalStore()
        p = EvolutionProposal("p1", "split", ["a.py"], 0.03, "safe", "test")
        store.add(p)
        store.accept("p1")
        assert store.proposals[0].status == STATUS_ACCEPTED
        assert len(store.pending()) == 0

    def test_reject(self):
        store = ProposalStore()
        p = EvolutionProposal("p1", "split", ["a.py"], 0.03, "safe", "test")
        store.add(p)
        store.reject("p1", "too risky")
        assert store.proposals[0].status == STATUS_REJECTED

    def test_accept_unknown_id(self):
        store = ProposalStore()
        # Should not raise, just pass silently
        store.accept("nonexistent")

    def test_save_and_load(self, tmp_path):
        store = ProposalStore()
        store.add(EvolutionProposal("p1", "split", ["a.py"], 0.03, "safe", "r1"))
        store.add(EvolutionProposal("p2", "break", ["b.py"], -0.01, "medium", "r2"))

        save_proposals(tmp_path, store)

        loaded = load_proposals(tmp_path)
        assert len(loaded.proposals) == 2
        assert loaded.proposals[0].proposal_id == "p1"
        assert loaded.proposals[1].strategy == "break"

    def test_load_missing_file(self, tmp_path):
        store = load_proposals(tmp_path)
        assert len(store.proposals) == 0


class TestCreateProposalFromEvolution:
    def test_creates_from_result(self):
        result_dict = {
            "selected_strategy": "fan_out_reduction",
            "selected_target": "cli.py",
            "score_delta": 0.04,
            "safety_tier": "safe",
        }
        p = create_proposal_from_evolution(result_dict, cycle=1)
        assert p is not None
        assert p.strategy == "fan_out_reduction"
        assert p.target_modules == ["cli.py"]
        assert p.predicted_score_delta == 0.04
        assert p.safety_tier == "safe"
        assert p.status == STATUS_PENDING
        assert p.proposal_id

    def test_returns_none_without_strategy(self):
        p = create_proposal_from_evolution({}, cycle=1)
        assert p is None
