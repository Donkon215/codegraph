from __future__ import annotations

import json

from codegraph.architecture_intent import ArchitectureIntent, load_architecture_intent, save_architecture_intent


def test_load_and_save_architecture_intent(tmp_path):
    intent = ArchitectureIntent(
        layers={"API": ["controllers"], "Service": ["services"]},
        rules=[{"from": "API", "to": "Service", "allowed": True}],
        subsystem_rules={"payment": {"internal_only": ["PaymentService"]}},
    )

    path = save_architecture_intent(tmp_path, intent)
    assert path.exists()

    loaded = load_architecture_intent(tmp_path)
    assert loaded.layers["API"] == ["controllers"]
    assert loaded.rules[0]["from"] == "API"
    assert "payment" in loaded.subsystem_rules
