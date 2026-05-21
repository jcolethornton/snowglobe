# Snowglobe — Product Specification

## Overview

**Snowglobe** is a read-only CLI tool that provides **explainable visibility into Snowflake cost and access**.

It answers three core questions:

1. **Where did our Snowflake spend come from?**
2. **Who owns and can access what?**
3. **Who is responsible when cost or access looks wrong?**

Snowglobe does **not** manage, deploy, or enforce Snowflake state.
It observes, explains, and recommends.

---

## Goals

* Make Snowflake cost **understandable and attributable**
* Make Snowflake access **traceable and explainable**
* Provide **human-readable insights**, not raw metadata
* Be safe to run in production (read-only by default)
* Be useful via CLI output alone

---

## Non-Goals (Very Important)

Snowglobe will **not**:

* Modify Snowflake objects or grants
* Apply DDL or manage deployments
* Act as a dashboard or BI tool
* Replace Terraform, dbt, or Snowflake-native controls
* Guarantee “correct” governance decisions

If a feature requires write access, it is **out of scope for v1**.

---

## Target Users

* Analytics Engineers
* Data Engineers
* Data Platform / Enablement teams

Snowglobe is built for **engineers**, not executives.

---

## Supported Environments (v1)

* Snowflake (all editions)
* Python 3.11+
* CLI execution (local, cron, CI, Airflow)

---

## Authentication & Security

* Uses standard Snowflake credentials (password, key pair, SSO)
* Requires **read-only role**
* No data leaves the customer environment by default
* Optional outbound Slack webhook only

---

## Core Concepts

### Cost Visibility

Snowglobe focuses on **cost deltas and attribution**, not billing totals.

Cost is attributed to:

* Warehouse
* Role
* User / service account
* Query type (e.g. COPY, SELECT, TRANSFORM)

Baseline comparisons are used to detect unusual changes.

---

### Access Visibility

Snowglobe explains **why** access exists, not just **that** it exists.

Access explanations include:

* Role inheritance paths
* Ownership chains
* Grant sources (direct vs inherited)
* Future grants

---

### Explainability

Every insight must:

* Show the reasoning path
* Reference concrete Snowflake metadata
* Be reproducible from raw inputs

“No black boxes.”

---

## CLI Interface (v1)

### `snowglobe daily`

Outputs a daily summary combining cost and access insights.

**Includes:**

* Total cost vs baseline
* Top cost contributors
* Notable access risks or anomalies
* Correlated insights (cost + ownership)

---

### `snowglobe cost`

Focused cost analysis.

**Subcommands (initial):**

* `snowglobe cost summary`
* `snowglobe cost top`
* `snowglobe cost delta`

---

### `snowglobe access`

Focused access analysis.

**Subcommands (initial):**

* `snowglobe access explain <role|object>`
* `snowglobe access ownership`
* `snowglobe access diff`

---

## Outputs

Snowglobe supports multiple output formats:

* Rich CLI (default)
* JSON
* CSV
* Optional Slack message (summary only)

---

## Architecture Principles

* Read-only Snowflake queries only
* Clear separation between:

  * Data collection
  * Analysis
  * Insight generation
  * Presentation
* Domain logic must be testable without Snowflake

---

## Technical Architecture (Implementation Detail)

### Project Structure

