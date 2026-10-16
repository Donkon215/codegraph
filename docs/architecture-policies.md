# Architecture policies

Policies live in `.codegraph/policies/architecture_policies.json`:

```json
{
  "policies": [
    {
      "policy_id": "frontend-backend-boundary",
      "name": "Frontend cannot depend on Python backend modules",
      "policy_type": "frontend_backend_boundary",
      "rule": "JavaScript and TypeScript files must not import Python files",
      "action": "block",
      "enabled": true
    },
    {
      "policy_id": "require-plan-before-apply",
      "name": "Require a plan before apply",
      "policy_type": "no_apply_without_plan",
      "rule": "An architecture plan must exist before applying changes",
      "action": "block",
      "enabled": true
    },
    {
      "policy_id": "dependency-allowlist",
      "name": "Limit cross-subsystem dependencies",
      "policy_type": "allowed_subsystem_deps",
      "rule": "Only frontend to service dependencies are permitted",
      "target": "frontend->service",
      "action": "block",
      "enabled": true
    },
    {
      "policy_id": "no-frontend-service-cycle",
      "name": "Forbid frontend/service cycle",
      "policy_type": "forbidden_subsystem_cycle",
      "rule": "Frontend and service must not depend on each other cyclically",
      "target": "frontend->service->frontend",
      "action": "block",
      "enabled": true
    }
  ]
}
```

The frontend/backend policy evaluates dependency edges supplied alongside the
graph nodes. Each edge may use node IDs (`source` and `target`) or file paths
(`source_file` and `target_file`); `type` or `edge_type` may identify the edge.
An edge is considered a violation when a `.js`, `.jsx`, `.ts`, or `.tsx` source
depends on a `.py` target. Graph_0 itself stores nodes but no dependency edges,
so a caller must pass an enriched graph or the policy has no edges to evaluate.

The no-apply-without-plan policy is operation-scoped. Static `policy --check`
has no apply operation and passes. An apply caller can evaluate it with
`health_data={"operation": "apply", "plan_exists": false}`. The apply pipeline
also enforces the plan gate directly before writing files.

`allowed_subsystem_deps` accepts a semicolon-separated list of `source->target`
pairs in `target`; cross-subsystem dependencies found in the import/workflow
graph must match one of those pairs. `forbidden_subsystem_dep` uses one pair and
flags that dependency. `layer_isolation` uses the same pair syntax for subsystem
names. For a specific forbidden cycle, `forbidden_subsystem_cycle` accepts a
closed path such as `frontend->service->frontend` and checks declared
architecture edges. Simulation commands also check newly introduced cycles in
a proposed graph.

`action` accepts `warn`, `block`, or `suggest`. A blocking violation makes the
policy report fail; warnings and suggestions are reported without blocking.

## Simulation plans

Architecture plans may be simulated with either `codegraph arch-simulate
--plan plan.json` or the positional form `codegraph arch-simulate plan.json`.
The positional `.json` form is reserved for plan files; other positional values
continue to mean a subsystem name.

Plan simulation stays read-only by default. Add `--proof` to route the plan
through `architecture_proof.generate_proof`; this explicitly writes a proof
record under `.codegraph/proofs/`. A `REJECTED` proof forces a `REJECT` verdict,
`PROVEN_WARNING` yields at least `REVIEW`, and any untested status yields
`REVIEW`. Without `--proof`, no proof state is written.
