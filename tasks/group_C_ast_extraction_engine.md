# Group C — AST Extraction Engine (Graph_0)

> Python AST parsing, node extraction, body hashing, module/class/function discovery, and Graph_0 generation via `extractor.py`.

---

### TASK C-001 — Implement Python AST Parser Entry Point

**Description:**
Create the main entry point for AST extraction that takes a Python source file and returns its parsed AST.

**Reasoning:**
All node extraction starts with parsing source files using Python's `ast` module. This must handle syntax errors gracefully per the failure modes table.

**Implementation Steps:**
1. Implement `parse_file(file_path: Path) -> ast.Module` in `codegraph/extractor.py`
2. Read file contents with UTF-8 encoding
3. Call `ast.parse(source, filename=str(file_path))`
4. On `SyntaxError`: log warning with file and line, return None
5. On `UnicodeDecodeError`: log warning, return None

**Files:**
- `codegraph/extractor.py`

**Dependencies:** A-005, A-006, A-007

**Edge Cases:**
- File with syntax errors → skip, log warning
- File with encoding issues → skip, log warning
- Empty file → valid empty AST
- File with BOM marker

**Validation:**
- Valid Python file parses successfully
- Syntax error file returns None with warning logged
- Empty file returns empty module AST

---

### TASK C-002 — Implement Function Node Extractor

**Description:**
Extract all top-level function definitions from an AST as Graph_0 nodes.

**Reasoning:**
Functions are the primary unit of analysis. Each function becomes a node with type="function".

**Implementation Steps:**
1. Implement `extract_functions(tree: ast.Module, file_path: str) -> list[Graph0Node]`
2. Walk AST looking for `ast.FunctionDef` and `ast.AsyncFunctionDef` at module level
3. For each function:
   - Generate node ID: `file::function_name`
   - Compute body_hash from function body AST
   - Record line number
   - Set type to "function"
4. Handle async functions identically to sync

**Files:**
- `codegraph/extractor.py` (modify)

**Dependencies:** C-001, A-021, A-022, B-001

**Edge Cases:**
- Async functions → same treatment as sync
- Functions decorated with `@staticmethod`, `@classmethod` at module level (unusual but valid)
- Functions with duplicate names → collision handling
- Nested functions → see C-005

**Validation:**
- Simple function extracted with correct ID
- Async function extracted correctly
- Line numbers are accurate
- Body hash computed

---

### TASK C-003 — Implement Class Node Extractor

**Description:**
Extract all class definitions from an AST as Graph_0 nodes.

**Reasoning:**
Classes are structural containers. They get their own nodes with type="class" and their methods become separate nodes.

**Implementation Steps:**
1. Implement `extract_classes(tree: ast.Module, file_path: str) -> list[Graph0Node]`
2. Walk AST for `ast.ClassDef` nodes
3. For each class:
   - Generate node ID: `file::ClassName`
   - Compute body_hash from class body (all methods combined)
   - Record line number
   - Set type to "class"
4. Handle nested classes (see C-006)

**Files:**
- `codegraph/extractor.py` (modify)

**Dependencies:** C-001, A-021, A-022, B-001

**Edge Cases:**
- Empty class (only pass) → valid node
- Class with only class variables → valid node
- Metaclass usage → treat as regular class
- Dataclass decorator → treat as regular class

**Validation:**
- Class extracted with correct ID format
- Body hash includes all method bodies
- Nested classes handled (see C-006)

---

### TASK C-004 — Implement Method Node Extractor

**Description:**
Extract all methods within classes as Graph_0 nodes with type="method".

**Reasoning:**
Methods are callable units within classes. Their node ID includes the class name: `file::Class::method`.

**Implementation Steps:**
1. Implement `extract_methods(class_node: ast.ClassDef, file_path: str, class_name: str) -> list[Graph0Node]`
2. Iterate over class body looking for `ast.FunctionDef` and `ast.AsyncFunctionDef`
3. For each method:
   - Generate node ID: `file::ClassName::method_name`
   - Compute body_hash from method body
   - Record line number
   - Set type to "method"
