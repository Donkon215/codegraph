---
name: codegraph-pipeline
description: "Master workflow skill for running the full codegraph architecture pipeline: preflight → stabilize → enforce → evolve → simulate → prove → implement → validate. Use this skill whenever running any multi-phase codegraph workflow. Prevents skipping mandatory gates."
origin: codegraph
---

# Codegraph Pipeline Skill

This skill governs every multi-phase codegraph operation. It is the canonical
workflow reference — consult it before running any non-trivial architecture task.

## When to Use

- Starting a new architecture improvement cycle
- Running enforce + evolve stages
- Before and after any structural code change
- When deciding which codegraph command to run next
- When the pipeline state is unclear

## Pipeline State Machine

Transitions are guarded. Each gate must pass before proceeding.

```
START
  │
  ▼
PREFLIGHT ──── fail ──→ ABORT (fix git state / branch)
  │
  ▼
STABILIZE ──── P1-P4 remaining ──→ REPAIR LOOP (max 3 cycles)
  │
  ▼
ENFORCE ──────  violations ──→ REPAIR
  │
  ▼
EVOLVE ────────  no improvement ──→ ARCHITECTURE_STABLE (exit)
  │
  ▼
SIMULATE ──────  rejected ──→ TRY NEXT CANDIDATE
  │
  ▼
PROVE ──────────  REJECTED ──→ REVISE PLAN
  │
  ▼
IMPLEMENT ──────  test fail ──→ REPAIR (max 2 retries)
  │
  ▼
VALIDATE
  │
  ▼
SCORE_COMPARE ── regression ──→ DISCARD BRANCH
  │
  ▼
MERGE_DECISION
```

## Phase Command Reference

### PREFLIGHT

```bash
git status --short
git branch
codegraph --version
ls .codegraph/lock 2>/dev/null || echo "no lock"
```

Pass conditions:
- Clean working tree OR only `.pyc` modifications
- On a feature branch (not `main`)
- No lock collision

### STABILIZE

```bash
codegraph build
codegraph analyze --json
codegraph tasks
```

Continue to ENFORCE when: 0 P1–P4 violations.

### ENFORCE

```bash
codegraph analyze --json
codegraph suggest validate
codegraph suggest list
```

Goal: all governance rules respected.

### EVOLVE

```bash
codegraph architect --save
codegraph arch-search --save --json
```

Goal: identify improvement candidates.

### SIMULATE

```bash
codegraph arch-simulate <subsystem> --save --json
```

Goal: validate candidate safely before proof.

### PROVE

```bash
codegraph arch-delta --save
codegraph prove --json
```

Accept: `PROVEN_SAFE` or `PROVEN_WARNING`
Reject: `REJECTED` — do not proceed

### IMPLEMENT

Via `codegraph-implementer` agent.

### VALIDATE

```bash
python -m pytest tests/ -x --tb=short -q
codegraph build
codegraph analyze --json
codegraph score --compare --json
codegraph lock
codegraph drift --json
```

### SCORE_COMPARE

Pass: `score >= baseline - 0.05`
Fail: discard branch, report regression

## Fast Safety Pass Template

For quick verification without evolution:

```bash
codegraph build
codegraph analyze
codegraph tasks
codegraph repair --max-cycles 3
codegraph build
codegraph analyze
```

## Evolution Pass Template

```bash
codegraph architect --save
codegraph arch-search --save
codegraph arch-delta --save
codegraph prove
```

## Full Validation Template

```bash
python -m pytest tests/ -x --tb=short -q
codegraph build
codegraph analyze
codegraph score --compare
codegraph lock
codegraph drift
```

## Mutation Budget (Default Limits)

```
max_files_modified  = 12
max_edges_added     = 25
max_edges_removed   = 25
max_nodes_added     = 15
max_nodes_removed   = 10
```

If a plan exceeds any limit → split into smaller scoped branches.

## Abort Conditions

Stop pipeline immediately if:
- All simulation candidates rejected
- Repair loop exceeds max 3 cycles
- Score drops below `baseline - 0.05`
- Drift unresolved after enforcement
- Proof status is `REJECTED` with no alternative candidates
