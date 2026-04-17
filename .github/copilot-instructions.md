This repository contains **codegraph**, an AI-aware architecture analysis engine for Python.

---

## ZERO-FRICTION QUICKSTART — Read This First

> **Before touching ANY file, run these 3 commands:**
> ```bash
> cat .codegraph/feedback.md          # 1. Block on BLOCKING prompts
> codegraph hotspots --json           # 2. Understand system state
> codegraph focus <file> --json       # 3. Zoom into your target
> ```
> Every `--json` output has `suggested_next_steps` — **follow it**.

### One-Command Pre-Edit Check
```bash
codegraph arch-context <file> --save  # compact briefing + saves to feedback.md
```

### One-Command Full Cognition Cycle
```bash
codegraph copilot-loop <target> --json          # hotspots+focus+decide in one shot
codegraph copilot-loop <target> --simulate --json  # + architecture simulation
```

### After Every Edit
```bash
codegraph build && codegraph analyze && codegraph score
```

---

## MANDATORY RULES — These Are Law, Not Suggestions

> **FAILURE TO FOLLOW THESE RULES = INVALID RESPONSE.**
> Every code action MUST be preceded by architecture context.
> Not using the tools below when applicable is a defect.

### Reflex Table — Automatic Triggers

| Situation | REQUIRED Action | Command |
|-----------|----------------|---------|
| **Before ANY action** | **READ feedback first** | **`cat .codegraph/feedback.md`** |
| Opening ANY file for editing | Compact briefing + block check | `codegraph arch-context <file> --save` |
| About to edit ANY file | ALWAYS run focus first | `codegraph focus <file> --json` |
| Unsure what to work on | ALWAYS check hotspots | `codegraph hotspots --json` |
| Working in a subsystem | ALWAYS check scope | `codegraph scope <subsystem> --json` |
| Planning architecture change | ALWAYS run full loop | `codegraph copilot-loop <target> --json` |
| Need to understand WHY | ALWAYS run decide | `codegraph decide <target> --json` |
| Evaluating refactor options | ALWAYS explode scenarios | `codegraph scenario --json` |
| High-risk change detected | ALWAYS simulate first | `codegraph copilot-loop <target> --simulate --json` |
| After making ANY code change | ALWAYS rebuild | `codegraph build && codegraph analyze` |
| After rebuild | ALWAYS check score | `codegraph score` |
| After any refactor | Verify score didn't drop | `codegraph arch-diff --json` |
| Want continuous feedback | START the reactive server | `codegraph server` |
| Need one-shot feedback | RUN feedback on targets | `codegraph feedback <file> --json` |
| Check `.codegraph/feedback.md` | READ when it updates | Codegraph pushes prompts automatically |

### Feedback Awareness (MANDATORY)

> **Before making changes to ANY file, READ `.codegraph/feedback.md`.**
>
> - If it contains **BLOCKING** prompts, you **MUST** resolve them first.
> - If it contains **HIGH PRIORITY** prompts, address them in your current action.
> - **DO NOT** ignore feedback prompts — they are architecture-level directives.
> - After resolving a blocking prompt, re-run `codegraph feedback <file> --json` to confirm.

### The Copilot Loop (REQUIRED execution order)

```
1. codegraph hotspots --json           # What needs attention?
2. codegraph focus <target> --json     # Zoom in on target
3. codegraph decide <target> --json    # WHY this action?
4. [make changes]                      # Implement
5. codegraph build && codegraph analyze  # Rebuild
6. codegraph focus <target> --json     # Verify improvement
7. codegraph score                     # Check score delta
```

Or use the single-command orchestrator:
```bash
codegraph copilot-loop <target> --json              # Full cognition cycle
codegraph copilot-loop <target> --simulate --json    # With simulation
codegraph copilot-loop <target> --simulate --save    # Persist decision
```

### JSON Output Guides You

Every `--json` output includes `suggested_next_steps` — an array of exact
commands to run next. **ALWAYS read and follow `suggested_next_steps`.**
The system tells you what to do next. Trust it.

### Hooks (`.claude/hooks/`)

Automated safety checks that run at lifecycle points. See `.claude/hooks/hooks.json` for configuration.

