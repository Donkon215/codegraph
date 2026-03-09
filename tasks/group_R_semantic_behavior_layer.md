# Group R — Semantic Behavior Layer (Graph_2)

> Automatic semantic extraction, behavioral modeling, data-flow analysis, guard/precondition detection, side-effect classification, domain action tagging, semantic-aware policy rules, semantic queries, and intent reinforcement via `semantics.py`.

**Principle:** Graph_0 captures **structure** (what exists). Graph_1 captures **intent** (what humans say it does). Graph_2 captures **behavior** (what the code actually does). This closes the gap between "who calls whom" and "what the code means" — enabling agents to reason about authentication flows, state mutations, conditional safety guards, I/O side effects, and domain operations without relying solely on human annotations.

**Analogy:** Graph_0 is the **skeleton**. Workflow is the **nervous system**. Graph_2 is the **muscle and organ map** — it tells you what each part *does*, not just where it is and what it's connected to.

---

## Phase 1 — Core Semantic Model

---

### TASK R-001 — Define Graph2Node Data Model

**Description:**
Implement the Graph_2 semantic behavior node data model that captures what a function *does* rather than what it *is*.

**Reasoning:**
Graph_0 tells you a function exists. Graph_1 tells you what a human says it does. Graph_2 tells you what the code **actually does** — its actions, guards, side effects, data flow, and domain operations. This is the foundation of semantic reasoning.

**Implementation Steps:**
1. Create `codegraph/models/graph2.py`
2. Define `Graph2Node` dataclass:
   - `id: str` — must match a Graph_0 node ID
   - `actions: list[SemanticAction]` — what the function does (see R-002)
   - `guards: list[Guard]` — preconditions/conditional checks before actions
   - `side_effects: list[SideEffect]` — external world interactions (see R-003)
   - `data_flow: DataFlowSummary` — inputs consumed, outputs produced (see R-004)
   - `domain_tags: list[str]` — auto-inferred domain categories (e.g., "payment", "auth", "logging")
   - `behavior_hash: str` — hash of the semantic model for change detection
   - `confidence: float` — 0.0-1.0 confidence in the semantic extraction
   - `extracted_at: str` — ISO 8601 timestamp
   - `extractor_version: str` — version of the semantic extractor that produced this
3. Implement `to_dict()` and `from_dict()` serialization
4. Implement `has_side_effects() -> bool`
5. Implement `has_guards() -> bool`
6. Implement `is_pure() -> bool` — no side effects, no state mutations

**Files:**
- `codegraph/models/graph2.py`

**Dependencies:** A-017, B-001

**Edge Cases:**
- Function with no detectable semantics → empty actions, low confidence
- Very complex function → many actions, may exceed reasonable model size
- Module-level code → special handling (no function scope)
- Lambda/closure → limited semantic extraction

**Validation:**
- Serialization round-trip preserves all fields
- `is_pure()` returns True for functions with no side effects
- `has_guards()` correctly identifies conditional preconditions
- `behavior_hash` changes when semantics change

---

### TASK R-002 — Define SemanticAction Data Model

**Description:**
Define the `SemanticAction` type that represents a discrete operation a function performs.

**Reasoning:**
Actions are the atomic units of behavior. A function might "validate input", "query database", "transform data", "send notification". These are distinct from call targets — they capture *what is being done*, not *who is doing it*.

**Implementation Steps:**
1. Define `SemanticAction` dataclass in `codegraph/models/graph2.py`:
   - `action_type: str` — category from `ActionType` enum (see R-005)
   - `description: str` — human-readable description of what happens
   - `target_node: Optional[str]` — the called node performing this action (if applicable)
   - `arguments_consumed: list[str]` — parameter names used in this action
   - `order: int` — relative order within the function (1, 2, 3...)
   - `conditional: bool` — True if inside an if/try/match block
   - `condition_description: Optional[str]` — what the guard condition is (if conditional)
2. Implement `to_dict()` and `from_dict()`

**Files:**
- `codegraph/models/graph2.py` (modify)

**Dependencies:** R-001

**Edge Cases:**
- Action inside deeply nested conditions → `conditional: True` with outermost condition
- Action in loop → note repetition in description
- Action with exception handling → capture both success and error paths

**Validation:**
- Actions serialize/deserialize correctly
- Order matches source code order
- Conditional flag accurate

---

### TASK R-003 — Define SideEffect Data Model

**Description:**
Define the `SideEffect` type that classifies how a function interacts with the external world.

**Reasoning:**
Side effects are the most dangerous aspect of code for autonomous agents. A function that writes to a database, sends an HTTP request, or modifies a file has consequences beyond the call graph. Agents must know about these before proposing changes.

**Implementation Steps:**
1. Define `SideEffect` dataclass in `codegraph/models/graph2.py`:
   - `effect_type: str` — from `SideEffectType` enum (see R-006)
   - `target: str` — what is affected (e.g., "database.users", "filesystem./tmp/data", "network.api.stripe.com")
   - `operation: str` — read, write, delete, create, send, receive
   - `reversible: bool` — can this be undone? (delete = no, write = maybe)
   - `confidence: float` — how sure we are this is a real side effect
2. Implement `to_dict()` and `from_dict()`
3. Implement `is_destructive() -> bool` — delete, truncate, drop operations

**Files:**
- `codegraph/models/graph2.py` (modify)

**Dependencies:** R-001

**Edge Cases:**
- Indirect side effects (calls function that writes DB) → captured as `confidence: lower`
- Side effects inside try/except → still a side effect
- Mock/test side effects → should be annotated differently (Layer 4)

**Validation:**
- Destructive operations detected
- Reversibility classified
- Confidence reflects detection method

---

### TASK R-004 — Define DataFlowSummary Data Model

**Description:**
Define the `DataFlowSummary` that captures what data a function consumes, transforms, and produces.

**Reasoning:**
Data flow answers "what goes in and what comes out". This enables agents to understand function contracts beyond type signatures — e.g., "consumes user credentials, produces authentication token" vs "consumes user object, produces user object" (passthrough).

**Implementation Steps:**
1. Define `DataFlowSummary` dataclass in `codegraph/models/graph2.py`:
   - `inputs: list[DataFlowItem]` — parameters and external data consumed
   - `outputs: list[DataFlowItem]` — return values and external data produced
   - `transforms: list[str]` — descriptions of data transformations
   - `state_mutations: list[str]` — instance/class/global state modified
   - `is_passthrough: bool` — function mostly passes data through unchanged
2. Define `DataFlowItem`:
   - `name: str` — parameter name or description
   - `data_category: str` — "credentials", "financial", "pii", "config", "generic"
   - `source: str` — "parameter", "database", "network", "filesystem", "environment"
3. Implement `to_dict()` and `from_dict()`

**Files:**
- `codegraph/models/graph2.py` (modify)

**Dependencies:** R-001

**Edge Cases:**
- Function with `*args, **kwargs` → limited data flow inference
- Generator/async generator → yield-based data flow
- Global state mutation → captured in `state_mutations`

**Validation:**
- Inputs match function parameters
- Outputs match return statements
- Passthrough detection works

---

### TASK R-005 — Define ActionType Enum

**Description:**
Define the enumeration of semantic action categories that functions can perform.

**Reasoning:**
A controlled vocabulary for actions enables consistent classification, querying, and policy enforcement. Too many categories = noise; too few = useless. This enum targets the sweet spot.

**Implementation Steps:**
1. Define `ActionType` enum in `codegraph/models/graph2.py`:
   - `VALIDATE` — input validation, schema checking, type assertion
   - `AUTHENTICATE` — identity verification, token validation, credential check
   - `AUTHORIZE` — permission checking, role-based access control
   - `QUERY` — data retrieval (database, API, cache, filesystem read)
   - `MUTATE` — data modification (database write, file write, state change)
   - `TRANSFORM` — data conversion, mapping, serialization, formatting
   - `SEND` — outbound communication (HTTP, email, message queue, webhook)
   - `RECEIVE` — inbound data acceptance (listener, webhook handler, queue consumer)
   - `LOG` — logging, audit trail, metrics recording
   - `CONFIGURE` — system setup, initialization, environment configuration
   - `ORCHESTRATE` — coordination of multiple sub-operations (controller/manager)
   - `GUARD` — precondition check that gates subsequent operations
   - `HANDLE_ERROR` — exception handling, recovery, fallback
   - `CACHE` — caching operations (get, set, invalidate)
   - `DISPATCH` — dynamic routing, event dispatch, plugin invocation
   - `COMPUTE` — pure computation with no side effects
   - `UNKNOWN` — could not classify
2. Add `has_external_effect() -> bool` property
3. Add `is_security_relevant() -> bool` property (AUTHENTICATE, AUTHORIZE, GUARD)