4. Handle `@staticmethod`, `@classmethod`, `@property` as regular methods

**Files:**
- `codegraph/extractor.py` (modify)

**Dependencies:** C-003, A-021, A-022, B-001

**Edge Cases:**
- `__init__`, `__repr__`, etc. → extract as nodes (filtering is separate concern)
- Property methods → type="method"
- Static methods → type="method"
- Overloaded methods (same name with @overload) → collision handling

**Validation:**
- Method ID includes class name
- All method types extracted
- Body hash per method, not per class

---

### TASK C-005 — Implement Nested Function Extraction

**Description:**
Extract nested (inner) function definitions as Graph_0 nodes.

**Reasoning:**
Functions can be defined inside other functions. These are real code units that should be tracked.

**Implementation Steps:**
1. Extend function extraction to recurse into function bodies
2. For nested functions:
   - ID: `file::outer::inner`
   - Deeply nested: `file::outer::middle::inner`
3. Track nesting depth for ID construction
4. Apply collision handling for identically named nested functions

**Files:**
- `codegraph/extractor.py` (modify)

**Dependencies:** C-002

**Edge Cases:**
- Lambda expressions → skip (no name, no useful ID)
- Closures → extract as nested functions
- Deeply nested (3+ levels) → include all levels in ID
- Same name at different nesting levels → different IDs naturally

**Validation:**
- Nested function has correct multi-level ID
- Deep nesting produces correct ID chain
- Lambda expressions are skipped

---

### TASK C-006 — Implement Nested Class Extraction

**Description:**
Extract nested class definitions as Graph_0 nodes.

**Reasoning:**
Classes can be nested inside other classes. These are relatively rare but must be handled correctly.

**Implementation Steps:**
1. Extend class extraction to recurse into class bodies
2. Nested class ID: `file::OuterClass::InnerClass`
3. Methods of nested classes: `file::OuterClass::InnerClass::method`

**Files:**
- `codegraph/extractor.py` (modify)

**Dependencies:** C-003

**Edge Cases:**
- Deeply nested classes
- Inner class with same name as outer (collision)

**Validation:**
- Nested class ID includes parent class
- Methods of nested class include full chain

---

### TASK C-007 — Implement Module Node Extraction

**Description:**
Extract module-level nodes representing entire Python files/packages.

**Reasoning:**
The README states modules can be annotated with intent. Module IDs use the path without file extension.

**Implementation Steps:**
1. Implement `extract_module_node(file_path: str) -> Graph0Node`
2. Module ID: path relative to project root, no `.py` extension
   - `src/pipeline.py` → ID: `src/pipeline`
3. Module body_hash: hash of entire file content (or top-level statements only)
4. Type: "module"
5. Line: 1

**Files:**
- `codegraph/extractor.py` (modify)

**Dependencies:** C-001, A-022, B-001

**Edge Cases:**
- `__init__.py` files → module ID is the package name
- Package name vs module name distinction
- Empty module file

**Validation:**
- Module ID has no `.py` extension
- `__init__.py` produces package-level ID
- Line is always 1

---

### TASK C-008 — Implement Full File Extraction Pipeline

**Description:**
Create the main extraction function that processes a single file and returns all nodes (module, classes, functions, methods).

**Reasoning:**
The pipeline must orchestrate all extractors in the correct order and handle collisions across the combined node set.

**Implementation Steps:**
1. Implement `extract_file(file_path: Path, project_root: Path) -> list[Graph0Node]`
2. Parse file → AST
3. Extract module node
4. Extract top-level functions
5. Extract classes with their methods
6. Extract nested functions
7. Resolve collisions across all nodes
8. Return sorted list of all nodes

**Files:**
- `codegraph/extractor.py` (modify)

**Dependencies:** C-001 through C-007, B-024

**Edge Cases:**
- File with only imports → one module node only
- File with syntax error → return empty list
- Very large file (10k+ lines) → performance consideration

**Validation:**
- All node types extracted from a complex file
- Collisions resolved
- Order is deterministic

---

### TASK C-009 — Implement Full Project Extraction Pipeline