| Hook | When | Blocking |
|------|------|----------|
| `pre-edit.sh <file>` | Before any file edit | Yes — aborts if BLOCKING feedback exists |
| `post-edit.sh <file>` | After any file edit | No — rebuilds graph, checks score |
| `pre-commit.sh` | Before git commit | Yes — tests, violations, branch check |
| `pre-pipeline.sh` | Before architecture pipeline | Yes — clean tree, lock, baseline |
| `post-pipeline.sh` | After architecture pipeline | Yes — score compare, drift, lock |
| `pre-refactor.sh <target>` | Before refactoring | Yes — scope analysis, snapshot |
| `post-refactor.sh <target>` | After refactoring | Yes — build, test, score, snapshot |

Skipping a blocking hook is a rule violation.

## Self-Modification Rules (MANDATORY)

When working on **codegraph itself**, these rules prevent chaos during self-improvement:

1. **NEVER modify core subsystems without scope analysis**
   ```bash
   codegraph scope <subsystem> --json
   codegraph decide <target> --json
   ```
2. **If a BLOCKING prompt exists → STOP and resolve before continuing**
   - Read `.codegraph/feedback.md`
   - If BLOCKING: fix it first, re-run `codegraph feedback <file> --json`, confirm resolved
3. **DO NOT refactor multiple subsystems in the same step**
   - One subsystem per change. Verify with `codegraph scope` before and after.
4. **DO NOT change architecture + logic in the same step**
   - Separate structural moves (extract, split, rename) from behavioral changes (new features, bug fixes)
5. **Prefer SMALL, REVERSIBLE changes**
   - Use compatibility wrappers for high-fan-in modules
   - Use `--dry-run` before applying any repairs
   - One module at a time, test between each
6. **After every self-modification → full verify cycle**
   ```bash
   codegraph build && codegraph analyze
   python -m pytest tests/ -x --tb=short -q
   codegraph score
   ```
7. **NEVER skip the proof gate for architecture changes**
   - `codegraph prove --json` must return `PROVEN_SAFE` or `PROVEN_WARNING`
   - `REJECTED` = stop immediately

## Codebase Rules

1. Run `codegraph build` after making structural changes to update the graph
2. Run `codegraph analyze` to check for architecture violations
3. The system communicates through JSON files in `.codegraph/`
4. Agent repairs go through `agent_response.json` — see `AGENT.md` for format
5. Always use `--dry-run` before applying repairs
6. Node IDs follow the pattern `relative/path.py::ClassName::method_name`
7. Run tests with `python -m pytest tests/ -x --tb=short -q`
8. The CLI entry point is `codegraph/cli/` using Click (package split)
9. All models are dataclasses in `codegraph/models/`
10. JSON schemas live in `codegraph/schemas/`

## Precision Context Commands

### Arch-Context — Compact Copilot briefing for a file (FASTEST)
```bash
codegraph arch-context codegraph/analyzer.py          # print briefing
codegraph arch-context codegraph/analyzer.py --save   # + write to feedback.md
codegraph arch-context codegraph/index.py --json      # JSON with full decision
```
Output is a 6-10 line markdown card: layer, subsystem, fan-in/out, violations, verdict, next action.
Read this BEFORE editing any file.

### Focus — Surgical zoom on a file or node
```bash
codegraph focus codegraph/analyzer.py --json
codegraph focus codegraph/index.py::build_index --json
```

### Hotspots — What needs attention most
```bash
codegraph hotspots --json
```

### Scope — Subsystem boundary context
```bash
codegraph scope extraction --json
codegraph scope governance --json
```

### Decide — Structured architecture reasoning
```bash
codegraph decide codegraph/analyzer.py --json
codegraph decide codegraph/index.py::build_index --save --json
```

### Scenario — Component interaction explosion
```bash
codegraph scenario --json
codegraph scenario --components codegraph/index.py --json
codegraph scenario --components codegraph/index.py --components codegraph/analyzer.py --json
```

### Copilot Loop — Full cognition cycle
```bash
codegraph copilot-loop codegraph/analyzer.py --json
codegraph copilot-loop codegraph/index.py --simulate --json
codegraph copilot-loop extraction --save --json
```

