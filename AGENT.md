# Codegraph — AI Architecture Analysis Engine

## Design

Codegraph is **not a tool for users to run**. It is a **backend engine operated exclusively by the AI agent (Copilot)**.

```
Copilot Agent    → runs codegraph, reads tasks, writes repairs, loops until clean
Human + Ext LLM  → design architecture rules in suggested_workflow.json
Codegraph        → graph engine + analyzer + repair engine
```

### Phase 1 — Copilot stabilizes the codebase
Copilot runs `build → analyze → tasks → reason → apply → delta → rebuild` until all tasks are resolved (intents annotated, orphans resolved, imports fixed).

### Phase 2 — Human designs architecture
Human reads graph files, asks an external LLM to propose architecture rules, saves them in `suggested_workflow.json`.

### Phase 3 — Copilot enforces architecture
Analyzer compares actual workflow against rules. Policy violations become tasks. Copilot fixes them automatically.

## For AI Agents

Read `.claude/agents/codegraph.agent.md` for the complete protocol:
- Full pipeline steps
- How to handle each task type
- `agent_response.json` format
- Which files you read vs write
- Rules and constraints

## CLI Commands

```
codegraph build              # Extract structure, build all graphs
codegraph analyze            # Detect architecture violations
codegraph tasks              # Generate agent task queue
codegraph query EXPR         # Query graph (callees, callers)
codegraph explain NODE       # Comprehensive node info
codegraph apply FILE         # Apply agent repairs
codegraph delta              # Incremental change detection
codegraph cas build          # Compute content hashes
codegraph cas verify         # Verify hash integrity
codegraph semantic build     # Extract semantic behaviors
codegraph semantic summary   # Show behavior statistics
codegraph status             # Project overview
codegraph diff               # Show graph changes
codegraph validate           # Check workflow integrity
```