**Files:**
- `codegraph/models/graph2.py` (modify)

**Dependencies:** R-001

**Validation:**
- All action types have clear definitions
- `has_external_effect()` correct for each type
- `is_security_relevant()` flags auth/authz/guard operations

---

### TASK R-006 — Define SideEffectType Enum

**Description:**
Define the enumeration of side effect categories.

**Reasoning:**
Side effects must be classified for policy enforcement. "Writes to database" is fundamentally different from "writes to log file".

**Implementation Steps:**
1. Define `SideEffectType` enum in `codegraph/models/graph2.py`:
   - `DATABASE_READ` — SQL SELECT, ORM query, key-value get
   - `DATABASE_WRITE` — SQL INSERT/UPDATE/DELETE, ORM save
   - `DATABASE_SCHEMA` — DDL operations (CREATE TABLE, migrations)
   - `FILESYSTEM_READ` — file open for reading, path operations
   - `FILESYSTEM_WRITE` — file open for writing, file creation
   - `NETWORK_REQUEST` — HTTP/gRPC/TCP outbound call
   - `NETWORK_LISTEN` — socket bind, server start
   - `ENVIRONMENT` — env var read/write, system call
   - `PROCESS` — subprocess spawn, os.exec
   - `LOGGING` — structured/unstructured log output
   - `CACHE_OP` — cache get/set/invalidate (Redis, memcached, in-memory)
   - `MESSAGE_QUEUE` — publish/subscribe to message broker
   - `STATE_MUTATION` — modification of global/class/instance state
   - `NONE` — pure function, no side effects
2. Add `risk_level() -> int` property (0=none, 1=low, 2=medium, 3=high)
3. Add `is_external() -> bool` — True for DB, network, filesystem, process

**Files:**
- `codegraph/models/graph2.py` (modify)

**Dependencies:** R-001

**Validation:**
- Risk levels correctly assigned
- `is_external()` flags non-local effects

---

### TASK R-007 — Define Graph2 Collection Model

**Description:**
Implement the `Graph2` collection that manages all semantic behavior nodes, analogous to Graph_0 and Graph_1 collections.

**Reasoning:**
The collection wraps all Graph_2 nodes with metadata, supports CRUD operations, and handles persistence to `.codegraph/graph2.json`.

**Implementation Steps:**
1. Define `Graph2` dataclass in `codegraph/models/graph2.py`:
   - `format_version: int = 1`
   - `extracted_at: str` — ISO 8601
   - `extractor_version: str`
   - `nodes: list[Graph2Node]`
   - `coverage: float` — percentage of Graph_0 nodes with semantic models
2. Implement `to_json()` and `from_json()` for `.codegraph/graph2.json`
3. Implement `get_node(node_id) -> Optional[Graph2Node]`
4. Implement `upsert_node(node: Graph2Node)`
5. Implement `get_nodes_with_effect(effect_type: SideEffectType) -> list[str]`
6. Implement `get_nodes_by_action(action_type: ActionType) -> list[str]`
7. Implement `get_nodes_by_domain(tag: str) -> list[str]`
8. Build internal lookup dict on load for O(1) access

**Files:**
- `codegraph/models/graph2.py` (modify)

**Dependencies:** R-001, R-005, R-006

**Edge Cases:**
- Graph_2 doesn't exist yet (first semantic analysis) → empty collection
- Node in Graph_2 but not in Graph_0 → stale, mark for removal
- Very large collection (10k+ nodes) → dict-based lookup

**Validation:**
- CRUD operations work correctly
- Queries by effect/action/domain return correct nodes
- Coverage percentage calculated accurately
- O(1) node lookup

---

## Phase 2 — Semantic Extraction Engine

---

### TASK R-008 — Implement Semantic Extractor Core

**Description:**
Create the main semantic extraction engine that analyzes function ASTs and produces Graph_2 nodes.

**Reasoning:**
This is the heart of the semantic layer. It takes a function's AST + call graph context and infers what the function *does* — its actions, guards, side effects, and data flow. It uses pattern matching, heuristics, and call target analysis rather than LLM inference (deterministic first, AI-assist later).

**Implementation Steps:**
1. Create `codegraph/semantics.py`
2. Implement `extract_semantics(node_id: str, ast_node: ast.AST, graph0: Graph0, workflow: Workflow) -> Graph2Node`
3. Pipeline:
   a. Extract actions from call sites (R-009)
   b. Detect guards/preconditions (R-010)
   c. Classify side effects (R-011)
   d. Analyze data flow (R-012)
   e. Infer domain tags (R-013)
   f. Compute behavior_hash
   g. Assign confidence score
4. Return fully populated Graph2Node

**Files:**
- `codegraph/semantics.py`

**Dependencies:** R-001 through R-007, C-001, B-006

**Edge Cases:**
- Function too complex to analyze → low confidence, partial model
- Built-in function calls → classify by known patterns
- Decorator-wrapped functions → analyze inner function
- Property getters/setters → simplified model

**Validation:**
- Simple function produces reasonable semantic model
- Complex function has lower confidence than simple one
- Known patterns (DB write, HTTP call) correctly classified

---

### TASK R-009 — Implement Action Extraction from Call Sites

**Description:**
Analyze a function's call sites to determine what actions it performs. Map each call to a `SemanticAction` based on the callee's known behavior or name patterns.

**Reasoning:**
The primary signal for actions is "what does this function call?" A call to `db.execute(INSERT...)` is a MUTATE action. A call to `requests.get()` is a QUERY+NETWORK action. A call to `validate_token()` is an AUTHENTICATE action. Pattern matching on call targets provides high-confidence classifications.

**Implementation Steps:**
1. Implement `extract_actions(ast_node, call_sites, graph0, workflow) -> list[SemanticAction]` in `codegraph/semantics.py`
2. For each call site in the function:
   a. Resolve call target to a node ID (from C-017 call site extraction)
   b. Check if target has existing Graph_2 entry → use its primary action type
   c. If no Graph_2 entry → classify by name pattern matching (R-014)
   d. If inside conditional → mark `conditional: True`
   e. Track argument usage for `arguments_consumed`
3. Order actions by their position in source code
4. Assign confidence based on classification method (known=1.0, pattern=0.8, guess=0.5)

**Files:**
- `codegraph/semantics.py` (modify)

**Dependencies:** R-008, R-005, C-017

**Edge Cases:**
- Call to unresolved dynamic target → action_type=DISPATCH, lower confidence
- Call inside try/except → still an action (may fail)
- Chained calls `a().b().c()` → each is a separate action
- Self-recursion → action_type=ORCHESTRATE with recursive note

**Validation:**
- Known DB call → MUTATE or QUERY
- Known HTTP call → SEND or QUERY
- Unknown call → reasonable default with lower confidence

---

### TASK R-010 — Implement Guard/Precondition Detection

**Description:**
Detect conditional checks that gate subsequent operations — authentication checks, permission checks, validation, null checks, and business rule guards.

**Reasoning:**
Guards are critically important for safety reasoning. If `fraud_check()` is a guard before `charge_card()`, an agent must know that removing or reordering them breaks a safety invariant. Guard detection enables semantic policy rules like "payment operations must have a fraud guard".

**Implementation Steps:**
1. Implement `detect_guards(ast_node, call_sites) -> list[Guard]` in `codegraph/semantics.py`
2. Define `Guard` dataclass:
   - `guard_type: str` — "authentication", "authorization", "validation", "null_check", "business_rule", "rate_limit", "feature_flag"
   - `condition: str` — human-readable description of the check
   - `gated_actions: list[int]` — indices of actions that depend on this guard
   - `is_early_return: bool` — guard returns/raises on failure
   - `source_line: int`
3. Detection patterns:
   a. `if not condition: raise/return` → early-return guard
   b. `if check_auth(...): <body>` → auth guard
   c. `if x is None: raise` → null check guard
   d. `assert condition` → assertion guard
4. Map guard to the actions it protects (everything after the guard or inside its body)

**Files:**
- `codegraph/semantics.py` (modify)

**Dependencies:** R-008

**Edge Cases:**
- Multiple guards in sequence → each captured separately
- Guard in else branch → inverted condition
- Try/except as guard pattern → classify exception type
- Guard with complex boolean condition → description from source

**Validation:**
- `if not user.is_authenticated: return 403` → auth guard detected
- `validate_input(data)` at top of function → validation guard
- Non-guard conditions (business logic) → not classified as guards

---

### TASK R-011 — Implement Side Effect Classification

**Description:**
Classify all side effects a function produces by analyzing its call targets, argument patterns, and AST context.

**Reasoning:**
Side effects determine the real-world impact of code changes. An agent considering removing a function must know whether it writes to a database, sends emails, or merely computes a value. This classification makes those consequences visible.