```
snowglobe/
├── __main__.py              # Entry point → calls cli.app:app()
├── __init__.py              # Empty
├── cli/                     # CLI layer (Typer + interactive shell)
│   ├── app.py              # Root Typer app, no-args → shell, subcommands for headless
│   ├── shell.py            # Interactive REPL (prompt_toolkit), all shell commands
│   ├── context.py          # SnowglobeContext — unified context (CLI + shell state)
│   ├── prompts.py          # Interactive fuzzy-completion prompts, TTY-aware
│   ├── shell_completer.py  # Tab-completion for shell commands
│   ├── access.py           # `snowglobe access check|create` commands
│   ├── cost.py             # `snowglobe cost queries` command
│   ├── optimizer.py        # `snowglobe optimize query|top-queries` commands
│   ├── debug.py            # `snowglobe debug` — connection diagnostics
│   ├── diff.py             # `snowglobe diff access` (stub)
│   └── report.py           # `snowglobe report cost|access` (stubs)
├── config/
│   └── loader.py           # Loads ~/.snowglobe/config.yaml, env var expansion
├── snowflake/
│   └── connection.py       # SnowflakeReadOnly — enforces no DDL, context manager
├── state/
│   ├── db.py              # StateDB — SQLite backend (grants, role_edges, user_roles, metadata)
│   └── state.py           # StateManager — legacy JSON persistence (deprecated)
├── collectors/             # Data collection from Snowflake (ACCOUNT_USAGE bulk queries)
│   ├── access.py           # AccessCollector — users, roles, grants, object index, CREATE grants
│   ├── query_history.py    # QueryCollector — warehouse query history
│   └── query_profile.py    # QueryProfileCollector — GET_QUERY_OPERATOR_STATS
├── core/                   # Service orchestration layer
│   ├── access_service.py   # AccessService — inspect_access + inspect_create + state mgmt
│   ├── query_service.py    # QueryService — query history state + sorting/filtering
│   └── optimizer.py        # QueryOptimizerService — profile collection + analysis
├── engines/                # Analysis/computation engines
│   ├── access/
│   │   ├── resolver.py     # AccessResolver — grants + role graph + path traversal
│   │   └── explainer.py    # AccessExplainer — user/role access with path explanation
│   ├── optimizer/
│   │   └── query_optimizer.py  # QueryOptimizerEngine — heuristic query analysis
│   └── ai/
│       └── cortex_optimizer.py # CortexOptimizer — Snowflake Cortex AI_COMPLETE
├── graphs/                 # Graph data structures
│   ├── role_graph.py       # RoleGraph — role hierarchy, ancestor traversal, path finding
│   └── user_graph.py       # UserGraph — user→role assignments, effective role resolution
├── models/                 # Data models (dataclasses)
│   ├── access.py           # AccessGrant — resolved grant with provenance
│   ├── access_path.py      # AccessPath — chain from identity to grant
│   ├── object_ref.py       # ObjectRef — (ObjectType, FQN)
│   ├── object_type.py      # ObjectType enum (27 types incl. STREAMLIT, NOTEBOOK, etc.)
│   ├── optimizer.py        # QueryOptimizationResult, ExpensiveOperator
│   ├── privilege.py        # Privilege enum + semantic matching (OWNERSHIP implies all)
│   └── query.py            # QueryProfile, QueryStats
├── queries/
│   └── query_history.py    # SQL template for warehouse query cost estimation
├── output/
│   └── cli.py              # Formatting: Rich tables, text, JSON, tree, create output
└── tests/
    └── access_tests.py     # Test stub
```

---

### Key Abstractions

#### Connection Layer

- **`SnowflakeReadOnly`** (`snowflake/connection.py`): Context-managed Snowflake connector that blocks DDL/DCL (CREATE, ALTER, DROP, GRANT, REVOKE, TRUNCATE). Supports password and key-pair auth.

#### Configuration

- **`SnowglobeConfig`** (`config/loader.py`): Loads multi-profile YAML from `~/.snowglobe/config.yaml`. Supports environment variable expansion (`$VAR` in values). Profiles contain `account`, `user`, `role`, `warehouse`, `password`/`private_key_path`.

#### Context Objects

- **`SnowglobeContext`** (`cli/context.py`): Unified context for both CLI and shell. Holds profile, connection factory, output format, verbosity, working state (`target_role`, `username`, `object_type`, `object_name`, `privilege`), and preloaded graphs/grants/object_index.

#### State Management

- **`StateDB`** (`state/db.py`): SQLite-backed state store (`~/.snowglobe/state/snowglobe.db`). Stores all 782K grants, role hierarchy edges, and user role assignments in indexed tables. Replaces the previous JSON-file approach. Supports full refresh (bulk replace) and incremental refresh (upsert/delete). Object index is derived from the grants table via `SELECT DISTINCT granted_on, fqn`. Uses WAL journal mode for concurrent read performance.

