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
