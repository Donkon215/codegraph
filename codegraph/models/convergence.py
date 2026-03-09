"""codegraph.models.convergence — Repair-loop convergence state tracker.

Task B-031.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple


@dataclass
class ConvergenceState:
    """Track repair-loop stopping conditions.

    Stopping conditions (README):
    1. Orphan count stagnant for *convergence_window* iterations.
    2. Edge count stabilised within *edge_stability_threshold*.
    3. Reached *max_iterations*.
    4. All actions are flag_for_human_review.
    """

    iteration: int = 0
    orphan_history: List[int] = field(default_factory=list)
    edge_count_history: List[int] = field(default_factory=list)
    max_iterations: int = 10
    convergence_window: int = 3
    edge_stability_threshold: float = 0.05

    def record_iteration(
        self,
        orphans: int,
        edges: int,
        all_flagged: bool = False,
    ) -> None:
        """Record metrics for the current iteration."""
        self.iteration += 1
        self.orphan_history.append(orphans)
        self.edge_count_history.append(edges)
        self._all_flagged = all_flagged

    def should_stop(self) -> Tuple[bool, str]:
        """Return ``(stop, reason)``."""
        if self.iteration == 0:
            return False, ""

        # 3. Max iterations
        if self.iteration >= self.max_iterations:
            return True, f"Reached max iterations ({self.max_iterations})"

        # 4. All flagged
        if getattr(self, "_all_flagged", False):
            return True, "All actions are flag_for_human_review"

        # 1. Orphan stagnation
        w = self.convergence_window
        if len(self.orphan_history) >= w:
            recent = self.orphan_history[-w:]
            if len(set(recent)) == 1:
                return True, f"Orphan count stagnant at {recent[0]} for {w} iterations"

        # 2. Edge stability
        if len(self.edge_count_history) >= w:
            recent = self.edge_count_history[-w:]
            if recent[-1] > 0:
                max_e = max(recent)
                min_e = min(recent)
                spread = (max_e - min_e) / recent[-1]
                if spread <= self.edge_stability_threshold:
                    return True, f"Edge count stabilised within {self.edge_stability_threshold * 100:.0f}%"

        return False, ""
