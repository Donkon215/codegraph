# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes       |

## Reporting a Vulnerability

If you discover a security vulnerability in codegraph, please report it
responsibly:

1. **Do not** open a public issue.
2. Email the maintainers at **security@codegraph.dev** with:
   - A description of the vulnerability.
   - Steps to reproduce.
   - Potential impact.
3. You will receive an acknowledgment within 48 hours.
4. A fix will be developed and released as soon as possible.

## Security Considerations

codegraph processes source code from the local file system and stores
analysis data in JSON files and SQLite databases under `.codegraph/`.

### Threat Model

- **Input**: Python source files from the project directory. codegraph uses
  `ast.parse()` (safe) — it never uses `eval()`, `exec()`, or `compile()`
  with untrusted code.
- **Storage**: All data is stored locally. No network access is performed
  during normal operation.
- **CLI**: Commands accept file paths and configuration values. Path arguments
  are validated and restricted to the project directory tree.
- **Dependencies**: Minimal runtime dependencies (click, pyyaml, coverage).

### What codegraph Does NOT Do

- Execute or import analyzed source code.
- Send data over the network.
- Access files outside the project directory.
- Require elevated privileges.

## Best Practices for Users

- Review `.codegraph/config.yaml` before running `codegraph build` on
  untrusted repositories.
- Keep codegraph and its dependencies up to date.
- Use `codegraph validate` to check graph integrity before relying on
  analysis results.
