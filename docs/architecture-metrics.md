# Architecture metrics — definitions and evidence

Single reference document for every metric computed by the current production
architecture-analysis APIs. It is the written definition side of GitHub issue
#71 ("Deterministic fixtures, local evaluation and documented metric
definitions"). Every definition below states its exact inputs, formula and
normalisation, tie-breaking rule, one worked example with real node ids taken
from `tests/fixtures/architecture`, and whether the metric is advisory or may
block. Each section links to the implementation module that produces it.

## Advisory standing metrics vs. simulator hard guards vs. #70

Three things must not be conflated:

1. **Standing structural metrics (this document)** — computed by
   `codegraph.architecture_metrics`, `codegraph.architecture_overview`, and
   `codegraph.architecture_execution` over the *current* extracted graph. All
   are **advisory**: they are reported only and never gate a build, an apply,
   or a simulation verdict.

2. **Architecture simulator (`codegraph.architecture_simulator`)** — evaluates
   *proposed* changes (before/after graphs) and is the hard structural guard.
   Its `_verdict` returns `REJECT` when `cycle_delta > 0` (a new cycle is a
   hard structural rejection), and its `_BLOCKING_TYPES =
   {"new_cycle", "subsystem_constraint", "forbidden_path",
   "transitive_forbidden"}` findings may block. Score drops, coupling changes,
   layer/constraint heuristic signals are reported alongside the verdict but
   never cause rejection by themselves.

3. **Issue #70 findings** — the simulator's `structural_effect` output (proposed
   change impact) is owned by #70 and documented here in section 10 as advisory
   reported output only. Its consequences never influence the verdict; the
   simulator's `_verdict`/`_BLOCKING_TYPES` (point 2) is the hard structural
   guard. Nothing here adds a new metric or hard policy.

Every metric in this document is therefore **advisory**; none is a hard policy
or may-block metric in the current codebase.

## Determinism

All metric output is deterministic across platforms and runs:

* every output collection (node lists, edge lists, communities, hubs,
  bridges, coupling rows, coverage rows) is sorted;
* floats are rounded (four decimals in `architecture_overview`, six decimals
  in `architecture_metrics`);
* no timestamps are emitted;
* partition ids are derived from a sha1 digest of a sorted seed, never from
  iteration order or hash seeding;
* ties are broken by explicit documented rules (node id ascending, source then
  target), so a behavioural change fails the fixture evaluation instead of
  being noticed later.

Verification: `json.dumps(report.to_dict(), sort_keys=True)` is byte-identical
for two builds of an unchanged repository.

## Metric index

| Metric | Implementation module | Advisory / may block |
|--------|----------------------|----------------------|
| Detected communities | `codegraph.architecture_overview.build_architecture_overview` (via `codegraph.graph_partitioning.build_partitions`) | Advisory |
| Cross-community links & per-link coupling | `codegraph.architecture_overview.build_architecture_overview` | Advisory |
| Aggregate structural metrics | `codegraph.architecture_overview.build_architecture_overview` | Advisory |
| Per-module coupling | `codegraph.architecture_metrics.compute_coupling` | Advisory |
| Cycles (strongly connected components) | `codegraph.architecture_metrics.compute_cycles` | Advisory |
| Hubs (top-band centrality) | `codegraph.architecture_metrics.compute_hubs` | Advisory |
| Bridges (multigraph-aware) | `codegraph.architecture_metrics.compute_bridges` | Advisory |
| Test coverage map & boundary attribution | `codegraph.architecture_execution.map_execution_coverage` | Advisory |
| Simulator structural effect | `codegraph.architecture_simulator.simulate_changes` (field `structural_effect`) | Advisory |
| Community overview artifact | `codegraph.architecture_overview.save_overview` / `emit_build_artifacts`; `codegraph partitions --overview --save` (artifact `.codegraph/architecture/community_overview.json`) | Advisory |

## 1. Detected communities

**Implementation:** `codegraph.architecture_overview.build_architecture_overview`;
communities come from `codegraph.graph_partitioning.build_partitions`.

