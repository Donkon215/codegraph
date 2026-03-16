This repository contains **codegraph**, an AI-aware architecture analysis engine for Python.

When working in this codebase:

1. Run `codegraph build` after making structural changes to update the graph
2. Run `codegraph analyze` to check for architecture violations
3. The system communicates through JSON files in `.codegraph/`
4. Agent repairs go through `agent_response.json` — see `AGENT.md` for format
5. Always use `--dry-run` before applying repairs
6. Node IDs follow the pattern `relative/path.py::ClassName::method_name`
7. Run tests with `python -m pytest tests/ -x --tb=short -q` (403 tests)
8. The CLI entry point is `codegraph/cli.py` using Click
9. All models are dataclasses in `codegraph/models/`
10. JSON schemas live in `codegraph/schemas/`

## Specialized Agents (`.claude/agents/`)

Use these agents for focused tasks — delegate rather than running the full pipeline manually:

| Agent | Use When |
|-------|----------|
| `codegraph-governor` | Orchestrating the full pipeline — dispatches to all other agents |
| `codegraph-architect` | Planning splits, cycle removal, subsystem evolution |
| `codegraph-arch-search` | Generating and ranking architecture improvement candidates |
| `codegraph-simulator` | Simulating candidates before proof gate |
| `codegraph-proof` | Proving architecture safety (cycle, layer, coupling, budget checks) |
| `codegraph-stabilizer` | `build` fails, P1–P4 violations, graph inconsistency |
| `codegraph-implementer` | Executing an already-proven architecture plan |
| `codegraph-reviewer` | Validating a branch before merge |
| `codegraph-cross-language` | React frontend + Python backend architecture analysis |

## Skills (`.claude/skills/`)

| Skill | Use When |
|-------|----------|
| `codegraph-pipeline` | Reference for pipeline state machine and command sequences |
| `codegraph-repair-loop` | Fixing broken graph state, priority-ordered repair recipes |
| `codegraph-query-language` | Writing `codegraph query` expressions |

## Cross-Language Support

The cross-language graph (`build_cross_language_links`) connects:
- `fetch('/api/...')` and `axios.get/post('/api/...')` in TSX/TS/JS → Python route handlers
- TypeScript `interface XDTO` → Python `class XModel / XSchema`
- Service boundary nodes: `frontend`, `backend`, `worker`

Tests live in `tests/cross_language/test_react_python_graph.py`.
