"""codegraph.models.dead_code — Dead-code signal checker.

Task B-038.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class DeadCodeSignals:
    """All four signals required before a node can be flagged as dead code.

    The README mandates that **all four** must be True before removal.
    """

    no_incoming_edges: bool = False
    no_imports: bool = False
    no_config_references: bool = False
    no_test_coverage: bool = False

    def all_confirmed(self) -> bool:
        """Return *True* only when every signal is confirmed."""
        return (
            self.no_incoming_edges
            and self.no_imports
            and self.no_config_references
            and self.no_test_coverage
        )

    def missing_signals(self) -> List[str]:
        """Return the names of signals that are still unconfirmed."""
        missing: List[str] = []
        if not self.no_incoming_edges:
            missing.append("no_incoming_edges")
        if not self.no_imports:
            missing.append("no_imports")
        if not self.no_config_references:
            missing.append("no_config_references")
        if not self.no_test_coverage:
            missing.append("no_test_coverage")
        return missing