**SQLite Schema:**
```
grants (grantee, privilege, granted_on, name, table_catalog, table_schema, granted_by, granted_to, fqn)
role_edges (parent, child)
user_roles (username, role)
metadata (key, value)  — stores refreshed_at timestamp
```

**Indexes:** `idx_grants_object`, `idx_grants_fqn`, `idx_grants_grantee`, `idx_grants_privilege`, `idx_role_edges_parent`, `idx_role_edges_child`, `idx_user_roles_user`

#### Graphs

- **`RoleGraph`** (`graphs/role_graph.py`): Directed graph of role inheritance (child → parent edges). Key methods: `all_ancestors(role)` (iterative DFS), `all_paths(from, to)` (recursive DFS returning all paths), `parents_of(role)`.
- **`UserGraph`** (`graphs/user_graph.py`): Maps users to their directly assigned roles (both account and database roles). `effective_roles(user, role_graph)` resolves full transitive closure. Supports an exclude-list for filtering noisy system roles.

#### Collectors

- **`AccessCollector`** (`collectors/access.py`): Uses `SNOWFLAKE.ACCOUNT_USAGE` bulk queries (not N+1 SHOW commands) for performance. Collects: user roles (`GRANTS_TO_USERS`), role hierarchy (`GRANTS_TO_ROLES`), high-level object grants (DATABASE/WAREHOUSE/ACCOUNT), object FQN index for completions, and CREATE privilege grants. Falls back to `SHOW GRANTS ON` for object types not in ACCOUNT_USAGE (STREAMLIT, NOTEBOOK, DYNAMIC TABLE, ALERT, TAG, SECRET).
- **`QueryCollector`** (`collectors/query_history.py`): Queries `SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY` with a credit estimation formula based on warehouse size multiplier.
- **`QueryProfileCollector`** (`collectors/query_profile.py`): Fetches SQL text and operator-level stats via `GET_QUERY_OPERATOR_STATS(<query_id>)`.

#### Engines

- **`AccessResolver`** (`engines/access/resolver.py`): Core access resolution engine. Given grants, role graph, and user graph, resolves effective grants for a user/role and finds all access paths (role chains) explaining why access exists.
- **`AccessExplainer`** (`engines/access/explainer.py`): High-level query interface. Given a target (user or role) + object + privilege, returns a structured dict explaining: object existence, roles with the privilege, access paths, and whether the target has access.
- **`QueryOptimizerEngine`** (`engines/optimizer/query_optimizer.py`): Heuristic analysis of query operator profiles. Detects: join explosions (10x row amplification), disk spills, partition pruning failures (>90% scanned), large scans (>1GB), cartesian joins, large window functions (>100M rows), large aggregations (>100M rows), heavy network shuffle (>1GB). Computes per-operator cost scores and attribution by operator type.
- **`CortexOptimizer`** (`engines/ai/cortex_optimizer.py`): Calls Snowflake Cortex `AI_COMPLETE` (claude-haiku-4-5) with the SQL text + heuristic suggestions + cost attributes to generate AI-powered optimization recommendations.

#### Models

- **`AccessGrant`**: Frozen dataclass — role, privilege, ObjectRef, granted_on, granted_by, inherited flag, source_role, role_type (ACCOUNT/DATABASE).
- **`ObjectRef`**: Frozen dataclass — ObjectType enum + FQN string.
- **`Privilege`**: Enum with semantic matching (OWNERSHIP implies all privileges).
- **`QueryProfile`**: Dataclass for operator-level stats (step_id, operator_id, parent_operators, statistics, time breakdown, attributes).
- **`QueryStats`**: Dataclass for query-level cost data (credits, bytes, execution time).
- **`AccessPath`**: Identity + role chain + terminal grant.

---

#### Data Flow

#### Access Check Flow

