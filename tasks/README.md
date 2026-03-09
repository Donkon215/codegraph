# codegraph — Engineering Task System

> Complete breakdown of the codegraph project into atomic, implementable tasks.
> Generated from the engineering specification in `readme.md`.

---

## Summary

| Group | Name | Tasks | Focus |
|-------|------|-------|-------|
| **A** | [Project Setup & Architecture](group_A_project_setup_and_architecture.md) | 36 | Scaffolding, deps, config, infrastructure |
| **B** | [Core Data Models & Schemas](group_B_core_data_models_and_schemas.md) | 40 | All data structures, enums, validation |
| **C** | [AST Extraction Engine](group_C_ast_extraction_engine.md) | 35 | Python parsing, node extraction, body hash |
| **D** | [Layer Detection & Configuration](group_D_layer_detection_and_configuration.md) | 20 | Layer system, auto-detection, config |
| **E** | [Annotation System](group_E_annotation_system.md) | 25 | Intent, metadata overlay, Graph_1 |
| **F** | [Workflow Builder](group_F_workflow_builder.md) | 36 | Edge extraction, tracing, filtering |
| **G** | [Graph Index Layer](group_G_graph_index_layer.md) | 20 | Index tables, SQLite, O(1) lookups |
| **H** | [Suggested Workflow & Policy](group_H_suggested_workflow_policy.md) | 25 | Rules, scopes, policy enforcement |
| **I** | [Analyzer & Task System](group_I_analyzer_and_tasks.md) | 30 | Orphans, policy diff, task generation |
| **J** | [Apply System](group_J_apply_system.md) | 20 | Repair actions, code modification |
| **K** | [Delta Engine](group_K_delta_engine.md) | 20 | Incremental updates, git diff, versioning |
| **L** | [Query System](group_L_query_system.md) | 20 | Query parser, traversal, output |
| **M** | [Architecture Tests & Impact](group_M_architecture_tests_and_impact.md) | 20 | Archi tests, test impact analysis |
| **N** | [CLI Interface](group_N_cli_interface.md) | 33 | All commands, output, flags |
| **O** | [Testing & QA](group_O_testing_and_qa.md) | 32 | Unit/integration/perf tests, CI |
| **P** | [Docs & Packaging](group_P_documentation_packaging_observability.md) | 25 | PyPI, docs, observability, security |
| **Q** | [Content Addressed Graph (CAS)](group_Q_content_addressed_graph.md) | 40 | Dependency hashing, hash propagation, node-level invalidation, Bazel-style CAS |
| **R** | [Semantic Behavior Layer (Graph_2)](group_R_semantic_behavior_layer.md) | 42 | Semantic extraction, actions, guards, side effects, data flow, domain tags, behavioral reasoning |

**Total: 557 tasks** (457 original + 40 Group Q + 42 Group R + 3 B-series + 2 H-series + 2 I-series + 2 L-series + 3 K-series + 2 G-series + 1 M-series + 3 B-CAS integration tasks)

---

## Build Order (Dependency Graph)

```
Phase 1 — Foundation
  A: Project Setup & Architecture

Phase 2 — Core Models
  B: Core Data Models & Schemas (depends on A)

Phase 3 — Extraction & Classification
  C: AST Extraction Engine (depends on B)
  D: Layer Detection & Configuration (depends on B)

Phase 4 — Metadata & Graph Construction
  E: Annotation System (depends on B, C, D)
  F: Workflow Builder (depends on B, C, D)

Phase 5 — Index & Policy
  G: Graph Index Layer (depends on B, F)
  H: Suggested Workflow & Policy (depends on B)

Phase 6 — Analysis & Actions
  I: Analyzer & Task System (depends on E, F, G, H)
  J: Apply System (depends on B, C, I)
  K: Delta Engine (depends on C, F, G)
  Q: Content Addressed Graph (depends on B, C, F, G, K)
  R: Semantic Behavior Layer (depends on B, C, E, F, G, Q)  ← NEW

Phase 7 — Query & Testing
  L: Query System (depends on G, R)
  M: Architecture Tests & Impact (depends on F, G, Q)

Phase 8 — Interface
  N: CLI Interface (depends on all above)

Phase 9 — Quality & Distribution
  O: Testing & QA (depends on all above)
  P: Docs & Packaging (depends on all above)
```

---

## Task ID Convention

- Format: `{GROUP}-{NNN}` (e.g., `A-001`, `F-023`, `O-017`)
- Sequential within each group
- Cross-referenced in dependency fields
- Stable after creation (never renumbered)

---

## Task Structure

Each task contains:
- **Task ID** — unique identifier
- **Title** — concise description
- **Description** — what needs to be implemented
- **Reasoning** — why this is needed (tied to README spec)
- **Implementation Steps** — step-by-step build instructions
- **Files** — which files to create or modify
- **Dependencies** — prerequisite task IDs
- **Edge Cases** — known boundary conditions
- **Validation** — how to verify correctness

---

## How to Use This Task System

1. **Start with Phase 1** (Group A) and work sequentially through phases
2. **Within a phase**, groups can be worked in parallel
3. **Within a group**, tasks are ordered by dependency
4. **Mark tasks complete** as you implement them
5. **Check dependencies** before starting a task — all deps must be complete
6. **Run validation** for each task as you finish it
7. **Cross-reference** the README for full specification details
