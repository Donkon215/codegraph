from __future__ import annotations

from codegraph.copilot_context_builder import validate_copilot_architecture_edit


def test_guardrails_blocks_invalid_architecture_edit(monkeypatch, tmp_path):
    class _Graph:
        nodes = [{"id": "controllers/user.py::UserController", "file": "controllers/user.py"}]
        edges = []
        metadata = {}

    class _Intent:
        layers = {"API": ["controllers"], "Repository": ["repositories"]}
        rules = [{"from": "API", "to": "Repository", "allowed": False}]
        subsystem_rules = {}

    class _Report:
        violations = [
            {
                "from_node": "controllers/user.py::UserController",
                "to_node": "repositories/user.py::UserRepository",
                "message": "API cannot depend on Repository",
            }
        ]

    import codegraph.copilot_context_builder as ccb

    monkeypatch.setattr("codegraph.architecture_graph.ArchitectureGraph.load", lambda root: _Graph())
    monkeypatch.setattr("codegraph.architecture_intent.load_architecture_intent", lambda root: _Intent())
    monkeypatch.setattr("codegraph.intent_validator.validate_architecture_intent", lambda graph, intent: _Report())
    monkeypatch.setattr("codegraph.subsystem_extractor.extract_subsystem", lambda *args, **kwargs: None)

    result = validate_copilot_architecture_edit(tmp_path, affected_node="controllers/user.py::UserController")
    assert result["allowed"] is False
    assert result["error"] == "architecture_violation"
