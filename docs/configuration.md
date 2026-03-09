# Configuration Reference

codegraph is configured via `.codegraph/config.yaml`. All keys are optional — sensible defaults are provided.

## Configuration Options

| Key                    | Type         | Default                    | Description                                                        |
|------------------------|--------------|----------------------------|--------------------------------------------------------------------|
| `internal_libs`        | `list[str]`  | `[]`                       | Directories treated as internal shared libraries (layer 2).        |
| `test_dirs`            | `list[str]`  | `[]`                       | Additional directories treated as test code (layer 4).             |
| `edge_filters`         | `list[str]`  | See below                  | Glob patterns for edge targets to exclude from the workflow graph. |
| `dunder_exclude`       | `list[str]`  | See below                  | Dunder methods to exclude from extraction.                         |
| `max_iterations`       | `int`        | `10`                       | Maximum convergence loop iterations.                               |
| `convergence_threshold`| `float`      | `0.05`                     | Convergence threshold (fraction of changed nodes).                 |
| `include_stubs`        | `bool`       | `false`                    | Whether to extract `.pyi` type stub files.                         |

## Layer System

Layers control which code agents can modify and how nodes are classified:

| Layer | Name           | Description                              | Modifiable? |
|-------|----------------|------------------------------------------|-------------|
| 0     | `STDLIB`       | Python standard library                  | No          |
| 1     | `EXTERNAL`     | Third-party packages (site-packages)     | No          |
| 2     | `INTERNAL_LIB` | Shared internal libraries (configured)   | No          |
| 3     | `PROJECT`      | Project source code (default)            | Yes         |
| 4     | `TEST`         | Test code                                | Yes         |

### Layer Detection Rules

Detection is applied in the following order:

1. **External (1)**: file resides in `site-packages` or is an editable-installed package.
2. **Internal Library (2)**: file is under a directory listed in `internal_libs`.
3. **Test (4)**: file matches test patterns (`test_*.py`, `*_test.py`, `conftest.py`) or is under `tests/`, `test/`, or a configured `test_dirs` entry.
4. **Project (3)**: everything else (default).

> **Note:** Stdlib detection (layer 0) is used for import-based classification. Project files are never classified as stdlib.

### Runtime Layer Override

Override layer detection from the CLI:

```bash
codegraph build --layer-override src/legacy/:2 --layer-override vendor/:1
```

Format: `path:layer_number`. Overrides are applied after automatic detection.

## Default Edge Filters

```yaml
edge_filters:
  - "builtins.*"
  - "typing.*"
  - "abc.*"
  - "collections.abc.*"
  - "logging.Logger.*"
  - "pathlib.Path.*"
  - "os.path.*"
```

## Default Dunder Exclusions

Methods like `__repr__`, `__str__`, `__len__`, `__hash__`, `__eq__`, `__ne__`, `__lt__`, `__le__`, `__gt__`, `__ge__`, `__bool__`, `__contains__`, `__iter__`, `__next__`, `__getitem__`, `__setitem__`, `__delitem__` are excluded by default.

## Complete Example

```yaml
# .codegraph/config.yaml
internal_libs:
  - shared/utils
  - libs/core

test_dirs:
  - integration_tests
  - e2e

edge_filters:
  - "builtins.*"
  - "typing.*"
  - "abc.*"

include_stubs: true
max_iterations: 15
convergence_threshold: 0.03
```

## Config Change Detection

After modifying `config.yaml`, run `codegraph build` for a full rebuild. The system stores a hash of the config file and will warn if it detects changes since the last build.

## Missing Config File

If `.codegraph/config.yaml` does not exist, all defaults are used. Run `codegraph init` to create the `.codegraph/` directory structure.