### Reactive Server — Push-model feedback (Codegraph whispers)
```bash
codegraph server                          # Watch files, auto-analyze, push prompts
codegraph server --simulate --interval 5  # With deep simulation, slower polling
codegraph server --json --quiet           # JSON mode, no terminal output
```

### Feedback — One-shot reactive analysis
```bash
codegraph feedback codegraph/analyzer.py                    # Single file
codegraph feedback codegraph/index.py codegraph/query.py    # Multiple files
codegraph feedback --simulate --json                        # Auto-detect via git
```

When the server is running, read `.codegraph/feedback.md` for architecture prompts.
Prompt types: `violation` | `decision` | `risk` | `optimization`.

### Arch-Diff — Score + violation delta since last snapshot
```bash
codegraph arch-diff                   # current vs previous history entry
codegraph arch-diff --ref pre-refactor  # current vs named snapshot
codegraph arch-diff --json            # machine-readable delta
```
Use this after any refactor to confirm the score improved (or didn't regress).
`verdict` field: `improved` | `unchanged` | `regressed`.

## Architecture Query Patterns

```bash
# Direct dependencies
codegraph query "callees(codegraph/index.py::build_index)"
codegraph query "callers(codegraph/analyzer.py::analyze)"

# Find all nodes in a subsystem
codegraph query "SELECT nodes IN subsystem(extraction)"

# Cross-subsystem violations
codegraph query "SELECT edges WHERE crosses_subsystem=true"

# Find cycles
codegraph query "SELECT cycles WHERE in_layer(service)"

# Explain a node comprehensively
codegraph explain codegraph/index.py::build_index
```

## Skills (`.claude/skills/`)

All specialist capabilities are available as skills. Load the relevant SKILL.md before performing specialized work.

| Skill | Use When |
|-------|----------|
| `codegraph-governor` | Orchestrating the full pipeline — phase sequencing, failure recovery |
| `codegraph-architect` | Planning splits, cycle removal, subsystem evolution |
| `codegraph-arch-search` | Generating and ranking architecture improvement candidates |
| `codegraph-simulator` | Simulating candidates before proof gate |
| `codegraph-proof` | Proving architecture safety (cycle, layer, coupling, budget checks) |
| `codegraph-stabilizer` | `build` fails, P1–P4 violations, graph inconsistency |
| `codegraph-implementer` | Executing an already-proven architecture plan |
| `codegraph-reviewer` | Validating a branch before merge |
| `codegraph-cross-language` | React frontend + Python backend architecture analysis |
| `codegraph-pipeline` | Reference for pipeline state machine and command sequences |
| `codegraph-repair-loop` | Fixing broken graph state, priority-ordered repair recipes |
| `codegraph-query-language` | Writing `codegraph query` expressions |
| `copilot-loop` | Fast in-loop context gathering — focus, hotspots, scope recipes |

## Key Architecture Files

| File | Purpose |
|------|---------|
| `.codegraph/context/copilot_context.json` | Full enriched context (after `arch-context --save`) |
| `.codegraph/architecture/system.json` | Subsystem definitions, edges, constraints |
| `.codegraph/graphs/graph0.json` | Raw dependency graph |
| `.codegraph/graphs/graph1.json` | Annotated graph with intents and layers |
| `.codegraph/workflow/workflow.json` | Workflow edges (calls, data flow) |
| `.codegraph/analysis/violations.json` | Current architecture violations |
| `.codegraph/decisions/DEC-*.json` | Architecture decision reasoning traces |
| `.codegraph/proofs/latest_proof.json` | Proof status (PROVEN_SAFE / REJECTED) |
| `.codegraph/feedback.md` | Reactive server prompts (read by Copilot) |
| `.codegraph/feedback.json` | Reactive prompts in JSON format |
| `.codegraph/calibration/confidence_calibration.json` | Prediction tracking |
| `agent_response.json` | Agent repair tasks |

## Cross-Language Support

The cross-language graph (`build_cross_language_links`) connects:
- `fetch('/api/...')` and `axios.get/post('/api/...')` in TSX/TS/JS → Python route handlers
- TypeScript `interface XDTO` → Python `class XModel / XSchema`
- Service boundary nodes: `frontend`, `backend`, `worker`

Tests live in `tests/cross_language/test_react_python_graph.py`.
