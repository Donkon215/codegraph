"""codegraph.models.alignment — Graph0 / Graph1 alignment checker.

Task B-025.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from codegraph.models.graph0 import Graph0
from codegraph.models.graph1 import Graph1


@dataclass
class AlignmentReport:
    """Result of checking Graph_1 references against Graph_0."""

    stale_entries: List[str] = field(default_factory=list)
    """Graph_1 node IDs with no matching Graph_0 node."""

    missing_intents: List[str] = field(default_factory=list)
    """Graph_0 node IDs with no Graph_1 entry."""

    stale_intents: List[str] = field(default_factory=list)
    """Graph_0 nodes whose body_hash changed since Graph_1 was last updated."""


def check_alignment(
    graph0: Graph0,
    graph1: Graph1,
    previous_hashes: Dict[str, str] | None = None,
) -> AlignmentReport:
    """Validate Graph_1 references against Graph_0.

    Parameters
    ----------
    graph0:
        Current structural graph.
    graph1:
        Current metadata overlay.
    previous_hashes:
        Optional mapping ``{node_id: body_hash}`` from the last Graph_1
        update cycle.  When provided, nodes whose current body_hash
        differs are reported as stale intents.
    """
    report = AlignmentReport()

    g0_ids = frozenset(n.id for n in graph0.nodes)
    g1_ids = frozenset(n.id for n in graph1.nodes)

    # Stale entries: in Graph_1 but not in Graph_0
    report.stale_entries = sorted(g1_ids - g0_ids)

    # Missing intents: in Graph_0 but not in Graph_1
    report.missing_intents = sorted(g0_ids - g1_ids)

    # Stale intents: body_hash changed since last Graph_1 update
    if previous_hashes:
        for node in graph0.nodes:
            if node.id in g1_ids:
                prev = previous_hashes.get(node.id)
                if prev is not None and prev != node.body_hash:
                    report.stale_intents.append(node.id)
        report.stale_intents.sort()

    return report