**Description:**
Create the top-level extraction function that processes all source files in a project and produces the complete Graph_0.

**Reasoning:**
This is what `codegraph build` calls. It discovers all source files, extracts nodes from each, and assembles the complete Graph_0.

**Implementation Steps:**
1. Implement `extract_project(project_root: Path, config: Config) -> Graph0`
2. Discover all source files using file discovery utility
3. Extract nodes from each file (with progress reporting)
4. Collect all nodes into Graph_0 collection
5. Assign graph_version
6. Set extraction timestamp
7. Log summary: total files, total nodes, warnings

**Files:**
- `codegraph/extractor.py` (modify)

**Dependencies:** C-008, A-033, A-009, B-002, A-012

**Edge Cases:**
- Empty project (no .py files) → empty Graph_0
- Project with only test files → still extract
- Very large project (1000+ files) → progress reporting
- Files that change during extraction

**Validation:**
- All source files processed
- Graph_0 has correct node count
- graph_version set
- Progress reported for large projects

---

### TASK C-010 — Implement AST Body Hash — Whitespace Invariance

**Description:**
Ensure the body hash computation ignores all whitespace differences.

**Reasoning:**
The README states body_hash ignores whitespace. Reformatting code (e.g., running black) must not change body_hash.

**Implementation Steps:**
1. In body hash computation, serialize AST nodes without whitespace
2. Use `ast.dump()` which normalizes whitespace
3. Verify that `ast.dump` produces identical output for equivalent ASTs with different formatting

**Files:**
- `codegraph/utils.py` (modify)

**Dependencies:** A-021

**Validation:**
- Same function with different indentation → same hash
- Same function with extra blank lines → same hash
- Same function reformatted by black → same hash

---

### TASK C-011 — Implement AST Body Hash — Comment Invariance

**Description:**
Ensure the body hash computation ignores comments.

**Reasoning:**
Comments are stripped by `ast.parse()` so they don't affect the AST, but inline comments in f-strings or multi-line strings might. Verify docstrings are also excluded.

**Implementation Steps:**
1. Verify that Python's `ast.parse()` strips all comments
2. Handle docstrings: exclude the first `ast.Expr(ast.Constant(str))` in function body
3. Ensure string literals that look like comments don't affect hash

**Files:**
- `codegraph/utils.py` (modify)

**Dependencies:** A-021

**Edge Cases:**
- Function with only a docstring → minimal body hash
- Multi-line docstring
- Docstring with code examples

**Validation:**
- Adding comment to function → hash unchanged
- Changing docstring → hash unchanged
- Removing docstring → hash unchanged

---

### TASK C-012 — Implement AST Body Hash — Logic Change Detection

**Description:**
Verify that logic changes (different control flow, different function calls, different variable use) produce different hashes.

**Reasoning:**
The entire purpose of body_hash is to detect when function logic changes, triggering stale intent warnings.

**Implementation Steps:**
1. Test matrix of changes that SHOULD change hash:
   - Adding/removing function calls
   - Changing control flow (if → if/else)
   - Changing variable names (since they appear in AST)
   - Changing operators
   - Adding/removing parameters
2. Test matrix of changes that should NOT change hash:
   - Whitespace changes
   - Comment changes
   - Docstring changes

**Files:**
- `codegraph/utils.py` (modify — if adjustments needed)

**Dependencies:** C-010, C-011

**Validation:**
- All logic changes produce different hashes
- All formatting changes produce same hashes

---

### TASK C-013 — Implement Decorator Extraction

**Description:**
Extract decorator information from functions, methods, and classes for metadata purposes.

**Reasoning:**
Decorators affect behavior (e.g., `@staticmethod`, `@property`, `@app.route`). While not part of body_hash, they're useful metadata for intent generation and analysis.

**Implementation Steps:**
1. Extract decorator names from AST nodes
2. Store as optional metadata on Graph0Node (or as separate annotation)
3. Handle:
   - Simple decorators: `@staticmethod`
   - Call decorators: `@app.route("/api")`
   - Chained decorators: multiple decorators on same function

