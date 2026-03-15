"""codegraph.architecture_evolution — Evolution layer API surface.

Compatibility module exposing stable evolution entry points while
internally delegating to existing evolution engine implementation.
"""

from codegraph.arch_evolution import (
    EvolutionReport,
    EvolutionResult,
    EvolutionStage,
    get_mutation_tier,
    run_evolution,
    run_evolution_cycle,
    save_evolution_report,
)

__all__ = [
    "EvolutionReport",
    "EvolutionResult",
    "EvolutionStage",
    "get_mutation_tier",
    "run_evolution",
    "run_evolution_cycle",
    "save_evolution_report",
]
