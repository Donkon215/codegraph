# Codegraph — Self-Evolving AI Architecture Engine

## Design

Codegraph is a **self-evolving architecture engine** operated by the AI agent (Copilot). It builds, analyzes, enforces, and evolves architecture through 7 layers.

```
Human             = Architecture Designer (approves rules, reviews proposals)
Codegraph         = Architecture Governor  (enforces rules, detects violations)
Copilot (Agent)   = Architecture Worker    (executes tasks, proposes rules, implements code)
```

### The 7-Layer Architecture Pipeline

| Layer | Purpose | Key Modules |
|-------|---------|-------------|
| 1. **Intent** | Capture what functions do | graph1 intents, semantic behaviors |
| 2. **Architecture** | Define system structure | system.json, arch_schema, target_architecture |
| 3. **Analysis** | Detect violations & smells | analyzer, architecture_advisor, architecture_lock, drift_detector |
| 4. **Planning** | Convert deltas to tasks | architecture_compiler, code_planner, tasks |
| 5. **Execution** | Apply repairs & changes | apply, branch_executor, agent_response |
| 6. **Validation** | Verify convergence | CAS hashing, delta, copilot_context |
| 7. **Evolution** | Improve architecture over time | architecture_simulator, arch_memory, subsystem_lifecycle |

### Autonomous Loop

```
intent → compile → simulate → plan → execute → validate → evolve → repeat
```

## For AI Agents

Read `.claude/agents/codegraph.agent.md` for the complete protocol:
- Full pipeline steps
- How to handle each task type
- `agent_response.json` format
- Which files you read vs write
- Rules and constraints

## CLI Commands

### Core Pipeline
```
codegraph build              # Extract structure, build all graphs
codegraph analyze            # Detect architecture violations
codegraph tasks              # Generate agent task queue
codegraph apply FILE         # Apply agent repairs
codegraph delta              # Incremental change detection
codegraph status             # Project overview
```

### Query & Exploration
```
codegraph query EXPR         # Query graph (callees, callers)
codegraph explain NODE       # Comprehensive node info
codegraph diff               # Show graph changes
codegraph validate           # Check workflow integrity
```

### Architecture Management
```
codegraph architect          # Architecture advisor report
codegraph enrich             # Add intents to workflow edges
codegraph compile INTENT     # Compile intent → architecture changes
codegraph code-plan          # Generate code plan from delta
codegraph lock               # Check architecture boundary enforcement
codegraph drift              # Detect code vs architecture drift
codegraph arch-simulate      # Simulate architecture changes
codegraph copilot-context    # Generate comprehensive Copilot context
```

### Governance & Policy
```
codegraph suggest list       # Show all policy rules
codegraph suggest add        # Add a new rule
codegraph suggest remove     # Remove a rule
```

### Content Addressing & Semantics
```
codegraph cas build          # Compute content hashes
codegraph cas verify         # Verify hash integrity
codegraph semantic build     # Extract semantic behaviors
codegraph semantic summary   # Show behavior statistics
codegraph semantic check     # Semantic policy checks
```