**Files:**
- `codegraph/extractor.py` (modify)
- `codegraph/models/graph0.py` (modify — add optional decorators field)

**Dependencies:** C-002, C-004

**Edge Cases:**
- Decorator with complex arguments
- Custom decorators from external libraries
- Decorator that wraps/replaces the function entirely

**Validation:**
- Decorator names extracted correctly
- Complex decorator arguments captured
- Multiple decorators listed in order

---

### TASK C-014 — Implement Parameter Extraction

**Description:**
Extract function/method parameter signatures for metadata purposes.

**Reasoning:**
Parameters help agents understand function interfaces. They're useful context for intent generation without reading source code.

**Implementation Steps:**
1. Extract parameter list from `ast.arguments`
2. For each parameter: name, type annotation (if present), default value (if present)
3. Handle: positional, keyword, *args, **kwargs
4. Store as optional metadata on Graph0Node

**Files:**
- `codegraph/extractor.py` (modify)

**Dependencies:** C-002, C-004

**Edge Cases:**
- No parameters (except self)
- Complex type annotations
- Default values with function calls
- Parameter unpacking

**Validation:**
- All parameter types extracted
- Type annotations captured when present
- Default values noted

---

### TASK C-015 — Implement Return Type Extraction

**Description:**
Extract return type annotations from functions and methods.

**Reasoning:**
Return types are valuable metadata for intent generation and type-level analysis.

**Implementation Steps:**
1. Check `ast.FunctionDef.returns` for return annotation
2. Convert annotation AST node to string representation
3. Store as optional metadata on Graph0Node

**Files:**
- `codegraph/extractor.py` (modify)

**Dependencies:** C-002, C-004

**Edge Cases:**
- No return annotation → None
- Complex return type (Union, Optional, Generic)
- `-> None` annotation

**Validation:**
- Return type extracted when present
- None when absent
- Complex types serialized as strings

---

### TASK C-016 — Implement Import Statement Extraction

**Description:**
Extract all import statements from a Python file for dependency tracking.

**Reasoning:**
Imports are stored separately and available via `codegraph query "dependencies(module)"`. They're not in the default workflow graph but are needed for dead code detection.

**Implementation Steps:**
1. Implement `extract_imports(tree: ast.Module, file_path: str) -> list[ImportInfo]`
2. Handle `import X`, `from X import Y`, `from . import Z` (relative)
3. Store: module name, imported names, alias, is_relative
4. Resolve relative imports to absolute paths where possible

**Files:**
- `codegraph/extractor.py` (modify)

**Dependencies:** C-001

**Edge Cases:**
- Relative imports in packages
- Star imports (`from X import *`)
- Conditional imports (inside if blocks)
- Type-checking only imports (`if TYPE_CHECKING:`)

**Validation:**
- All import forms extracted
- Relative imports resolved
- Conditional imports handled

---

### TASK C-017 — Implement Call Site Extraction for Static Analysis

**Description:**
Extract all function call sites from within function/method bodies for static workflow edge construction.

**Reasoning:**
Static call analysis produces `edge_type: call, confidence: static` edges. This is the primary source of workflow edges.

**Implementation Steps:**
1. Implement `extract_call_sites(func_node: ast.FunctionDef) -> list[CallSite]`
2. Walk function body AST looking for `ast.Call` nodes
3. For each call:
   - Resolve target name (simple name, attribute access, chained calls)
   - Record line number
   - Classify as direct, method call, or dynamic
4. Handle: `func()`, `obj.method()`, `module.func()`, `cls.method()`

**Files:**
- `codegraph/extractor.py` (modify)

**Dependencies:** C-001

**Edge Cases:**
- Chained calls: `a.b().c()` → multiple call sites
- Dynamic targets: `getattr(obj, name)()` → unresolvable
- Decorator calls
- Comprehension with function calls
- Lambda calls

**Validation:**
- Direct function calls resolved
- Method calls resolved with object name
- Dynamic calls marked as unresolvable

---

### TASK C-018 — Implement Call Target Resolution

**Description:**
Resolve call site names to Graph_0 node IDs.

