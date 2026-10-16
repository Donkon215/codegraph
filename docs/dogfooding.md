# CodeGraph dogfooding workflow

Use CodeGraph to check a planned architecture change to CodeGraph itself. The workflow has two phases so a person can implement the change only after reviewing the simulation and proof verdict.

```powershell
# Prepare before editing source. The plan is an arch-simulate JSON plan.
.\scripts\dogfood_arch_change.ps1 -Phase prepare -Plan .\change-plan.json

# Optional: ask the simulator to attribute individually rejected edge changes,
# retain their reasons, and emit a revised plan for review.
.\scripts\dogfood_arch_change.ps1 -Phase prepare -Plan .\change-plan.json -ReviseRejected

# Implement the approved change, then verify it.
.\scripts\dogfood_arch_change.ps1 -Phase verify -Plan .\change-plan.json
```

The prepare phase builds the current graph, simulates the plan, runs the proof gate, checks the predicted graph's layer/health/score results, and saves `.codegraph/predicted_graph.json`. The script allows implementation only when the simulation completed its function-level checks, the proof status is `PROVEN_SAFE`, and there is no `REJECT` verdict. A neutral simulator `REVIEW` such as an unchanged score is therefore allowed only when the proof gate independently reports safe. The verify phase runs the test suite, rebuilds all graph views, and compares the rebuilt graph with the saved prediction using `codegraph arch-reconcile`.

For legacy edge-operation plan lists, `--revise-rejected` asks the simulator to isolate individually rejected changes by re-simulating each operation. It reports the original verdict, every removed operation and its rejection reasons, and the remaining `revised_plan`. The dogfooding script saves that plan as `.codegraph/planning/revised_arch_plan.json`; review it before implementation. A rejection caused only by a combination of changes is not guessed at: no operation is removed and the plan remains rejected. Canonical `ArchitectureChange` plans are not automatically revised because their non-edge operations do not yet have complete function-level simulation coverage.

The plan format accepted by `arch-simulate` is either the legacy list of `{ "change": "add_edge|remove_edge|rewire_edge", "node": "...", "target": "..." }` records or a canonical `ArchitectureChange` JSON object. Human-readable intent can be compiled to that model with `codegraph compile "add REST API" --change --output change-plan.json`; `codegraph arch-plan --change --output change-plan.json` emits a canonical plan from the configured architecture. Canonical subsystem/component/constraint operations are preserved in the predicted graph, but the edge sandbox does not score those operations yet, so their simulation returns `REVIEW` and the prepare script blocks implementation until the model covers them.

This is the repeatable self-hosting entry point. Run it around a substantive CodeGraph change and keep its simulation output, test result, and reconciliation report with the change review. The architecture simulation does not edit source code; implementation remains a deliberate human step between phases.

## Verified example

This workflow was exercised on `ArchitectureGraph.save_predicted`: the pre-change plan added a call to `ArchitectureGraph.load_predicted` so the written artifact is checked through its public reader. The simulator completed its function-level checks and the proof gate returned `PROVEN_SAFE`; the overall simulator verdict remained `REVIEW` because the aggregate score was unchanged. The prepare gate allowed the change because there was no rejection, the checks ran, and the independent proof was safe. After implementation, the full suite passed (1,544 passed, 1 skipped), the rebuild completed with 4,777 nodes and 5,847 edges, and `arch-reconcile` reported an exact match with no predicted-only or actual-only nodes, edges, or constraints.