**Definition.** Graph structure (the `ArchitectureGraph` workflow edges,
treated undirected for partitioning) is clustered into detected communities
using iterative label propagation. `build_partitions` defaults to
`min_size=4` (partitions smaller than the minimum are folded back toward
module locality); the issue #71 fixture harness calls it with `min_size=1`.
Labels initialise to the module part of each node id (text before the first
`::`), then each node adopts the most frequent neighbour label; ties are broken
by label ascending, and iteration stops when a full pass makes no change.
Communities are structural clusters only — they are reported separately from
declared subsystems (`graph.metadata["subsystems"]` and node `subsystem` tags)
and are never merged with them.

**Inputs:** `ArchitectureGraph` nodes and edges; optional `min_size`
(production default 4).

**Formula / normalisation:** none beyond community membership. Each community
reports `size` (node count), `internal_edge_count` (edges with both endpoints
in the community), `boundary_nodes` (nodes incident to a cross-community
edge), `node_type_counts`, `files`, `directories`, `boundary_edges`, and
`declared_subsystem` (set only when every node in the community carries the
same `subsystem` tag, otherwise `null`).

* `files` — the distinct file paths referenced by the community's nodes, taken
  from each node's `file` field and falling back to the module part of the node
  id when `file` is empty. De-duplicated via a set, then sorted ascending.
* `directories` — for each file, `Path(file_path).parent` with backslashes
  normalized to forward slashes (`\\` → `/`); an empty or `"."` result becomes
  `"."`. De-duplicated, then sorted ascending. This makes the directory list
  stable across Windows and POSIX path separators.
* `boundary_edges` — the actual workflow edge records that cross the
  community's boundary (exactly one endpoint in the community), preserved as
  full edge dicts as evidence. Sorted by
  `(source, target, edge_type, source_detail)`. These are the edge records
  themselves, not just a count.

**Tie-break:** partition ids are `module_sha1(seed)[:8]`; node ids within a
community are sorted ascending; `files`, `directories`, `boundary_nodes`, and
`boundary_edges` are all sorted for deterministic output.

**Worked examples.** In `tests/fixtures/architecture/three_community/`, each of
the three communities reports a single `files` entry
(`src/orders/orders.py`, `src/payments/payments.py`, `src/reports/reports.py`)
and matching `directories` (`src/orders`, `src/payments`, `src/reports`); the
cross edge `src/payments/payments.py::PaymentService →
src/orders/orders.py::OrderService` appears as a `boundary_edge` on both the
payments and orders communities. In
`tests/fixtures/architecture/cross_dir_single_community/`, one community spans
two directories (`lib/billing`, `lib/payments`) with `files`
`lib/billing/bill.py` and `lib/payments/pay.py`, but `boundary_edges` is empty
because all five edges are internal to the single community — directory spread
does not imply a community cut.

**Advisory / may block:** Advisory. Community shape, file/directory listings,
and boundary edges are heuristic evidence only, not acceptance criteria.

## 1a. Build artifact: `community_overview.json`

**Implementation:** `codegraph.architecture_overview.save_overview` and
`emit_build_artifacts`; exposed via `codegraph partitions --overview --save`.

**Definition.** The detected community overview is persisted as a stable JSON
artifact at `.codegraph/architecture/community_overview.json`. The build path
(`emit_build_artifacts`) builds partitions once (production default
`min_size=4`), saves them through the partition lifecycle
(`.codegraph/partitions/`), then saves the overview; partitions are computed a
single time and reused for both artifacts. The CLI form
`codegraph partitions --overview --save` builds/loads partitions, builds the
overview, and persists it (the `--save` flag requires `--overview`; with
`--rebuild` the partitions are also rebuilt and saved). The artifact is
written with `sort_keys=True`, no timestamps, and `indent=2`, so it is
byte-identical across builds of an unchanged repository.

**Advisory / may block:** Advisory. The artifact records detected structure;
it gates nothing and is always regeneratable.

## 2. Cross-community links & per-link coupling

**Implementation:** `codegraph.architecture_overview.build_architecture_overview`.

**Definition.** For every workflow edge whose source and target lie in
different detected communities, a directional cross-community link is
recorded. Edges with an endpoint not assigned to a partition are skipped. Each
link stores `edge_count` (number of edges on that directional cut), up to
`_MAX_LINK_EDGES` (8) sample edges as evidence, the sorted source and target
boundary node ids, and a heuristic `coupling_score`.

