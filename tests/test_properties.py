"""Property-based tests for core models.

Task O-029: Validate model properties with generated data.
"""

from __future__ import annotations

import json
import random
import string

import pytest

from codegraph.models.graph0 import Graph0, Graph0Node
from codegraph.models.graph1 import Graph1, Graph1Node
from codegraph.models.workflow import Workflow, WorkflowEdge, deduplicate_edges
from codegraph.utils.ids import generate_node_id


def _random_string(rng: random.Random, min_len: int = 1, max_len: int = 20) -> str:
    length = rng.randint(min_len, max_len)
    return "".join(rng.choice(string.ascii_lowercase) for _ in range(length))


def _random_node(rng: random.Random) -> Graph0Node:
    file = _random_string(rng) + ".py"
    func = _random_string(rng)
    nid = f"{file}::{func}"
    return Graph0Node(
        id=nid,
        body_hash=_random_string(rng, 5, 10),
        file=file,
        type=rng.choice(["function", "method", "class", "module"]),
        line=rng.randint(1, 1000),
    )


class TestGraph0Properties:
    """Property tests for Graph0."""

    def test_json_roundtrip(self) -> None:
        rng = random.Random(42)
        for _ in range(20):
            g = Graph0()
            n_nodes = rng.randint(0, 10)
            for _ in range(n_nodes):
                try:
                    g.add_node(_random_node(rng))
                except ValueError:
                    pass  # duplicate ID
            text = g.to_json()
            restored = Graph0.from_json(text)
            assert len(restored.nodes) == len(g.nodes)

    def test_add_remove_identity(self) -> None:
        rng = random.Random(123)
        g = Graph0()
        node = _random_node(rng)
        g.add_node(node)
        assert g.has_node(node.id)
        g.remove_node(node.id)
        assert not g.has_node(node.id)

    def test_no_duplicates(self) -> None:
        rng = random.Random(456)
        g = Graph0()
        node = _random_node(rng)
        g.add_node(node)
        with pytest.raises(ValueError):
            g.add_node(node)


class TestWorkflowProperties:
    """Property tests for Workflow."""

    def test_edge_dedup_subset(self) -> None:
        """Deduplication result is a subset of input."""
        rng = random.Random(789)
        edges = []
        for _ in range(20):
            src = _random_string(rng)
            tgt = _random_string(rng)
            edges.append(WorkflowEdge(source=src, target=tgt))
        result = deduplicate_edges(edges)
        assert len(result) <= len(edges)
        result_keys = {e._key() for e in result}
        for e in edges:
            assert e._key() in result_keys

    def test_json_roundtrip(self) -> None:
        rng = random.Random(101)
        wf = Workflow()
        for _ in range(10):
            wf.add_edge(WorkflowEdge(
                source=_random_string(rng),
                target=_random_string(rng),
                edge_type=rng.choice(["call", "test", "trace"]),
                confidence=rng.choice(["static", "runtime", "ai_inferred"]),
            ))
        text = wf.to_json()
        restored = Workflow.from_json(text)
        assert len(restored.edges) == len(wf.edges)


class TestNodeIdProperties:
    """Property tests for node ID generation."""

    def test_roundtrip_components(self) -> None:
        rng = random.Random(202)
        for _ in range(50):
            file = _random_string(rng) + ".py"
            cls = _random_string(rng) if rng.random() > 0.5 else None
            func = _random_string(rng) if rng.random() > 0.3 else None
            nid = generate_node_id(file, class_name=cls, func_name=func)
            assert isinstance(nid, str)
            assert len(nid) > 0
            # File part always present
            assert file in nid or file.rsplit(".", 1)[0] in nid
