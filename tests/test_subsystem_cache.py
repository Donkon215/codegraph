from __future__ import annotations

import json
import time

from codegraph.subsystem_cache import SubsystemCache
from codegraph.subsystem_graph import SubsystemGraph


def _subsystem() -> SubsystemGraph:
    return SubsystemGraph(
        nodes=[
            {"id": "payment.py::PaymentService", "file": "payment.py", "type": "class"},
            {"id": "payment.py::PaymentRepo", "file": "payment.py", "type": "class"},
        ],
        edges=[
            {"source": "payment.py::PaymentService", "target": "payment.py::PaymentRepo", "edge_type": "call"},
        ],
        boundary_nodes=["payment.py::PaymentService"],
        metadata={"depth": 2},
    )


def test_subsystem_cache_hit_and_load(tmp_path):
    cache = SubsystemCache(tmp_path)
    cache.put("payment.py::PaymentService", _subsystem())

    entry = cache.get("payment.py::PaymentService")
    assert entry is not None
    assert entry.root_node == "payment.py::PaymentService"

    loaded = cache.entry_to_subsystem(entry)
    assert len(loaded.nodes) == 2
    assert len(loaded.edges) == 1


def test_subsystem_cache_invalidates_when_history_newer(tmp_path):
    cache = SubsystemCache(tmp_path)
    entry = cache.put("payment.py::PaymentService", _subsystem())

    hist = tmp_path / ".codegraph" / "architecture" / "architecture_history.json"
    hist.parent.mkdir(parents=True, exist_ok=True)
    hist.write_text(
        json.dumps({"entries": [{"timestamp": time.time() + 30}]}, indent=2),
        encoding="utf-8",
    )

    assert cache.is_valid(entry) is False


def test_subsystem_cache_invalidate_for_nodes(tmp_path):
    cache = SubsystemCache(tmp_path)
    cache.put("payment.py::PaymentService", _subsystem())

    removed = cache.invalidate_for_nodes({"payment.py::PaymentRepo"})
    assert removed == 1