**Formula / normalisation.**

```
coupling_score = cross_edges_between_pair /
                 (internal_edges_source + internal_edges_target +
                  cross_edges_between_pair)
```

where `internal_edges_source`/`internal_edges_target` are the counts of
internal edges of the two communities and `cross_edges_between_pair` is the
number of edges on that directional cut. The score is cross edges over all
edges touching the two communities; it is a descriptive heuristic, never a
rejection criterion. Link-level edge samples are sorted by
`(source, target, edge_type, source_detail)` and truncated to 8 for stable,
small output.

**Tie-break:** links are emitted sorted by `(source_community,
target_community)`.

**Worked example.** In `tests/fixtures/architecture/coupling/input.json` the two
3-node communities `orders_py_4139b6de` and `payments_py_af3cb169` are joined by
one cross edge `orders.py::OrderService -> payments.py::PaymentService`, giving
`edge_count: 1`, `coupling_score: 0.0769`, and aggregate
`max_coupling_score: 0.0769`.

**Advisory / may block:** Advisory. Coupling scores are heuristic evidence
only, not acceptance criteria.

## 3. Aggregate structural metrics

**Implementation:** `codegraph.architecture_overview.build_architecture_overview`.

**Definition.** Roll-up numbers computed from the detected partition:

| Metric | Meaning |
|--------|---------|
| `community_count` | number of detected communities |
| `node_count` | number of distinct nodes in the graph |
| `edge_count` | number of workflow edges |
| `internal_edges` | edges whose endpoints share a community |
| `cross_edges` | edges crossing community boundaries |
| `internal_edge_ratio` | `internal_edges / (internal_edges + cross_edges)` |
| `mean_community_size` | mean nodes per community |
| `max_coupling_score` | highest per-link coupling score (0.0 if no links) |

**Inputs:** `ArchitectureGraph` plus its detected partition.

**Formula / normalisation:** ratios are `0.0` when the denominator is 0; floats
rounded to 4 decimals.

**Tie-break:** none (scalar aggregates).

**Worked example.** `tests/fixtures/architecture/coupling`: `community_count: 2`,
`node_count: 6`, `edge_count: 13`, `internal_edges: 12`, `cross_edges: 1`,
`internal_edge_ratio: 0.9231`, `mean_community_size: 3.0`,
`max_coupling_score: 0.0769`.

**Advisory / may block:** Advisory; no pass/fail fields.

## 4. Per-module coupling

**Implementation:** `codegraph.architecture_metrics.compute_coupling`
(report field `coupling`).

**Definition.** A module is the part of a node id before the first `::`.
`members(m)` is the set of node ids in module `m`, built from graph nodes and
from every edge endpoint (so endpoints that have no node record still join
their module). `crossing(m)` is the set of *edge records* `(s -> t)` where
exactly one of `s`, `t` is in `members(m)`.

**Formula / normalisation.** No de-duplication: every original edge record is
kept, so parallel and reverse-direction records between the same pair count
separately and nothing is merged or lost.

```
coupling(m) = |crossing(m)| / max(1, |members(m)|)
```