```
CLI (access check) or Shell (access) → resolve_access_inputs (TTY-aware prompts)
  → AccessService.inspect_access()
    → Load role graph + user graph from SQLite (in-memory)
    → Query grants for target object from SQLite (indexed, <100ms)
    → AccessResolver (build from targeted grants + graphs)
    → AccessExplainer (user_access / role_access)
  → Output formatter (text or JSON)
```

#### Reverse Lookup Flow (whoaccess)

```
CLI (access whoaccess) or Shell (whoaccess) → AccessService.inspect_reverse()
  → Query grants for target object from SQLite
  → For each privilege: find direct roles, descendants (via role graph), users
  → Output: per-privilege breakdown with roles + users + counts
```

#### CREATE Privilege Flow

```
CLI (access create) or Shell (create) → AccessService.inspect_create()
  → Load role graph + user graph from SQLite
  → Resolve effective roles (transitive closure)
  → Query CREATE grants from SQLite (indexed by privilege + grantee)
  → Resolve role inheritance paths (when scoped)
  → Output: scope hierarchy + via_roles + paths
```

#### Query Cost Flow

```
CLI (cost queries) → QueryService
  → StateManager (load/refresh)
  → QueryCollector → QUERY_HISTORY SQL → QueryStats models
  → pandas DataFrame sorting/filtering
  → Rich table output
```

#### Query Optimizer Flow

```
CLI (optimize query) → QueryOptimizerService
  → QueryProfileCollector → GET_QUERY_OPERATOR_STATS → QueryProfile models
  → QueryOptimizerEngine (heuristic detection + scoring)
  → Operator tree construction + cost attribution
  → CortexOptimizer (AI_COMPLETE for AI suggestions)
  → Output: suggestions, tree, cost breakdown, AI result
```

#### Interactive Shell Flow

```
`snowglobe` (no args) → start_shell(context)
  → AccessService.get_graphs() (preload from cache, auto-refresh if missing)
  → PromptSession with FuzzyCompleter
  → REPL loop: _dispatch(text, ctx) → handler functions
  → Commands: use, set, access, create, cost, optimize, refresh, status, debug, help
```

---

### CLI Commands (Implemented)

| Command | Status | Description |
|---------|--------|-------------|
| `snowglobe` (no args) | Working | Launches interactive shell |
| `snowglobe refresh` | Working | Refresh cached state from Snowflake (incremental by default) |
| `snowglobe refresh --full` | Working | Full refresh (rebuilds entire SQLite DB) |
| `snowglobe debug` | Working | Connection diagnostics (8-step checklist) |
| `snowglobe access check` | Working | Explain access for user/role on object (with role paths) |
| `snowglobe access create` | Working | Check CREATE privileges with scope hierarchy |
| `snowglobe access whoaccess` | Working | Reverse lookup: who can access this object? |
| `snowglobe cost queries` | Working | Top expensive queries by credits or bytes |
| `snowglobe optimize query --query-id <id>` | Working | Full query analysis + AI suggestions |
| `snowglobe optimize top-queries` | Working | Batch analysis of top N queries |
| `snowglobe diff access` | Stub | Not implemented |
| `snowglobe report cost` | Stub | Not implemented |
| `snowglobe report access` | Stub | Not implemented |

### Shell Commands

The shell uses a **guided wizard** (`check`) as the primary entry point, with direct shortcuts for power users. All commands have **fuzzy tab-completion** for arguments (usernames, roles, object FQNs).

| Command | Description |
|---------|-------------|
| `check` | **Guided wizard** — walks through access & privilege checks step by step |
| `roles <user>` | What roles does a user have? (direct + inherited) |
| `members <role>` | Who has this role? (direct + inherited users) |
| `path <from> <to>` | Does one role inherit from another? (shows inheritance paths) |
| `cost` | Show top expensive queries |
| `optimize <id>` | Analyze a specific query |
| `refresh` | Refresh cached state from Snowflake |
| `status` | Show current working state + cache age |
| `debug` | Run connection diagnostics |
| `help` / `?` | Show available commands |
| `exit` | Exit the shell |

**Shortcuts (power users):**