**Implementation Steps:**
1. Implement `classify_side_effects(ast_node, call_sites, graph0) -> list[SideEffect]` in `codegraph/semantics.py`
2. Detection strategies:
   a. **Known library patterns**: `requests.post()` → NETWORK_REQUEST, `cursor.execute("INSERT")` → DATABASE_WRITE
   b. **Standard library patterns**: `open(f, 'w')` → FILESYSTEM_WRITE, `subprocess.run()` → PROCESS
   c. **ORM patterns**: `.save()`, `.delete()`, `.create()` → DATABASE_WRITE
   d. **State mutation**: `self.x = ...` → STATE_MUTATION
   e. **Logging**: `logger.info()`, `print()` → LOGGING
   f. **Transitive effects**: function calls another function with known side effects → inherit with lower confidence
3. Use known-library database (R-015) for pattern matching
4. Set confidence: direct detection = 1.0, transitive = 0.7, heuristic = 0.5

**Files:**
- `codegraph/semantics.py` (modify)

**Dependencies:** R-008, R-006, R-015

**Edge Cases:**
- Dynamic method calls → can't classify, mark as UNKNOWN
- Side effects in exception handlers → still count
- Mocked side effects in tests → classify but annotate as test context
- Context managers (`with open(...)`) → detect entry/exit effects

**Validation:**
- `cursor.execute("INSERT INTO...")` → DATABASE_WRITE
- `requests.post(url, data)` → NETWORK_REQUEST
- `self.balance = new_amount` → STATE_MUTATION
- Pure math function → NONE

---

### TASK R-012 — Implement Data Flow Analysis

**Description:**
Analyze function parameters, return values, and intermediate data transformations to build a data flow summary.

**Reasoning:**
Data flow tells agents what a function consumes and produces. This enables reasoning about data contracts: "If I change the return type of function A, which downstream functions will break?" It also enables sensitive data tracking (PII, credentials, financial data).

**Implementation Steps:**
1. Implement `analyze_data_flow(ast_node, type_hints) -> DataFlowSummary` in `codegraph/semantics.py`
2. Input analysis:
   a. Extract parameters with type annotations
   b. Classify by data category using name heuristics ("user", "password", "amount", "token" → infer category)
   c. Track which parameters are used in which calls
3. Output analysis:
   a. Find all return statements
   b. Infer return type from annotations or returned value
   c. Classify output data category
4. Transform analysis:
   a. Identify mapping/conversion patterns (dict comprehension, list map, serialization)
   b. Generate descriptions like "converts User to dict" or "filters list by predicate"
5. State mutation:
   a. Track `self.x = ...` assignments
   b. Track global variable writes
   c. Track mutable argument modifications

**Files:**
- `codegraph/semantics.py` (modify)

**Dependencies:** R-008, R-004

**Edge Cases:**
- No type annotations → rely on name heuristics, lower confidence
- `*args, **kwargs` → limited analysis, note in summary
- Multiple return paths with different types → capture all
- Generator functions → yield-based flow

**Validation:**
- `def process(user: User, amount: float) -> Receipt` → inputs=[user:pii, amount:financial], outputs=[Receipt:generic]
- Passthrough function → `is_passthrough: True`
- State-mutating function → `state_mutations` populated

---

### TASK R-013 — Implement Domain Tag Inference

**Description:**
Automatically infer domain tags for functions based on their actions, side effects, call targets, file location, and naming patterns.

**Reasoning:**
Domain tags like "payment", "auth", "notification", "analytics" enable high-level queries ("show me all payment functions") and domain-scoped policies. Auto-inference reduces the annotation burden that currently falls entirely on Graph_1 intents.

**Implementation Steps:**
1. Implement `infer_domain_tags(node_id, actions, side_effects, graph0) -> list[str]` in `codegraph/semantics.py`
2. Inference signals:
   a. **File path**: `src/payment/` → "payment" tag, `src/auth/` → "auth" tag
   b. **Function name**: `validate_token` → "auth", `send_email` → "notification"
   c. **Action types**: AUTHENTICATE → "auth", MUTATE + DATABASE → "persistence"
   d. **Call targets**: calls Stripe API → "payment", calls SMTP → "email"
   e. **Graph_1 intent keywords**: if intent mentions "payment" → "payment" tag
3. Combine signals with confidence scoring — tag assigned only if confidence > threshold
4. Standard tag vocabulary: auth, payment, persistence, notification, analytics, logging, config, api, validation, scheduling, caching, security

**Files:**
- `codegraph/semantics.py` (modify)

**Dependencies:** R-008, R-005