**Reasoning:**
Raw call sites are names like `validate_trade()` or `self.process()`. These must be resolved to full node IDs like `src/trade.py::validate_trade`.

**Implementation Steps:**
1. Implement `resolve_call_target(call_site: CallSite, imports: list[ImportInfo], current_file: str, all_nodes: dict) -> Optional[str]`
2. Resolution strategy:
   a. Check if target name matches a function in same file
   b. Check if target name matches an imported name
   c. Check if target is a method call on a known class
   d. If unresolvable → return None (becomes dynamic edge)
3. Handle `self.method()` by resolving current class context

**Files:**
- `codegraph/extractor.py` (modify)

**Dependencies:** C-017, C-016

**Edge Cases:**
- Same function name in multiple files → disambiguate via imports
- `self.method()` → resolve to class method
- `super().method()` → resolve to parent class
- Imported alias (e.g., `import pandas as pd; pd.read_csv()`)

**Validation:**
- Local function calls resolved
- Imported function calls resolved
- Unresolvable calls return None
- self.method() resolved correctly

---

### TASK C-019 — Implement Dynamic Call Detection

**Description:**
Detect function calls whose targets cannot be determined statically and emit dynamic edges.

**Reasoning:**
The README describes dynamic dispatch patterns (registry, plugins, DI) that produce `edge_type: dynamic` edges with wildcard targets.

**Implementation Steps:**
1. Implement `detect_dynamic_calls(func_node: ast.FunctionDef) -> list[DynamicCall]`
2. Patterns to detect:
   - Dictionary lookup + call: `d[key]()`
   - `getattr(obj, name)()`
   - Variable function call: `f = some_lookup(); f()`
   - `*args` / `**kwargs` forwarding
3. For each, create edge with `target: "scope::*"`

**Files:**
- `codegraph/extractor.py` (modify)

**Dependencies:** C-017