| Command | Description |
|---------|-------------|
| `use role <name>` | Set active role for queries |
| `use user <name>` | Set active user for queries |
| `access` | Direct: can user/role access an object? |
| `whoaccess` | Direct: who can access an object? |
| `create` | Direct: where can a role create objects? |

### Global CLI Options

- `--profile <name>` — Snowflake connection profile (default: "default")
- `--role <name>` — Override Snowflake role
- `--output table|json` — Output format
- `--verbose / -v` — Verbose output

---

### Dependencies

| Package | Purpose |
|---------|---------|
| typer | CLI framework |
| rich | Terminal formatting (tables, JSON, colors) |
| prompt_toolkit | Interactive shell + fuzzy completion |
| snowflake-connector-python | Snowflake connectivity |
| pandas | DataFrame operations for query data |
| pydantic | (declared but not actively used in models) |
| PyYAML | Config file loading |
| sqlglot | (declared but not actively used yet) |
| Jinja2 | (declared, likely for future templating) |
| cryptography/pyOpenSSL | Key-pair authentication |

---

### Design Patterns

1. **Service-per-domain**: Each domain (access, cost, optimization) has a service class that orchestrates collectors, engines, and state.
2. **SQLite-backed state**: All Snowflake metadata (782K grants, role edges, user assignments) stored in a single indexed SQLite database (`~/.snowglobe/state/snowglobe.db`). Provides instant local lookups (<100ms) for any object. Auto-refreshes on first run.
3. **Incremental refresh with watermarks**: Uses `GREATEST(MODIFIED_ON, COALESCE(DELETED_ON, '1970-01-01')) >= last_refresh` to fetch only changed rows. Reduces refresh from ~2.5 min to ~13s.
4. **Graph-based access resolution**: Role hierarchy is modeled as a directed graph. Access is resolved by computing transitive closures and finding all paths. `all_descendants()` enables reverse lookups.
5. **Heuristic + AI**: Query optimization uses rule-based heuristics first, then feeds those results to Cortex AI for synthesized recommendations.
6. **Read-only enforcement**: The connection layer actively blocks DDL/DCL statements at the application level.
7. **TTY-aware dual mode**: Same commands work interactively (fuzzy prompts for missing args) and headlessly (error on missing args). Detected via `sys.stdin.isatty()`.
8. **Object index derived from grants**: No separate collection needed — `SELECT DISTINCT granted_on, fqn FROM grants` provides tab-completion data. (Exception: STREAMLIT/NOTEBOOK/DYNAMIC TABLE/ALERT need SHOW enumeration as they're not in GRANTS_TO_ROLES.)

---

### Current Limitations / Known Gaps

1. **No `daily` command** — Specified but not implemented.
2. **No CSV output** — Only table and JSON formats exist.
3. **Diff/Report commands are stubs** — Raise `NotImplementedError`.
4. **Test coverage is minimal** — Single test file.
5. **STREAMLIT/NOTEBOOK/DYNAMIC TABLE/ALERT** not in object completions (requires SHOW enumeration during refresh).
6. **ACCOUNT_USAGE has 45 min latency** — Very recent grant changes won't appear.
7. **No `cost summary` or `cost delta`** — Only `cost queries` exists.
8. **Future grants not tracked** — Low priority (not needed for existing object access checks).
9. **Empty object_name causes crash** — Should validate before `.upper()` call.
10. **Privilege suggestions not context-aware** — Same list shown for all object types.

---

## Testing Strategy

* Unit tests for analyzers and explainers
* Fixtures for Snowflake metadata
* Minimal integration tests for read-only access

---

## Versioning & Evolution

* v1: Visibility + explainability
* v2+: Optional controlled actions (explicit opt-in only)
* No breaking changes without a major version bump

---

## Success Criteria (v1)

Snowglobe is successful if:

* An engineer can explain a cost spike in minutes
* An engineer can trace why access exists without trial-and-error
* The tool can be safely recommended to run in prod

---

## License & Distribution

* Distributed as a Python package
* CLI-first
* Commercial licensing planned (details TBD)

---

## Guiding Principle

> **Snowglobe earns trust by never touching production state.**