**Edge Cases:**
- Generic utility functions → may get no domain tags (that's fine)
- Function in `auth/` that's actually a helper → file path signal outweighed by content
- Multiple domains → function can have multiple tags

**Validation:**
- Payment processing function → "payment" tag
- Auth handler → "auth" tag
- Generic sort function → no domain tags or "utility"
- Tags are consistent across builds (deterministic)

---

### TASK R-014 — Implement Function Name Pattern Classifier

**Description:**
Build a pattern-matching classifier that maps function/method names to likely action types using naming conventions.

**Reasoning:**
Python naming conventions carry strong semantic signal. `validate_*` is likely VALIDATE, `get_*` is likely QUERY, `create_*` is likely MUTATE, `send_*` is likely SEND. A pattern database enables high-confidence classification without deep analysis.

**Implementation Steps:**
1. Implement `classify_by_name(function_name: str) -> tuple[ActionType, float]` in `codegraph/semantics.py`
2. Pattern rules (prefix/suffix matching):
   - `validate_*`, `check_*`, `verify_*`, `is_*`, `has_*` → VALIDATE (0.8)
   - `authenticate_*`, `login_*`, `auth_*` → AUTHENTICATE (0.85)
   - `authorize_*`, `permit_*`, `can_*`, `allow_*` → AUTHORIZE (0.85)
   - `get_*`, `fetch_*`, `load_*`, `find_*`, `search_*`, `query_*` → QUERY (0.7)
   - `create_*`, `save_*`, `update_*`, `delete_*`, `remove_*`, `insert_*` → MUTATE (0.75)
   - `transform_*`, `convert_*`, `parse_*`, `format_*`, `serialize_*`, `map_*` → TRANSFORM (0.7)
   - `send_*`, `notify_*`, `publish_*`, `emit_*`, `dispatch_*` → SEND (0.75)
   - `handle_*`, `on_*`, `process_*` → ORCHESTRATE (0.6)
   - `log_*`, `record_*`, `track_*` → LOG (0.8)
   - `init_*`, `setup_*`, `configure_*`, `bootstrap_*` → CONFIGURE (0.75)
   - `compute_*`, `calculate_*`, `sum_*`, `avg_*` → COMPUTE (0.7)
3. Support both prefix and contains matching
4. Return (UNKNOWN, 0.0) for no match
5. Make pattern database configurable

**Files:**
- `codegraph/semantics.py` (modify)

**Dependencies:** R-005

**Edge Cases:**
- Ambiguous names like `process_data` → ORCHESTRATE with lower confidence
- Names with multiple signals `validate_and_save` → return highest confidence match
- Dunder methods → skip classification
- Single-letter names → UNKNOWN

**Validation:**
- `validate_input` → VALIDATE, 0.8
- `send_notification` → SEND, 0.75
- `xyz` → UNKNOWN, 0.0
- Pattern DB is configurable

---

### TASK R-015 — Build Known Library Side Effect Database

**Description:**
Create a curated database mapping well-known Python library functions/methods to their side effect types and action categories.

**Reasoning:**
The semantic extractor needs to know that `requests.post()` is a network write, `cursor.execute()` is a database operation, and `os.remove()` is a filesystem delete. A curated database provides high-confidence classification for common libraries.

**Implementation Steps:**
1. Create `codegraph/known_libraries.py`
2. Define database as dict mapping `module.function` patterns to side effect classifications:
   ```python
   KNOWN_EFFECTS = {
       # Network
       "requests.get": (SideEffectType.NETWORK_REQUEST, "read"),
       "requests.post": (SideEffectType.NETWORK_REQUEST, "write"),
       "httpx.Client.get": (SideEffectType.NETWORK_REQUEST, "read"),
       "aiohttp.ClientSession.post": (SideEffectType.NETWORK_REQUEST, "write"),
       # Database
       "sqlite3.Cursor.execute": (SideEffectType.DATABASE_WRITE, "execute"),
       "sqlalchemy.Session.commit": (SideEffectType.DATABASE_WRITE, "commit"),
       "psycopg2.cursor.execute": (SideEffectType.DATABASE_WRITE, "execute"),
       # ORM patterns
       "*.save": (SideEffectType.DATABASE_WRITE, "save"),
       "*.delete": (SideEffectType.DATABASE_WRITE, "delete"),
       # Filesystem
       "builtins.open": (SideEffectType.FILESYSTEM_READ, "open"),  # mode-dependent
       "pathlib.Path.write_text": (SideEffectType.FILESYSTEM_WRITE, "write"),
       "os.remove": (SideEffectType.FILESYSTEM_WRITE, "delete"),
       "shutil.rmtree": (SideEffectType.FILESYSTEM_WRITE, "delete"),
       # Process
       "subprocess.run": (SideEffectType.PROCESS, "execute"),
       "os.system": (SideEffectType.PROCESS, "execute"),
       # Logging
       "logging.Logger.*": (SideEffectType.LOGGING, "log"),
       "builtins.print": (SideEffectType.LOGGING, "print"),
       # Cache
       "redis.Redis.set": (SideEffectType.CACHE_OP, "write"),
       "redis.Redis.get": (SideEffectType.CACHE_OP, "read"),
       # Message Queue
       "pika.channel.basic_publish": (SideEffectType.MESSAGE_QUEUE, "publish"),
       "celery.app.task.apply_async": (SideEffectType.MESSAGE_QUEUE, "dispatch"),
   }
   ```
3. Support glob patterns (`*.save`) for method-level matching
4. Support file mode detection for `open()` → read vs write
5. Make extensible via config: `config.yaml.known_effects`

**Files:**
- `codegraph/known_libraries.py`

**Dependencies:** R-006

**Edge Cases:**
- Library not in database → fall back to name pattern matching
- Custom ORM `.save()` method → glob pattern catches it, lower confidence
- Version-specific API changes → document which versions are covered
- Indirect calls through wrappers → detected transitively with lower confidence

**Validation:**
- `requests.post()` correctly classified as NETWORK_REQUEST
- `cursor.execute("SELECT")` classified as DATABASE_READ (SQL parsing bonus)
- Unknown library function → no classification (graceful degradation)
- Config extension adds custom entries

---

### TASK R-016 — Implement SQL Statement Classifier

**Description:**
Parse SQL strings in code to distinguish between read queries (SELECT) and write operations (INSERT, UPDATE, DELETE, DDL).

**Reasoning:**
A `cursor.execute()` call could be a read or write — the SQL string determines which. Parsing the SQL argument provides precise side-effect classification for all database interactions.

**Implementation Steps:**
1. Implement `classify_sql(sql_string: str) -> tuple[SideEffectType, str]` in `codegraph/semantics.py`
2. Extract SQL strings from AST (string literals, f-strings, concatenations)
3. Classify:
   - Starts with `SELECT`, `SHOW`, `DESCRIBE`, `EXPLAIN` → DATABASE_READ
   - Starts with `INSERT`, `UPDATE`, `DELETE`, `REPLACE` → DATABASE_WRITE
   - Starts with `CREATE`, `ALTER`, `DROP`, `TRUNCATE` → DATABASE_SCHEMA
   - Contains parameters `%s` or `?` → classify by initial keyword
4. Handle multi-statement strings → classify by most dangerous operation
5. Handle ORM query builders (`.filter().all()` = read, `.filter().update()` = write)

**Files:**
- `codegraph/semantics.py` (modify)

**Dependencies:** R-015

**Edge Cases:**
- Dynamic SQL (variable, not string literal) → can't classify, mark UNKNOWN
- Multi-line SQL → normalize whitespace before classification
- Stored procedure calls (CALL/EXEC) → classify as DATABASE_WRITE (conservative)
- SQL in f-strings → extract keyword from template

**Validation:**
- `"SELECT * FROM users"` → DATABASE_READ
- `"INSERT INTO orders VALUES ..."` → DATABASE_WRITE
- `"DROP TABLE users"` → DATABASE_SCHEMA
- Dynamic variable → UNKNOWN

---

## Phase 3 — Full Graph Build Integration

---

### TASK R-017 — Implement Full Semantic Extraction Orchestrator

**Description:**
Implement the top-level function that runs semantic extraction for all nodes in Graph_0 and produces the complete Graph_2.

**Reasoning:**
During `codegraph build`, after Graph_0 and workflow are constructed, a semantic extraction pass produces Graph_2. This orchestrates the per-node extraction and handles errors gracefully.

**Implementation Steps:**
1. Implement `build_graph2(graph0: Graph0, graph1: Graph1, workflow: Workflow, project_root) -> Graph2` in `codegraph/semantics.py`
2. Steps:
   a. For each function/method node in Graph_0:
      - Load its AST from parsed source
      - Extract semantics (R-008)
      - Add to Graph_2
   b. Handle extraction failures: log warning, skip node, continue
   c. Compute coverage: nodes_with_semantics / total_nodes
   d. Reinforce Graph_1 intents where possible (R-022)
3. Log: "Extracted semantics for N of M nodes (X% coverage) in Y.Ys"
4. Save to `.codegraph/graph2.json`

**Files:**
- `codegraph/semantics.py` (modify)

**Dependencies:** R-008, R-001 through R-007, C-001

**Edge Cases:**
- Node's source file has syntax errors → skip with warning
- Very large codebase (10k+ nodes) → show progress, target < 30s
- Some nodes produce empty semantics → valid, low coverage
- Extraction crash on single node → catch, log, continue

**Validation:**
- All parseable function nodes analyzed
- Coverage percentage reported
- Graph_2 saved to correct location
- Individual node failure doesn't crash entire extraction

---

### TASK R-018 — Implement Incremental Semantic Extraction (Delta-Aware)

**Description:**
During delta, only re-extract semantics for nodes whose body_hash or dependency_hash changed, reusing cached Graph_2 entries for unchanged nodes.

**Reasoning:**
Full semantic extraction is expensive. During delta, only changed nodes need re-analysis. CAS integration (Group Q) identifies the affected set; semantic extraction is scoped to that set only.

**Implementation Steps:**
1. Implement `update_graph2_delta(affected_nodes: set[str], graph0, graph1, workflow, graph2, project_root) -> Graph2` in `codegraph/semantics.py`
2. For nodes in affected_set:
   a. Re-extract semantics
   b. Compare new behavior_hash with old
   c. If behavior changed → update Graph_2 entry
   d. If behavior unchanged (code changed but semantics same) → keep old entry, update timestamp
3. For nodes NOT in affected_set: keep existing Graph_2 entries
4. Remove Graph_2 entries for deleted nodes
5. Add Graph_2 entries for new nodes
6. Log: "Updated semantics for N of M affected nodes (K with changed behavior)"

**Files:**
- `codegraph/semantics.py` (modify)

**Dependencies:** R-017, Q-007, K-001

**Edge Cases:**
- CAS not available → fall back to file-level change detection
- New node without previous Graph_2 entry → full extraction
- Behavior hash unchanged despite code change → semantics stable, no update needed
- Very large affected set → show progress

**Validation:**
- Only affected nodes re-extracted
- Unchanged nodes preserve old Graph_2 entries
- behavior_hash change detection works
- Compatible with CAS pipeline

---

### TASK R-019 — Implement Behavior Hash Computation

**Description:**
Compute the `behavior_hash` for a Graph_2 node — a content hash of its semantic model for change detection.

**Reasoning:**
`body_hash` detects code changes. `behavior_hash` detects *semantic* changes. If code changes but the semantic model stays the same (e.g., variable rename), behavior is stable. If actions/guards/effects change, behavior changed even if it's a small edit.

**Implementation Steps:**
1. Implement `compute_behavior_hash(node: Graph2Node) -> str` in `codegraph/semantics.py`
2. Hash components (deterministic):
   - Sorted action types and targets
   - Sorted guard types
   - Sorted side effect types and targets
   - Data flow signature (input categories → output categories)
3. Exclude: confidence, timestamps, order (only the *what*, not the *how certain*)
4. Use SHA256 for consistency with body_hash and dependency_hash

**Files:**
- `codegraph/semantics.py` (modify)

**Dependencies:** R-001

**Edge Cases:**
- Empty semantics → hash of empty model (stable)
- Reordering actions → hash unchanged (sorted)
- New guard added → hash changes
- Confidence changed but actions same → hash unchanged

**Validation:**
- Same semantic model always produces same hash
- Different actions produce different hashes
- Confidence changes don't affect hash
- Deterministic across runs

---

### TASK R-020 — Integrate Semantic Extraction into `codegraph build` Pipeline

**Description:**
Add the semantic extraction step to the `codegraph build` command, producing Graph_2 alongside Graph_0, Graph_1, and workflow.

**Reasoning:**
Graph_2 must be built as part of the standard build pipeline. It runs after workflow (needs call graph) and before index (index should include semantic data).

**Implementation Steps:**
1. Add Graph_2 step to `codegraph build` command (N-002):
   a. After workflow build
   b. Before index build
   c. Call `build_graph2()` (R-017)
   d. Pass Graph_2 to index builder for semantic index tables
2. Add `--skip-semantics` flag to bypass semantic extraction (faster builds)
3. Display in build summary:
   ```
   Semantic Analysis:
     Nodes analyzed:    847 / 1,023
     Coverage:          82.8%
     Side effects:      312 nodes with external effects
     Guards detected:   156 precondition checks
     Domain tags:       payment(45), auth(38), persistence(89), ...
   ```

**Files:**
- `codegraph/cli.py` (modify)

**Dependencies:** R-017, N-002

**Edge Cases:**
- `--skip-semantics` → no Graph_2 built, downstream features degraded
- Semantic extraction failure → build continues, Graph_2 partial/empty
- Pre-existing Graph_2 from previous build → overwritten

**Validation:**
- Build includes semantic analysis step
- Summary shows semantic statistics
- `--skip-semantics` flag works
- Build completes even if semantics fail

---

### TASK R-021 — Integrate Semantic Extraction into Delta Pipeline

**Description:**
Add incremental semantic extraction to the delta pipeline, updating Graph_2 for affected nodes.

**Reasoning:**
During `codegraph delta`, Graph_2 must be updated for changed nodes so semantic data stays current.

**Implementation Steps:**
1. Add Graph_2 update step to `run_delta()`:
   a. After Graph_0 merge and workflow recomputation
   b. Call `update_graph2_delta()` (R-018) with affected nodes
   c. Include behavior_hash changes in delta output
2. Add to delta statistics:
   ```
   Semantics:
     Re-analyzed:      12 nodes
     Behavior changed:  5 nodes
     New effects:       2 nodes gained side effects
   ```
3. Skip if Graph_2 doesn't exist yet (suggest running `codegraph build`)

**Files:**
- `codegraph/delta.py` (modify)

**Dependencies:** R-018, K-001

**Edge Cases:**
- No Graph_2 file → skip semantic update, log warning
- CAS narrows affected set → fewer nodes to re-analyze
- Semantic extraction fails for single node → continue with remaining

**Validation:**
- Delta updates Graph_2 for changed nodes
- Unchanged nodes retain old semantics
- Statistics accurate in delta output

---

## Phase 4 — Intent Reinforcement & Cross-Graph Alignment

---

### TASK R-022 — Implement Intent Reinforcement from Semantics

**Description:**
Use Graph_2 semantic analysis to validate, strengthen, or suggest corrections to Graph_1 intent annotations.

**Reasoning:**
Intent annotations in Graph_1 are written by humans or agents and may be wrong, vague, or outdated. Graph_2 provides an independent, code-derived behavioral model. Comparing the two enables automatic validation: "The intent says 'helper function' but the code performs authentication and database writes."

**Implementation Steps:**
1. Implement `reinforce_intents(graph1: Graph1, graph2: Graph2) -> IntentReinforcementReport` in `codegraph/semantics.py`
2. For each node with both Graph_1 intent and Graph_2 semantics:
   a. **Validation**: Does the intent mention the primary action? (e.g., intent says "process payment", Graph_2 shows MUTATE+SEND actions)
   b. **Contradiction**: Does the intent conflict with semantics? (e.g., intent says "read-only query", Graph_2 shows DATABASE_WRITE)
   c. **Enrichment**: Can the intent be improved? (e.g., intent is vague "helper", Graph_2 shows specific VALIDATE+QUERY actions)
   d. **Suggestion**: Generate improved intent text from semantic model
3. Return report with: validated, contradicted, enriched, suggested intents
4. **Never auto-modify Graph_1** — only suggest, let agent/human decide

**Files:**
- `codegraph/semantics.py` (modify)

**Dependencies:** R-017, E-001, B-016

**Edge Cases:**
- No Graph_1 intent → skip validation, use Graph_2 to suggest one
- Very vague intent → enrichment suggested
- Intent and semantics fully aligned → validated, high confidence
- Complex function with many actions → intent may correctly summarize at high level

**Validation:**
- "helper function" intent on auth function → contradiction flagged
- "validate and process payment" on payment function → validated
- Missing intent on DB-writing function → suggestion generated
- No auto-modification of Graph_1

---

### TASK R-023 — Implement Semantic-Aware Orphan Classification

**Description:**
Enhance orphan detection (I-002) with semantic analysis to better classify orphan nodes by their behavioral role.

**Reasoning:**
Current orphan classification uses structural heuristics (name patterns, `__main__`). Semantic analysis can detect: "This orphan has DISPATCH actions — it's likely an event handler. This orphan performs AUTHENTICATE — it's likely a middleware hook, not dead code."

**Implementation Steps:**
1. Implement `classify_orphan_semantic(node_id, graph2, graph0) -> str` in `codegraph/semantics.py`
2. Enhanced classifications:
   - `event_handler`: has DISPATCH or RECEIVE actions → probably registered dynamically
   - `middleware`: has AUTHENTICATE or AUTHORIZE actions with early-return guard → probably middleware
   - `plugin_hook`: has CONFIGURE actions, no callers → probably a plugin entry point
   - `callback`: has single action, simple signature → probably a callback
   - `test_helper`: Layer 4, has no assertions → test utility
   - `dead_code`: no meaningful actions, no callers, no tests → safe to remove
   - `scheduled_task`: has ORCHESTRATE actions, no direct callers → probably cron/scheduler
3. Confidence scoring based on semantic evidence strength
4. Feed enhanced classification into task generation for smarter agent context

**Files:**
- `codegraph/semantics.py` (modify)

**Dependencies:** R-017, I-002

**Edge Cases:**
- No Graph_2 entry for orphan → fall back to structural classification
- Multiple possible classifications → return highest confidence
- Dead code with side effects → flag as "dangerous dead code"

**Validation:**
- Event handler orphan classified correctly (not as dead code)
- Middleware orphan recognized
- True dead code still classified as dead
- Safer than structural-only classification

---

### TASK R-024 — Implement Behavior Change Detection for Stale Intent Flagging

**Description:**
Enhance stale intent detection to distinguish between code changes that affect behavior and cosmetic changes, using `behavior_hash`.

**Reasoning:**
Current stale detection (K-007, I-003) flags intents whenever `body_hash` changes. But a variable rename or comment edit doesn't change behavior — the intent is still valid. Using `behavior_hash` from Graph_2, stale detection becomes more precise: only flag intents when the *semantic model* changes.

**Implementation Steps:**
1. Implement `detect_semantic_stale(graph1, graph2, old_graph2) -> list[SemanticStaleIntent]` in `codegraph/semantics.py`
2. For each node with intent:
   a. If `behavior_hash` unchanged → intent is NOT semantically stale (even if body_hash changed)
   b. If `behavior_hash` changed → intent is semantically stale, report what changed:
      - New actions added
      - Actions removed
      - Guards changed
      - Side effects changed
      - Data flow changed
3. Return structured report with severity:
   - `HIGH`: side effects changed (destructive change)
   - `MEDIUM`: guards changed (safety-relevant change)
   - `LOW`: actions reordered or new non-critical actions added

**Files:**
- `codegraph/semantics.py` (modify)

**Dependencies:** R-019, R-017, I-003, K-007

**Edge Cases:**
- behavior_hash unchanged but body_hash changed → NOT stale (cosmetic change)
- New side effect added → HIGH severity stale
- Guard removed → HIGH severity stale
- Action reordered → LOW or no stale

**Validation:**
- Variable rename → NOT flagged as stale
- New DB write added → flagged as HIGH
- Guard removed → flagged as HIGH
- Comment change → NOT flagged

---

## Phase 5 — Semantic Policy & Queries

---

### TASK R-025 — Implement Semantic Policy Rule Types

**Description:**
Extend the suggested workflow system (Group H) with new semantic-aware rule types that enforce behavioral constraints, not just call-graph constraints.

**Reasoning:**
Current rules: "A must call B" or "A must not call B" — purely structural. Semantic rules: "functions that perform MUTATE must have a GUARD" or "payment domain functions must not have NETWORK_REQUEST side effects except through the payment gateway". This is where semantic analysis becomes powerful for architecture enforcement.

**Implementation Steps:**
1. Define new rule types in `codegraph/models/suggested_workflow.py`:
   - `requires_guard`: "functions matching scope that perform action_type must have guard_type"
   - `forbidden_effect`: "functions matching scope must not have side_effect_type"
   - `required_effect`: "functions matching scope must have side_effect_type" (e.g., logging required)
   - `domain_boundary`: "functions in domain_a must not call functions in domain_b directly"
   - `action_sequence`: "action_type_a must precede action_type_b in functions matching scope"
2. Add `semantic_rule: bool` field to rule model to distinguish from structural rules
3. Implement evaluation against Graph_2 data

**Files:**
- `codegraph/models/suggested_workflow.py` (modify)
- `codegraph/suggest.py` (modify)

**Dependencies:** R-007, H-001, H-002, R-005, R-006

**Edge Cases:**
- Rule references action/effect type not in enum → validation error with suggestions
- Scope matches functions without Graph_2 entries → skip rule evaluation, warn
- Semantic rule combined with structural rule → both must pass

**Validation:**
- `requires_guard` catches unguarded mutations
- `forbidden_effect` catches unauthorized DB writes
- `domain_boundary` detects cross-domain violations
- Rules serialize/deserialize correctly

---

### TASK R-026 — Implement Semantic Policy Violation Detector

**Description:**
Evaluate semantic policy rules against Graph_2 data and produce violation reports.

**Reasoning:**
Semantic rules are only useful if violations are detected and reported. This extends the existing policy violation detection (H-010) with Graph_2-powered checks.

**Implementation Steps:**
1. Implement `evaluate_semantic_rules(rules, graph2, graph0, workflow) -> list[SemanticViolation]` in `codegraph/semantics.py`
2. For each semantic rule:
   a. Expand scope to matching node IDs
   b. For each matched node, check Graph_2 entry against rule constraints
   c. If violation found → create SemanticViolation with:
      - rule_id, node_id, violation description
      - what was expected vs what was found
      - suggested fix (e.g., "add fraud_check guard before charge_card")
3. Integrate with existing analyzer (I-001) violation collection

**Files:**
- `codegraph/semantics.py` (modify)

**Dependencies:** R-025, R-007, H-010

**Edge Cases:**
- Node has no Graph_2 entry → skip, cannot evaluate semantic rules
- Rule matches many nodes → batch evaluation
- Violation on node with low semantic confidence → warn but still report

**Validation:**
- Unguarded mutation → violation detected
- Guarded mutation → no violation
- Cross-domain call → boundary violation detected
- Violations integrated into analyzer output

---

### TASK R-027 — Implement Semantic Query Functions

**Description:**
Extend the query system (Group L) with semantic queries: find functions by action type, side effect, guard, domain, or behavioral pattern.

**Reasoning:**
Users and agents need to ask questions like "which functions write to the database?", "which functions perform authentication?", "which payment functions have no fraud guard?". These queries are impossible with structural data alone.

**Implementation Steps:**
1. Add semantic query functions to `codegraph/query.py`:
   - `effects("DATABASE_WRITE")` → all nodes with DATABASE_WRITE side effect
   - `actions("AUTHENTICATE")` → all nodes performing authentication
   - `guards("validation")` → all nodes with validation guards
   - `domain("payment")` → all nodes tagged with payment domain
   - `pure()` → all nodes with no side effects
   - `unguarded("MUTATE")` → nodes with MUTATE action but no guards
   - `risky()` → nodes with high-risk side effects (risk_level >= 3)
2. Support depth parameter: `effects("DATABASE_WRITE", depth=2)` → include transitive callers
3. Format results with semantic context (show actions/effects alongside node IDs)
4. Support `--json` output

**Files:**
- `codegraph/query.py` (modify)

**Dependencies:** R-007, L-001, L-013, G-023

**Edge Cases:**
- No Graph_2 → error: "Run `codegraph build` first (semantic analysis required)"
- Query type not recognized → helpful error with list of semantic query functions
- Very many matching nodes → respect limit parameter

**Validation:**
- `effects("DATABASE_WRITE")` returns all DB-writing functions
- `pure()` returns only side-effect-free functions
- `unguarded("MUTATE")` finds dangerous patterns
- Semantic queries composable with structural queries

---

### TASK R-028 — Implement Semantic Index Tables

**Description:**
Add SQLite index tables for Graph_2 data to enable fast semantic queries: effects index, actions index, domain tags index, guards index.

**Reasoning:**
Semantic queries must be O(1) like structural queries. Without an index, every semantic query requires loading and scanning the entire Graph_2 JSON.

**Implementation Steps:**
1. Add tables to index database:
   - `semantic_actions`: `(node_id TEXT, action_type TEXT, confidence REAL)`
   - `semantic_effects`: `(node_id TEXT, effect_type TEXT, target TEXT, risk_level INTEGER)`
   - `semantic_guards`: `(node_id TEXT, guard_type TEXT)`
   - `semantic_domains`: `(node_id TEXT, domain_tag TEXT)`
   - `semantic_meta`: `(node_id TEXT, behavior_hash TEXT, is_pure INTEGER, confidence REAL)`
2. Add indexes on all type/tag columns
3. Implement `build_semantic_index(graph2: Graph2)` in `codegraph/index.py`
4. Implement delta update: `update_semantic_index(changed_nodes, graph2)`
5. Add query methods to `IndexStore`:
   - `get_nodes_by_effect(effect_type) -> list[str]`
   - `get_nodes_by_action(action_type) -> list[str]`
   - `get_nodes_by_domain(domain) -> list[str]`
   - `get_pure_nodes() -> list[str]`
   - `get_risky_nodes(min_risk=3) -> list[str]`

**Files:**
- `codegraph/index.py` (modify)

**Dependencies:** R-007, G-001, G-007, G-008

**Edge Cases:**
- Graph_2 empty → tables empty (valid)
- Node with multiple effects → multiple rows
- Delta update removes old entries before inserting new
- Migration from pre-semantic index → create tables

**Validation:**
- All semantic query methods return correct nodes
- Index matches Graph_2 data
- Delta update is incremental (not full rebuild)
- Performance: O(1) for type/tag lookups

---

## Phase 6 — Enhanced Dead Code & Safety Analysis

---

### TASK R-029 — Implement Semantic Dead Code Analysis

**Description:**
Enhance dead code detection with semantic analysis to reduce false positives: detect functions that appear dead structurally but have behavioral signals indicating they're active.

**Reasoning:**
Current dead code detection (I-002, B-038) relies on four structural signals. Semantic analysis adds behavioral signals: a function with DISPATCH side effects or RECEIVE actions is likely dynamically invoked even without static callers. This prevents dangerous false-positive deletions.

**Implementation Steps:**
1. Implement `semantic_dead_code_check(node_id, graph2, dead_code_signals) -> DeadCodeVerdict` in `codegraph/semantics.py`
2. Additional survival signals (if any present, NOT dead code):
   a. **DISPATCH/RECEIVE actions** → likely dynamically invoked (callback, event handler)
   b. **CONFIGURE actions** → likely called during initialization (plugin, setup)
   c. **AUTHENTICATE/AUTHORIZE actions** → likely middleware, too dangerous to remove
   d. **High side_effect risk_level** → too dangerous to auto-remove, flag_for_human_review
   e. **Domain tag matches known dynamic patterns** → "api", "webhook", "scheduler"
3. Return verdict:
   - `SAFE_TO_REMOVE`: all structural signals confirm dead + no semantic survival signals
   - `SUSPICIOUS`: structural signals say dead but semantic signals say maybe alive
   - `DANGEROUS`: has high-risk side effects or security actions, must not auto-remove
4. Override agent action: if verdict is DANGEROUS, force `flag_for_human_review` instead of `remove_dead_code`

**Files:**
- `codegraph/semantics.py` (modify)

**Dependencies:** R-017, B-038, I-002

**Edge Cases:**
- No Graph_2 entry → fall back to structural-only analysis
- Function has DISPATCH but is truly dead → SUSPICIOUS (agent decides)
- Function has auth actions but is actually dead → still DANGEROUS (safety first)

**Validation:**
- Event handler without callers → SUSPICIOUS, not SAFE_TO_REMOVE
- True dead utility function → SAFE_TO_REMOVE
- Auth function without callers → DANGEROUS
- Prevents false-positive deletions

---

### TASK R-030 — Implement Safety Impact Assessment for Apply Actions

**Description:**
Before executing any apply action (J-001), assess the semantic safety impact of the change.

**Reasoning:**
The apply system modifies code. Before a `connect_call`, `add_import`, or `remove_dead_code` action, the system should check: "Does this change affect a function with security actions? Does it alter a guard chain? Does it change a function with high-risk side effects?" This adds a semantic safety net.

**Implementation Steps:**
1. Implement `assess_safety(action, graph2) -> SafetyAssessment` in `codegraph/semantics.py`
2. For each apply action:
   a. Look up source and target nodes in Graph_2
   b. Check if either has security-relevant actions (AUTHENTICATE, AUTHORIZE, GUARD)
   c. Check if action adds/removes a guard dependency
   d. Check risk level of side effects involved
3. Return `SafetyAssessment`:
   - `risk: str` — "low", "medium", "high", "critical"
   - `warnings: list[str]` — specific concerns
   - `requires_human_review: bool` — True if risk >= "high"
   - `explanation: str` — why this risk level
4. If `requires_human_review`, override action to `flag_for_human_review`

**Files:**
- `codegraph/semantics.py` (modify)

**Dependencies:** R-017, J-001

**Edge Cases:**
- No Graph_2 entry for node → risk=UNKNOWN, warn
- Removing dead code that has DB_WRITE → HIGH risk, block auto-removal
- Adding import to security module → MEDIUM risk, warn
- Connecting two pure functions → LOW risk, proceed

**Validation:**
- Removing auth function → CRITICAL risk
- Connecting pure functions → LOW risk
- Adding call to DB-writing function → MEDIUM risk
- Human review forced for HIGH/CRITICAL

---

## Phase 7 — Explain & Visualization

---

### TASK R-031 — Enhance `codegraph explain` with Semantic Section

**Description:**
Add a "Behavior" section to the explain output showing the node's Graph_2 semantic model: actions, guards, side effects, data flow, and domain tags.

**Reasoning:**
The explain command is the primary inspection tool. Adding semantic information gives agents and developers a complete picture of what a function does, not just its structure and connections.

**Implementation Steps:**
1. Add behavior section to explain output:
   ```
   ## Behavior (Graph_2)
   Actions:
     1. VALIDATE — validate user input against schema
     2. QUERY — fetch user record from database
     3. GUARD — check user.is_active before proceeding
     4. MUTATE — update user.last_login timestamp
   Guards:
     - authentication: user must be authenticated (line 12)
     - validation: input schema check (line 8)
   Side Effects:
     - DATABASE_READ: users table (confidence: 0.95)
     - DATABASE_WRITE: users.last_login (confidence: 0.90)
     - LOGGING: audit trail (confidence: 1.0)
   Data Flow:
     Inputs: user_id (generic), session_token (credentials)
     Outputs: UserProfile (pii)
   Domain: auth, persistence
   Behavior Hash: 7f3a2c...
   Confidence: 0.87
   ```
2. Omit section when Graph_2 data unavailable
3. Support `--json` output with full semantic detail
4. Add `--behavior` flag to show only semantic section (quick check)

**Files:**
- `codegraph/cli.py` (modify)
- `codegraph/query.py` (modify)

**Dependencies:** R-007, N-005, B-014

**Edge Cases:**
- No Graph_2 → section omitted, note "Run build for semantic analysis"
- Low confidence → show confidence warning
- Very many actions → paginate or summarize

**Validation:**
- Explain includes behavior section when Graph_2 present
- JSON output includes all semantic fields
- Missing Graph_2 doesn't crash explain

---

### TASK R-032 — Implement Semantic Summary Command

**Description:**
Add a `codegraph semantics` command group with subcommands for inspecting and managing Graph_2 data.

**Reasoning:**
Graph_2 is a significant subsystem that needs its own inspection tools, separate from structural graph commands.

**Implementation Steps:**
1. Add `@cli.group() semantics` to `codegraph/cli.py`
2. Subcommands:
   - `codegraph semantics summary` — overview of Graph_2 (coverage, top domains, effect distribution)
   - `codegraph semantics effects [--type TYPE]` — list all side effects or filter by type
   - `codegraph semantics guards` — list all detected guards
   - `codegraph semantics domains` — list all domain tags with node counts
   - `codegraph semantics pure` — list all pure (side-effect-free) functions
   - `codegraph semantics risky [--min-risk N]` — list high-risk nodes
   - `codegraph semantics validate` — check Graph_2 consistency against Graph_0/Graph_1
3. All subcommands support `--json` output

**Files:**
- `codegraph/cli.py` (modify)

**Dependencies:** R-007, R-028, N-001

**Edge Cases:**
- No Graph_2 → helpful error: "Run `codegraph build` first"
- Graph_2 stale (Graph_0 changed) → warn

**Validation:**
- All subcommands produce output
- JSON output valid
- Help text describes semantic concepts

---

### TASK R-033 — Implement Semantic Diff Between Versions

**Description:**
Show how the semantic model changed between two graph versions: new actions, removed guards, changed side effects, domain shifts.

**Reasoning:**
When reviewing changes, knowing that "3 functions gained DATABASE_WRITE side effects" or "2 authentication guards were removed" is far more valuable than "15 body hashes changed".

**Implementation Steps:**
1. Implement `diff_semantics(old_graph2, new_graph2) -> SemanticDiff` in `codegraph/semantics.py`
2. Report:
   - **New effects**: functions that gained side effects they didn't have before
   - **Lost effects**: functions that lost side effects (may indicate broken functionality)
   - **Guard changes**: guards added or removed
   - **Domain shifts**: functions that changed domain tags
   - **Safety regressions**: functions where risk_level increased
   - **Purity changes**: functions that became pure or lost purity
3. Add to `codegraph diff` output as "Semantic Changes" section
4. Add to delta output

**Files:**
- `codegraph/semantics.py` (modify)
- `codegraph/models/diff.py` (modify)

**Dependencies:** R-007, B-015

**Edge Cases:**
- No old Graph_2 → all entries are "new"
- No new Graph_2 → error
- Node only in one version → added/removed

**Validation:**
- New DB writes detected
- Removed guards flagged
- Domain shifts tracked
- Safety regressions highlighted

---

## Phase 8 — Testing & Validation

---

### TASK R-034 — Implement Unit Tests for Semantic Extraction

**Description:**
Comprehensive unit tests for all semantic extraction components: actions, guards, side effects, data flow, domain inference.

**Reasoning:**
Semantic extraction involves heuristics and pattern matching. Thorough testing ensures accuracy and prevents regressions.

**Implementation Steps:**
1. Create `tests/test_semantics.py`
2. Test categories:
   a. **Action extraction**: known function patterns classify correctly
   b. **Guard detection**: if-return patterns, assert, try/except
   c. **Side effect classification**: DB, network, filesystem, logging, state mutation
   d. **Data flow**: parameter tracking, return type inference
   e. **Domain inference**: file path, name patterns, action-based
   f. **Name pattern classifier**: all patterns in R-014
   g. **SQL classifier**: SELECT/INSERT/UPDATE/DELETE/DDL (R-016)
   h. **Known library database**: all entries in R-015
3. Test edge cases:
   - Empty function, complex function, async function, generator
   - Decorated functions, class methods, static methods
   - Functions with no type annotations

**Files:**
- `tests/test_semantics.py`

**Dependencies:** R-008 through R-016

**Validation:**
- All action types correctly classified
- All side effect types correctly classified
- Guard detection accuracy > 90% on test suite
- Domain inference consistent across runs

---

### TASK R-035 — Implement Integration Tests for Semantic Pipeline

**Description:**
End-to-end tests that verify the full semantic pipeline: AST → Graph_0 → Workflow → Graph_2, including delta updates.

**Reasoning:**
The semantic pipeline must integrate correctly with the rest of the system. Integration tests verify the full chain on a real sample project.

**Implementation Steps:**
1. Create `tests/test_semantics_integration.py`
2. Test scenarios:
   a. Full build produces Graph_2 with reasonable coverage
   b. Delta updates only re-extract affected nodes
   c. Semantic queries return correct results
   d. Policy violations detected by semantic rules
   e. Intent reinforcement produces valid suggestions
   f. Dead code with dispatch actions not classified as SAFE_TO_REMOVE
3. Use sample project fixture (O-002) extended with:
   - DB-writing functions
   - Auth handlers
   - Pure computation functions
   - Dynamic dispatch patterns

**Files:**
- `tests/test_semantics_integration.py`

**Dependencies:** R-017, R-018, O-002

**Validation:**
- Full pipeline produces valid Graph_2
- Delta correctly narrows re-extraction
- All semantic features work end-to-end

---

### TASK R-036 — Implement Semantic Extraction Accuracy Benchmarks

**Description:**
Measure semantic extraction accuracy against hand-labeled ground truth on a reference codebase.

**Reasoning:**
Semantic extraction uses heuristics. Accuracy must be quantified: what percentage of actions, guards, and effects are correctly classified? False positives and false negatives must be tracked.

**Implementation Steps:**
1. Create `benchmarks/semantic_accuracy.py`
2. Hand-label 100 functions from sample project with ground-truth semantics
3. Run semantic extractor on same functions
4. Measure:
   - Action type precision/recall
   - Side effect precision/recall
   - Guard detection precision/recall
   - Domain tag accuracy
   - Overall confidence calibration (predicted vs actual accuracy)
5. Target: >80% precision, >70% recall for action classification
6. Target: >90% precision for side effect detection (false positives are dangerous)

**Files:**
- `benchmarks/semantic_accuracy.py`
- `tests/fixtures/semantic_ground_truth.json`

**Dependencies:** R-017

**Validation:**
- Accuracy meets targets
- False positive rate for side effects < 10%
- Confidence scores correlate with actual accuracy

---

## Phase 9 — Advanced Features

---

### TASK R-037 — Implement Semantic-Aware Agent Context

**Description:**
Include Graph_2 semantic data in the pre-fetched context provided to agents in tasks.json, so agents understand behavioral implications before proposing changes.

**Reasoning:**
Agents that know a function "performs authentication and database writes with a fraud guard" make better repair decisions than agents that only see "function has 3 callers and 2 callees". Semantic context prevents dangerous automated changes.

**Implementation Steps:**
1. Extend `pre_fetched_context` in task generation (I-008) with semantic data:
   - For each task node, include its Graph_2 summary: actions, guards, effects, domain
   - For related nodes (callers/callees), include brief semantic summary
   - Flag security-relevant nodes explicitly: "WARNING: this node performs AUTHENTICATE"
2. Add `semantic_context: dict` to TaskNode model
3. Keep context compact — summarize, don't include full Graph_2 entries

**Files:**
- `codegraph/analyzer.py` (modify)
- `codegraph/models/tasks.py` (modify)

**Dependencies:** R-017, I-008, B-009

**Edge Cases:**
- No Graph_2 data → omit semantic context, don't block task generation
- Very large semantic model → summarize to key actions + effects only
- Agent confused by semantic data → provide as structured optional section

**Validation:**
- Tasks include semantic context when Graph_2 available
- Context is compact (< 200 bytes per node)
- Security warnings present for auth/guard nodes
- Tasks without Graph_2 still generated correctly

---

### TASK R-038 — Implement Semantic Configuration and Extensibility

**Description:**
Add configuration options for semantic extraction: enable/disable, confidence thresholds, custom domain tags, custom library effects, pattern overrides.

**Reasoning:**
Different projects have different domain vocabularies and library stacks. Configuration makes semantic extraction adaptable to any codebase.

**Implementation Steps:**
1. Add semantics section to `config.yaml`:
   ```yaml
   semantics:
     enabled: true
     confidence_threshold: 0.5  # minimum confidence to include in Graph_2
     custom_domains:
       - name: "trading"
         patterns: ["trade_*", "order_*", "position_*"]
       - name: "risk"
         patterns: ["risk_*", "limit_*", "margin_*"]
     custom_effects:
       "myorm.Model.persist": ["DATABASE_WRITE", "save"]
       "myapp.notify": ["MESSAGE_QUEUE", "publish"]
     pattern_overrides:
       "schedule_*": "DISPATCH"
     skip_modules: ["tests/*", "scripts/*"]
   ```
2. Parse and validate config
3. Pass to semantic extractor
4. Custom domains extend (not replace) built-in domain tags
5. Custom effects extend built-in known library database

**Files:**
- `codegraph/semantics.py` (modify)
- `codegraph/config.py` (modify if exists)

**Dependencies:** R-008, A-009

**Edge Cases:**
- Invalid config → helpful error message
- Custom domain conflicts with built-in → custom takes precedence
- Empty config → use all defaults

**Validation:**
- Custom domains detected
- Custom effects classified correctly
- Confidence threshold filters low-confidence entries
- `enabled: false` skips all semantic extraction

---

### TASK R-039 — Implement Semantic Visualization

**Description:**
Generate visual representations of the semantic behavior model: side-effect flow diagrams, guard dependency trees, domain clustering.

**Reasoning:**
Visualization makes semantic data accessible to non-expert users. A diagram showing "all database-writing functions are guarded by auth" is immediately understandable.

**Implementation Steps:**
1. Implement `visualize_semantics(graph2, workflow, format) -> str` in `codegraph/semantics.py`
2. Visualizations:
   a. **Effect flow**: DOT/Mermaid diagram showing which functions have which side effects, colored by risk level
   b. **Guard tree**: which guards protect which actions, showing the safety chain
   c. **Domain map**: cluster functions by domain tag, show cross-domain edges
3. Color coding:
   - Red: high-risk side effects (DATABASE_WRITE, NETWORK_REQUEST)
   - Yellow: medium-risk (STATE_MUTATION, FILESYSTEM_WRITE)
   - Green: pure functions (no side effects)
   - Blue: guarded functions
4. Support DOT, Mermaid, and ASCII output

**Files:**
- `codegraph/semantics.py` (modify)

**Dependencies:** R-007, R-028

**Edge Cases:**
- Very large graph → show subgraph around queried nodes
- Many domains → cluster visualization
- Functions with many effects → summarize

**Validation:**
- DOT renders in Graphviz
- Mermaid renders in GitHub markdown
- Colors correctly represent risk levels

---

### TASK R-040 — Implement Graph_2 Migration and Backward Compatibility

**Description:**
Handle upgrading existing codegraph projects that were built before Graph_2 was available, plus Graph_2 format version migration.

**Reasoning:**
Existing projects won't have Graph_2. The system must gracefully detect this, offer to generate Graph_2, and degrade feature set when Graph_2 is unavailable.

**Implementation Steps:**
1. Detect missing Graph_2:
   - `codegraph build` → always generate Graph_2 (unless `--skip-semantics`)
   - `codegraph status` → report "Semantic analysis: not available" when missing
   - `codegraph query effects(...)` → error: "Semantic data not available. Run `codegraph build` to generate."
2. Feature degradation ladder:
   - **Full Graph_2**: all semantic features available
   - **No Graph_2**: structural features work, semantic queries error, policy rules skip semantic checks, explain omits behavior section, dead code uses structural signals only
3. Format version migration:
   - If `graph2.json` has old `format_version` → migrate automatically
   - Backup old file before migration
   - Log migration operations

**Files:**
- `codegraph/semantics.py` (modify)
- `codegraph/cli.py` (modify)

**Dependencies:** R-017, R-007

**Edge Cases:**
- Graph_2 exists but is stale (Graph_0 changed) → warn, suggest rebuild
- Graph_2 corrupt → regenerate from scratch
- Partial Graph_2 (some nodes extracted, others not) → valid, low coverage

**Validation:**
- Missing Graph_2 doesn't crash any command
- Feature degradation is graceful (errors are helpful)
- Format migration preserves data
- Status command accurately reports Graph_2 availability

---

### TASK R-041 — Write Graph_2 / Semantic Layer Documentation

**Description:**
Document the semantic behavior layer: concepts, extraction methodology, configuration, query syntax, policy rules, and limitations.

**Reasoning:**
Graph_2 introduces new concepts that users and agent developers need to understand. Clear documentation is essential for adoption.

**Implementation Steps:**
1. Create `docs/semantic-layer.md` with sections:
   - **Concept**: What is Graph_2? How does it relate to Graph_0/Graph_1?
   - **Behavior Model**: actions, guards, side effects, data flow, domain tags
   - **Extraction**: how semantic analysis works (patterns, heuristics, known libraries)
   - **Configuration**: custom domains, effects, patterns, confidence thresholds
   - **Queries**: semantic query syntax with examples
   - **Policy Rules**: semantic rule types with examples
   - **Intent Reinforcement**: how Graph_2 validates Graph_1 annotations
   - **Limitations**: what semantic extraction can and cannot detect
   - **FAQ**: common questions
2. Include worked examples with real code snippets
3. Diagrams showing Graph_0 → Workflow → Graph_2 pipeline

**Files:**
- `docs/semantic-layer.md`

**Dependencies:** R-038, R-032

**Validation:**
- Documentation matches implementation
- Examples are runnable
- Limitations honestly documented

---

### TASK R-042 — Implement Semantic Failure Mode Handling

**Description:**
Define and handle all semantic-layer-specific failure modes gracefully.

**Reasoning:**
Semantic extraction is heuristic-based and will encounter edge cases. Every failure must be handled without breaking the rest of the system.

**Implementation Steps:**
1. Define failure modes and handlers:
   - **semantic_extraction_crash**: AST analysis fails for a node → log, skip node, continue
   - **low_coverage_warning**: < 50% of nodes have semantic models → suggest running with lower confidence threshold
   - **stale_graph2**: Graph_2 out of date with Graph_0 → warn, suggest rebuild
   - **unknown_library**: call target not in known library database → classify as UNKNOWN, reduce confidence
   - **circular_semantics**: function's semantics depend on callee's semantics which depend on caller → break cycle with provisional classification
   - **semantic_contradiction**: Graph_2 and Graph_1 directly contradict each other → report as intent reinforcement finding
   - **config_invalid**: custom semantic config has errors → report, use defaults
2. Log all failure modes with structured logging
3. No failure mode should crash build or delta

**Files:**
- `codegraph/semantics.py` (modify)

**Dependencies:** R-017, R-018

**Edge Cases:**
- Multiple failures on same node → log all, still skip
- Failure rate > 50% → warn that semantic analysis may be unreliable

**Validation:**
- Each failure mode handled gracefully
- Build/delta complete despite semantic failures
- Structured logging captures all failure details
