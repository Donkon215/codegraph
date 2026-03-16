---
name: codegraph-repair-loop
description: "Guided repair skill for fixing codegraph violations, broken graph state, orphan nodes, stale intents, and policy failures. Use after codegraph build/analyze reports issues, or when the stabilize phase has pending P1–P4 tasks."
origin: codegraph
---

# Codegraph Repair Loop Skill

Systematic, priority-ordered process for making a codegraph graph healthy and analyzable.

## When to Use

- `codegraph tasks` shows P1–P4 items
- `codegraph build` exits non-zero
- `codegraph analyze` shows blocking violations
- After a large refactor leaves the graph inconsistent
- Before starting the EVOLVE phase

## Repair Priority Order

Always fix in this order — never skip a higher priority to fix a lower one:

```
P1  → policy_violation      (architecture governance broken)
P2  → missing_import         (graph edges missing)
P3  → orphan_node            (unreachable nodes)
P4  → stale_intent           (annotations outdated)
P10 → intent_missing         (no annotation — lowest priority)
```

## Repair Recipes

### P1 — Policy Violation

```bash
# Find the violating node
codegraph suggest list
codegraph query "callees(<node_id>)"

# Option A: Fix the code (remove the forbidden dependency)
# Option B: Justify rule removal
codegraph suggest remove <rule_id>
# Requires: documented reason why the rule doesn't apply
```

Decision criteria:
- If violation is real (code violates intent) → fix code
- If rule is wrong (too strict / outdated) → propose rule update
- Never silently ignore P1 violations

### P2 — Missing Import

```bash
# Find what's missing
codegraph analyze --json | python -c "import json,sys; [print(v) for v in json.load(sys.stdin).get('violations',[]) if v.get('type')=='missing_import']"

# Add the import to the source file
# Then verify graph updates
codegraph build
```

### P3 — Orphan Node

```bash
codegraph query "callers(<node_id>)"
codegraph query "callees(<node_id>)"
```

Classification decision:
- Zero callers AND zero callees → likely dead code
  - If yes: `codegraph annotate --node <id> --tag dead_code` (ask human to remove)
  - If no (it's a CLI/test entry point): `codegraph annotate --node <id> --tag entry_point`
- Has callees but no callers → probably an entry point or was renamed

### P4 — Stale Intent

```bash
# View current intent
codegraph explain <node_id> --json

# Update to match current code behavior
codegraph annotate --node <node_id> --intent "<new accurate description>"
```

### P10 — Intent Missing

```bash
# Generate missing intents
codegraph intent-missing

# Batch apply from file
codegraph intent-apply intents.json
```

## Loop Execution

```
for cycle in 1..3:
    run: codegraph build
    run: codegraph analyze --json
    run: codegraph tasks

    if no P1-P4 tasks:
        break  ← stabilized

    fix all P1 tasks
    fix all P2 tasks
    fix all P3 tasks (confirm with human before deleting)
    fix all P4 tasks

if still P1-P4 after cycle 3:
    ESCALATE to human — do not continue
```

## Exit Criteria

Repair is complete when:
- `codegraph analyze` reports 0 P1 violations
- `codegraph analyze` reports 0 P2 missing imports
- `codegraph analyze` reports 0 P3 orphans (or all tagged/confirmed)
- `codegraph build` exits 0

## Known Pitfalls

| Pitfall | Symptom | Fix |
|---------|---------|-----|
| `__pycache__` deletion | build fails on `.pyc` errors | `git checkout -- codegraph/__pycache__` |
| `extract_project()` return mismatch | `build` fails with `unpack NoneType` | Verify function returns `(graph0, report)` |
| `index.py` high-fan-in | test breaks after extraction | Add compat wrapper re-exporting from new location |
| `.codegraph` staged deletion | clean-tree preflight blocks | Verify scope before continuing |