The crossing edge records themselves are stored as `edges` evidence (each
record's `source`/`target` normalised, `edge_type` defaulted to `"call"`),
sorted by `(source, target, edge_type)`. `coupling` is rounded to 6 decimals.
Normalising by module size keeps a small, tightly boundaried module from being
confused with a large, loosely coupled one.

**Tie-break:** modules emitted sorted by module id.

**Worked example.** `tests/fixtures/architecture/hubs`: module `hub.py` has
members `{hub.py::Hub}` plus its four in-boundary callers are in other modules,
so `hub.py::Hub`'s own module `hub.py` reports `node_count: 1`,
`crossing_edges: 4`, `coupling: 4.0`. Module `a.py` reports
`node_count: 1`, `crossing_edges: 1` (`a.py::Alpha -> hub.py::Hub`),
`coupling: 1.0`.

**Advisory / may block:** Advisory. Standing structural picture only; does not
replace simulator sandbox checks.

## 5. Cycles (strongly connected components)

**Implementation:** `codegraph.architecture_metrics.compute_cycles`
(report field `cycles`).

**Definition.** Strongly connected components (SCCs) of the directed graph that
contain more than one node, computed with an iterative Kosaraju pass. Each
component reports its sorted member node ids and the edges between members as
evidence. Self-loops alone do not form a reported cycle.

**Formula / normalisation.** No de-duplication: every original edge record
between members is preserved, so parallel same-type edges that carry distinct
`source_detail`/call sites are all reported as evidence. Component size = member
count; edges restricted to pairs where both endpoints are in the component,
sorted by `json.dumps(edge, sort_keys=True)` for stable reproducible order.

**Tie-break:** components ordered by their smallest member; member ids and
edges sorted for deterministic output.

**Worked example.** `tests/fixtures/architecture/cycles`: edges
`loop.py::A -> loop.py::B`, `loop.py::B -> loop.py::C`, `loop.py::C -> loop.py::A`
form one component `nodes: [loop.py::A, loop.py::B, loop.py::C]`, `size: 3`,
with all three edges as evidence.

**Advisory / may block:** Advisory. Standing structural metric of the current
graph, **not** the simulator's sandboxed hard cycle check on proposed changes
(see § Advisory standing metrics vs. simulator hard guards vs. #70).

## 6. Hubs (top-band centrality)

**Implementation:** `codegraph.architecture_metrics.compute_hubs`
(report field `hubs`; constants `REACH_DEPTH = 3`, `HUB_BAND = 0.10`).

**Definition.** For each node `n`:

```
score(n) = in_degree(n) + out_degree(n) + bounded_reach(n)
```

`in_degree`/`out_degree` count edge records (parallel records each count
toward a node's centrality, matching codegraph's fan-in/fan-out convention).
`bounded_reach(n)` is the number of *distinct* nodes reachable from `n`
following out-edges within `REACH_DEPTH` edges (default 3), excluding `n`
itself; reach uses set-based adjacency so it counts nodes, not records. The
traversal is deliberately bounded so transitive reach stays cheap on large
graphs.

**Formula / normalisation / tie-break.**

* Rank nodes by descending `score`, then ascending node id.
* The top band is the top `HUB_BAND` fraction of nodes
  (`ceil(0.10 * count)`, at least 1); every node tied at the cutoff score is
  included.
* Isolated nodes (score 0) are never hubs.
* Each hub reports `callers` (its direct in-neighbors, sorted) as evidence;
  every listed caller has a direct edge to the hub.
* Hub fields: `score` (6 decimals), `in_degree`, `out_degree`, `reach`,
  `callers`.

**Worked example.** `tests/fixtures/architecture/hubs`: edges
`a.py::Alpha -> hub.py::Hub`, `b.py::Beta -> hub.py::Hub`,
`c.py::Gamma -> hub.py::Hub`, `d.py::Delta -> hub.py::Hub`. Node
`hub.py::Hub`: `in_degree: 4`, `out_degree: 0`, `reach: 0`,
`score: 4.0`, `callers: [a.py::Alpha, b.py::Beta, c.py::Gamma, d.py::Delta]`;
it is the single hub (top band of 5 nodes = 1 node).

**Advisory / may block:** Advisory; never gates a build/apply/simulation.

## 7. Bridges (multigraph-aware)

**Implementation:** `codegraph.architecture_metrics.compute_bridges`
(report field `bridges`).

**Definition.** An edge whose removal increases the number of weakly connected
components, computed on the undirected view of the graph. The check is
multigraph-aware: per undirected pair `{source, target}`, a pair count greater
than one (parallel or reverse-direction records) means removing one record
leaves the other, so that record is **not** a bridge. Only pairs joined by a
single record can be bridges, and Tarjan's low-link condition on the simple
undirected graph confirms there is no alternate path. Self-loops are ignored.

Each bridge reports the edge (the first matching edge record in `graph.edges`
order, preserving its actual orientation and attributes including
`source_detail`) and the two sorted components it joins, found by removing the
pair and BFS-searching both sides with the pair blocked.

**Formula / normalisation.** Candidate pairs from Tarjan (`low[node] >
discovery[parent]`); filtered to pairs with exactly one edge record; components
computed by BFS on the undirected adjacency with the pair blocked; output
sorted by `(source, target)`. Bridge field `edge` preserves the actual original
edge record.

**Tie-break:** bridges normalised as sorted pairs and emitted sorted by
`(source, target)`.

**Worked example.** `tests/fixtures/architecture/bridges`: left clique
`{left.py::L1, left.py::L2, left.py::L3}`, edge `left.py::L2 ->
bridge.py::Bridge`, then `bridge.py::Bridge -> right.py::R1`, right pair
`right.py::R1 <-> right.py::R2`. `left.py::L2 -> bridge.py::Bridge` is a
bridge joining `component_a: [left.py::L1, left.py::L2, left.py::L3]` and
`component_b: [bridge.py::Bridge, right.py::R1, right.py::R2]`.

**Advisory / may block:** Advisory; standing structural picture only.

## 8. Test coverage map & boundary attribution

**Implementation:** `codegraph.architecture_execution.map_execution_coverage`.

**Definition.** Joins workflow-edge execution-flow evidence with test-coverage
evidence over architecture boundaries (detected communities/partitions).
Test-ness comes from the graph's layer-4 assignment
(`codegraph.layers.LAYER_TEST == 4`) and is **never inferred from a
`test_` file name**.

**Inputs:** `ArchitectureGraph`, an index store exposing
`get_nodes_at_layer(4)` (test node ids), and optional pre-computed partitions
(built from the graph with the production default `min_size=4` when omitted;
the issue #71 harness overrides to `min_size=1`).

**Test-coverage evidence.** `test_nodes` = layer-4 node ids from the index,
restricted to ids present in the graph. `evidence` is `"present"` when the
graph contains at least one layer-4 test node, otherwise `"missing"`.

**Test -> boundary attribution.** A test covers every boundary it can *reach*
through the graph (direct call or transitive via helpers), not just its
direct callees. Attribution uses a deterministic BFS
(`_reachable_boundaries`) starting from the test's direct callees with cycle
protection (a `visited` set) so circular call graphs terminate; neighbours are
visited in sorted order. The test's own boundary is **not** counted unless
re-reached through a cycle — coverage is about calling *into* a boundary, not
residing in one. Every boundary is listed explicitly, including zero-coverage
ones.

**Boundary coverage statuses:**

| Status | Meaning |
|--------|---------|
| `covered` | at least one test reaches a node in the boundary |
| `zero_coverage` | tests exist but none reaches this boundary |
| `missing_evidence` | no layer-4 test nodes in the graph at all |

**Flow coverage statuses** (one per boundary-crossing workflow edge, in
traversal order, `flow_id = "source -> target"`, de-duplicated by that string):

| Status | Meaning |
|--------|---------|
| `covered` | both sides have covering tests |
| `one_sided` | exactly one side has covering tests |
| `untested` | neither side has covering tests (tests exist) |
| `missing_evidence` | no layer-4 test nodes in the graph |

**Additional fields:** `orphan_tests` (graph test nodes reaching no boundary,
only when evidence is present), `ambiguous_tests` (tests attributable to more
than one boundary — recorded, not resolved silently), and advisory `totals`
(boundary/flow/test counts). Totals are advisory metrics only, never a gate.

**Tie-break:** boundaries emitted sorted by boundary id; flows in traversal
order (sorted source, then sorted target); test lists sorted; orphan/ambiguous
lists sorted.

**Worked example.** `tests/fixtures/architecture/untested_boundary`: test
`tests.py::test_db` is at layer 4 (`evidence: present`) and reaches
`checked.py::Checker`, so boundary `checked_py_3b1505f9` is `covered` with
`covering_tests: [tests.py::test_db]`; boundary `unt_py_88c87fd4` (containing
the untested `unt.py::Gateway -> unt.py::DB` edge) is `zero_coverage` with no
covering tests.

**Advisory / may block:** Advisory; coverage gaps never block a build, apply,
or simulation verdict.

## 9. Evidence & missing-vs-skipped semantics

Every number in `architecture_metrics` ships with the node ids and edges that
produced it (crossing edge records for coupling, member edges for cycles,
callers for hubs, the actual edge record plus joined components for bridges),
so a reviewer can recompute any number by hand and get the same answer.

In `architecture_execution`, "missing evidence" (no layer-4 test nodes) is
distinguished from "zero coverage" (tests exist but reach no boundary), and
tests attributable to multiple boundaries are recorded as ambiguous rather than
resolved silently. Nothing here treats a missing coverage map as a failure.

## 10. Simulator structural effect (issue #70)

**Implementation:** `codegraph.architecture_simulator.simulate_changes`, result
field `structural_effect` (produced by the private
`_structural_effect` helper).

**Definition.** Given a proposed change (one or more `add_edge` /
`remove_edge` / `rewire_edge` mutations) applied to a sandbox copy of the
graph, `structural_effect` lists the deterministic consequences of the change
on the predicted graph. Consequences describe the change; they **never**
influence the verdict (the verdict is driven by `cycle_delta` and the
blocking policy findings). Each consequence carries the node ids and edge
records that produced it.

The simulator sandbox is scoped to the changed node's partition plus boundary
nodes, built by `codegraph.subsystem_sandbox.build_partition_sandbox`. The
index store is not required: when it is absent the function-level checks are
unavailable, but the structural effect is still computed.

**Consequence kinds:**

| Kind | Meaning |
|------|---------|
| `connection_added` | an edge record added by the change |
| `connection_removed` | an edge record removed by the change |
| `cycle_created` | an added edge whose source is reachable from its target in the predicted graph (a new cycle) |
| `cycle_extended` | the change deepens an existing cycle (cycle delta > 0 with no single edge creating it) |
| `boundary_crossed` | an added edge crosses the sandbox partition boundary |
| `region_newly_connected` | an added edge connects two previously separate weak components inside the partition |
| `hub_touched` | a changed node is a hub (top-band centrality from `compute_hubs`), with before/after hub evidence |
| `affected_nodes` | all nodes transitively reachable from the changed nodes in the predicted graph |

**Inputs:** `simulate_changes(project_root, changes)` reads the on-disk graph
views (`.codegraph/graphs/graph0.json`, `graph1.json`, `workflow.json`) and the
sandbox partition; each change is `{"change": ..., "node": ..., "target": ...}`.

**Formula / normalisation / tie-break.** The edge diff is multigraph-aware:
parallel edge records are distinguished by multiplicity, so adding or removing
one of several parallel records is still reported. Consequences are emitted in
a deterministic order (connection_added/removed sorted by edge key, then
cycle_created, cycle_extended, boundary_crossed, region_newly_connected,
hub_touched per touched node, affected_nodes last). Floats follow the
production rounding.

**Tie-break:** touched nodes processed in sorted order; hub evidence sorted by
caller.

**Worked example.** `tests/fixtures/architecture/structural_effect/input.json`
proposes `add_edge c.py::C -> a.py::A` on edges
`a.py::A -> b.py::B`, `b.py::B -> c.py::C`. The recorded `structural_effect`
contains `connection_added` (`c.py::C -> a.py::A`), `cycle_created` (the new
edge closes the cycle `A -> B -> C -> A`), two `hub_touched` consequences
(`a.py::A` and `c.py::C`), and `affected_nodes: [a.py::A, b.py::B, c.py::C]`.
The verdict is `REJECT` with `cycle_risk: 1`.

**Advisory / may block:** Advisory. The structural effect is reported output
only; consequences never influence the verdict, and the verdict itself is
produced by the issue #70 simulator, not by a metric in this document.

## Links from implementations to this document

The metric implementations above reference this document as their written
definition via their module docstrings:

* `codegraph/architecture_overview.py` — communities, cross-community links,
  aggregate metrics
* `codegraph/architecture_metrics.py` — per-module coupling, cycles, hubs,
  bridges
* `codegraph/architecture_execution.py` — coverage map, boundary/flow statuses
* `codegraph/architecture_simulator.py` — `structural_effect` (issue #70)

A reader can find each metric's definition from the code via these module
docstrings and this document.

## Out of scope for this document

* New scoring scales or new metrics (new metrics belong to #68).
* Blocking policy wiring or simulator hard guards (owned by the simulator /
  policy layers; see § Advisory standing metrics vs. simulator hard guards vs.
  #70).
* CI, publishing, or large-node throughput benchmarks (out of scope for #71).