**Edge Cases:**
- Complex dynamic patterns (decorator factories, etc.)
- Obvious dynamic patterns vs ambiguous ones
- False positives (variable that could be resolved but isn't)

**Validation:**
- Registry lookup pattern detected
- getattr pattern detected
- Edge target is `scope::*` format

---

### TASK C-020 — Implement Incremental File Extraction for Delta

**Description:**
Create an extraction function that re-extracts only specified files, producing a partial Graph_0 update.

**Reasoning:**
The delta engine needs to re-extract only changed files, not the entire project. This must produce results compatible with the full extraction.

**Implementation Steps:**
1. Implement `extract_files(file_paths: list[Path], project_root: Path) -> list[Graph0Node]`
2. Extract nodes from specified files only
3. Return nodes in the same format as full extraction
4. Used by delta engine to compare against previous Graph_0

**Files:**
- `codegraph/extractor.py` (modify)

**Dependencies:** C-008

**Validation:**
- Partial extraction produces same nodes as full extraction for the same files
- Results are usable for delta comparison

---

### TASK C-021 — Implement Extraction Caching

**Description:**
Cache extraction results per file using content hash to avoid re-parsing unchanged files.

**Reasoning:**
On large projects, full extraction can be slow. Caching avoids re-parsing files that haven't changed since last extraction.

**Implementation Steps:**
1. Implement `ExtractionCache` class in `codegraph/extractor.py`
2. Key: file content hash
3. Value: extracted nodes
4. Store cache in `.codegraph/cache/extraction_cache.json`
5. Invalidate entry when file content hash changes
6. Skip parsing for cache hits

**Files:**
- `codegraph/extractor.py` (modify)

**Dependencies:** C-008, A-020

**Edge Cases:**
- Cache corruption → ignore cache, re-extract
- Cache from different project version → invalidate all
- Very large cache → set size limit

**Validation:**
- Cache hit skips parsing
- Changed file invalidates cache entry
- Corrupted cache is handled gracefully

---

### TASK C-022 — Implement Extraction Error Handling and Recovery

**Description:**
Handle all extraction-level errors per the failure modes table.

**Reasoning:**
The README specifies: AST parse error → skip file, log warning, continue build. The extractor must never crash on a single file failure.

**Implementation Steps:**
1. Wrap per-file extraction in try/except
2. On `SyntaxError`: skip file, log with file path and line
3. On `UnicodeDecodeError`: skip file, log with file path
4. On any other exception: skip file, log full traceback
5. Collect all warnings and return with extraction result
6. Implement `ExtractionReport` with success/failure counts and warnings

**Files:**
- `codegraph/extractor.py` (modify)

**Dependencies:** C-009, A-007

**Edge Cases:**
- All files fail → empty Graph_0 with many warnings
- Binary file accidentally matched → skip gracefully
- Permission denied on file → skip with warning

**Validation:**
- Syntax error file skipped, others processed
- Warning logged with file path
- Extraction continues after errors

---

### TASK C-023 — Implement Class Hierarchy Extraction

**Description:**
Extract class inheritance relationships for analysis.

**Reasoning:**
Class hierarchy is needed for `super()` call resolution and understanding OOP structures. While not primary Graph_0 data, it's needed for accurate call resolution.

**Implementation Steps:**
1. When extracting a class, also extract its base classes
2. Store base class references as metadata
3. Resolve base classes to Graph_0 node IDs where possible
4. Handle: single inheritance, multiple inheritance, external base classes

**Files:**
- `codegraph/extractor.py` (modify)

**Dependencies:** C-003

**Edge Cases:**
- External base class (from library) → layer 1
- Multiple inheritance
- Metaclasses
- ABC hierarchy

**Validation:**
- Base classes extracted and referenced
- External base classes identified as layer 0/1

---

### TASK C-024 — Implement Global Variable / Constant Extraction

**Description:**
Extract module-level variable assignments that may be referenced by functions.

**Reasoning:**
Module-level constants (e.g., `MAX_RETRIES = 3`, `API_URL = "..."`) are referenced by functions and relevant for understanding module purpose.

**Implementation Steps:**
1. Implement `extract_globals(tree: ast.Module) -> list[GlobalDef]`
2. Extract `ast.Assign` and `ast.AnnAssign` at module level
3. Record variable name, type annotation (if any), and line number
4. Skip private variables (starting with `_`) optionally

**Files:**
- `codegraph/extractor.py` (modify)

**Dependencies:** C-001

**Edge Cases:**
- Multiple assignment (`a = b = 1`)
- Tuple unpacking (`x, y = 1, 2`)
- Constants vs mutable globals

**Validation:**
- Module-level constants extracted
- Type annotations captured
- Augmented assignments handled

---

### TASK C-025 — Implement Extraction Performance Optimization

**Description:**
Optimize the extraction pipeline for large repositories with 500+ files.

**Reasoning:**
The README mentions scaling concerns at 500+ files. Extraction should be parallelizable and efficient.

**Implementation Steps:**
1. Profile extraction on large sample projects
2. Use `concurrent.futures.ProcessPoolExecutor` for parallel file parsing
3. Each file can be parsed independently (no shared state)
4. Combine results after parallel extraction
5. Benchmark: extraction should process 100 files/second minimum

**Files:**
- `codegraph/extractor.py` (modify)

**Dependencies:** C-009

**Edge Cases:**
- Exception in worker process → handle, don't crash
- Memory pressure on very large projects → limit parallelism
- File system contention on network drives

**Validation:**
- Parallel extraction produces same results as sequential
- Measurable speedup on 500+ file projects
- Errors in individual files don't affect others

---

### TASK C-026 — Implement Scope-Aware Name Resolution

**Description:**
Build a scope tree during extraction that enables accurate name resolution for call targets.

**Reasoning:**
Python's scoping rules (LEGB) affect which name a call resolves to. Without scope awareness, call target resolution will be inaccurate.

**Implementation Steps:**
1. Create `ScopeTree` class that tracks variable bindings at each scope level
2. Build scope tree while walking AST:
   - Module scope (imports, globals)
   - Class scope (methods, class variables)
   - Function scope (parameters, locals)
3. Use scope tree during call target resolution
4. Handle: closures, global/nonlocal declarations

**Files:**
- `codegraph/extractor.py` (modify)

**Dependencies:** C-017, C-016

**Edge Cases:**
- `global` and `nonlocal` declarations
- Closures accessing outer scope
- Name shadowing (local hides module-level)
- Class variables vs instance variables

**Validation:**
- Local function resolves before imported function
- global declaration changes resolution
- Closure references resolved to outer scope

---

### TASK C-027 — Implement Extraction for __init__.py Files

**Description:**
Handle `__init__.py` files which define package-level nodes and re-exports.

**Reasoning:**
Package `__init__.py` files often re-export symbols and define package-level imports. They need special handling for module ID generation.

**Implementation Steps:**
1. Detect `__init__.py` files during file discovery
2. Module ID for `__init__.py`: use package path, not file path
   - `src/utils/__init__.py` → ID: `src/utils`
3. Extract re-exports (`__all__`, `from .module import X`)
4. Extract any functions/classes defined in `__init__.py`

**Files:**
- `codegraph/extractor.py` (modify)

**Dependencies:** C-007, C-016

**Edge Cases:**
- Empty `__init__.py` → still a module node
- `__init__.py` with complex re-export logic
- Namespace packages (no `__init__.py`)

**Validation:**
- Package ID is directory path, not file path
- Re-exports tracked
- Functions in `__init__.py` have correct IDs

---

### TASK C-028 — Implement Type Stub (.pyi) Handling

**Description:**
Decide on and implement handling for `.pyi` type stub files.

**Reasoning:**
Type stubs provide additional type information that could improve call target resolution. Research whether to extract or ignore them.

**Research Notes:**
- `.pyi` files are typically for external libraries
- Project-level `.pyi` might indicate custom stubs
- Decision: ignore by default, but use for enhanced type resolution if present

**Implementation Steps:**
1. By default, do not extract nodes from `.pyi` files
2. Optionally, use `.pyi` type information to improve call resolution
3. Add config option: `include_stubs: false`

**Files:**
- `codegraph/extractor.py` (modify)
- `codegraph/config.py` (modify)

**Dependencies:** C-009, A-009

**Validation:**
- `.pyi` files ignored by default
- Config option respected

---

### TASK C-029 — Implement Extraction Report Generator

**Description:**
Generate a summary report after extraction that includes statistics and warnings.

**Reasoning:**
After `codegraph build`, the user should see a summary of what was extracted, how many nodes, warnings, etc.

**Implementation Steps:**
1. Define `ExtractionReport` dataclass:
   - `files_processed: int`
   - `files_skipped: int`
   - `nodes_extracted: int` (by type)
   - `collisions: list[str]`
   - `warnings: list[str]`
   - `duration_seconds: float`
2. Return ExtractionReport from `extract_project()`
3. Format for CLI output

**Files:**
- `codegraph/extractor.py` (modify)

**Dependencies:** C-009

**Validation:**
- Report counts match actual extraction
- Warnings include file paths
- Duration is accurate

---

### TASK C-030 — Implement Graph_0 Persistence (Save/Load)

**Description:**
Implement saving Graph_0 to `.codegraph/graphs/graph0.json` and loading it back.

**Reasoning:**
Graph_0 must be persisted after extraction and loaded by all other components.

**Implementation Steps:**
1. Implement `save_graph0(graph0: Graph0, project_root: Path)`
2. Use atomic file writer
3. Format: indented JSON for readability
4. Implement `load_graph0(project_root: Path) -> Graph0`
5. Validate format on load

**Files:**
- `codegraph/extractor.py` (modify)
- `codegraph/storage.py` (modify)

**Dependencies:** C-009, A-013, B-002

**Edge Cases:**
- File doesn't exist on first load → return empty Graph_0
- Corrupted JSON → clear error message
- Very large file → streaming JSON parser?

**Validation:**
- Save then load produces identical Graph_0
- Missing file returns empty graph
- Corrupted file raises clear error

---

### TASK C-031 — Implement Graph_0 Comparison for Delta

**Description:**
Implement comparison logic between two Graph_0 instances to detect additions, removals, and modifications.

**Reasoning:**
The delta engine compares new extraction against previous Graph_0 to classify nodes as added/removed/modified.

**Implementation Steps:**
1. Implement `compare_graphs(old: Graph0, new: Graph0) -> GraphDiff`
2. Define `GraphDiff`: nodes_added, nodes_removed, nodes_modified (body_hash changed)
3. Match nodes by ID
4. Detect body_hash changes for matched nodes
5. Handle collision disambiguator changes

**Files:**
- `codegraph/extractor.py` (modify)

**Dependencies:** B-002, C-009

**Validation:**
- New node correctly classified as added
- Removed node correctly classified
- Changed body_hash classified as modified
- Unchanged node not reported

---

### TASK C-032 — Implement Extraction for Conditional Code

**Description:**
Handle code defined inside `if __name__ == "__main__":` blocks and other conditional definitions.

**Reasoning:**
Functions defined inside conditional blocks are real code that might be entry points. They need extraction with appropriate handling.

**Implementation Steps:**
1. Detect `if __name__ == "__main__":` blocks
2. Extract functions defined within as top-level functions
3. Optionally mark as "conditional" metadata
4. Handle other conditional patterns: `if sys.platform == "win32"`

**Files:**
- `codegraph/extractor.py` (modify)

**Dependencies:** C-002

**Edge Cases:**
- Functions defined in else branch of conditional
- Nested conditionals with function definitions
- try/except blocks with function definitions

**Validation:**
- Functions in `__main__` block extracted
- Conditional functions marked appropriately

---

### TASK C-033 — Implement Async-Specific Extraction

**Description:**
Handle async-specific patterns: async generators, async context managers, await expressions.

**Reasoning:**
Async Python code has specific patterns that affect workflow edge construction. Await expressions create implicit edges.

**Implementation Steps:**
1. Detect `async def` functions and extract as type="function" or "method"
2. Extract `await` expressions as potential call sites
3. Handle `async for` and `async with` as call sites
4. Mark functions as async in metadata

**Files:**
- `codegraph/extractor.py` (modify)

**Dependencies:** C-002, C-017

**Edge Cases:**
- `await` on non-coroutine (error in code, but don't crash)
- `async for` with async generator
- Nested async contexts

**Validation:**
- Async functions extracted correctly
- Await expressions create call sites
- Async metadata recorded

---

### TASK C-034 — Implement Extraction Determinism Guarantee

**Description:**
Ensure extraction always produces identical output for identical input, regardless of run order or parallelism.

**Reasoning:**
Deterministic output is essential for delta comparison and test stability. Parallel extraction must produce the same result as sequential.

**Implementation Steps:**
1. Sort all output lists deterministically (by node ID)
2. Ensure parallel extraction produces same order as sequential
3. Ensure body_hash is deterministic (no random elements)
4. Add determinism test: run extraction twice, compare byte-for-byte

**Files:**
- `codegraph/extractor.py` (modify)

**Dependencies:** C-009

**Validation:**
- Two identical extractions produce byte-identical JSON
- Parallel and sequential produce same output
- Order is by node ID

---

### TASK C-035 — Implement Extraction of Type Annotations for Nodes

**Description:**
Extract complete type annotation information from function signatures for richer metadata.

**Reasoning:**
Type annotations provide valuable information about what types flow through the codebase. This enhances both intent generation and call target resolution.

**Implementation Steps:**
1. Extract all parameter type annotations
2. Extract return type annotations
3. Store as structured metadata on Graph0Node
4. Handle:
   - Simple types: `int`, `str`
   - Generic types: `List[str]`, `Dict[str, int]`
   - Union types: `Union[str, None]` / `str | None`
   - Custom types: resolve to Graph_0 nodes where possible

**Files:**
- `codegraph/extractor.py` (modify)

**Dependencies:** C-014, C-015

**Edge Cases:**
- Forward references as strings
- `from __future__ import annotations`
- Complex nested generics

**Validation:**
- Simple types extracted correctly
- Generic types serialized as strings
- Forward references handled
