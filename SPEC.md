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
│   ├── app.py              # Root Typer app, profile loading, global options
│   ├── shell.py            # Interactive REPL shell (prompt_toolkit)
│   ├── router.py           # Shell command dispatcher
│   ├── registry.py         # @command decorator + COMMANDS dict
│   ├── context.py          # SnowglobeContext (Typer) + ShellContext (REPL)
│   ├── prompts.py          # Interactive fuzzy-completion prompts for access queries
│   ├── shell_completer.py  # Tab-completion for shell (use/inspect/set)
│   ├── access.py           # `snowglobe access check` command
│   ├── cost.py             # `snowglobe cost queries` command
│   ├── optimizer.py        # `snowglobe optimize query|top-queries` commands
│   ├── diff.py             # `snowglobe diff access` (stub)
│   ├── report.py           # `snowglobe report cost|access` (stubs)
│   └── commands/           # Shell-mode commands (use, set, access)
│       ├── use.py          # `use role|user <name>`
│       ├── set.py          # `set object_type|object_name|privilege <value>`
│       └── access.py       # `access` (runs query with current shell state)
├── config/
│   └── loader.py           # Loads ~/.snowglobe/config.yaml, supports env var expansion
├── snowflake/
│   └── connection.py       # SnowflakeReadOnly — enforces no DDL, context manager
├── state/
│   └── state.py            # StateManager — JSON file persistence + pandas loader
├── collectors/             # Data collection from Snowflake
│   ├── access.py           # AccessCollector — users, roles, grants via SHOW commands
│   ├── query_history.py    # QueryCollector — warehouse query history
│   └── query_profile.py    # QueryProfileCollector — GET_QUERY_OPERATOR_STATS
├── core/                   # Service orchestration layer
│   ├── access_service.py   # AccessService — state mgmt + resolver + explainer wiring
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
│   ├── grant.py            # Grant — simpler grant model (unused currently)
│   ├── object_ref.py       # ObjectRef — (ObjectType, FQN)
│   ├── object_type.py      # ObjectType enum (DATABASE, TABLE, VIEW, etc.)
│   ├── optimizer.py        # QueryOptimizationResult, ExpensiveOperator
│   ├── privilege.py        # Privilege enum + semantic matching (OWNERSHIP implies all)
│   └── query.py            # QueryProfile, QueryStats
├── queries/
│   └── query_history.py    # SQL template for warehouse query cost estimation
├── output/
│   └── cli.py              # Formatting: Rich tables, text, JSON, tree rendering
└── tests/
    └── access_tests.py     # Minimal test stub
```

---

### Key Abstractions

#### Connection Layer

- **`SnowflakeReadOnly`** (`snowflake/connection.py`): Context-managed Snowflake connector that blocks DDL/DCL (CREATE, ALTER, DROP, GRANT, REVOKE, TRUNCATE). Supports password and key-pair auth.

#### Configuration

- **`SnowglobeConfig`** (`config/loader.py`): Loads multi-profile YAML from `~/.snowglobe/config.yaml`. Supports environment variable expansion (`$VAR` in values). Profiles contain `account`, `user`, `role`, `warehouse`, `password`/`private_key_path`.

#### Context Objects

- **`SnowglobeContext`** (`cli/context.py`): Typer-level context holding profile, connection factory, output format, and verbosity. Lazy-connects to Snowflake.
- **`ShellContext`** (`cli/context.py`): Wraps `SnowglobeContext` for the interactive shell. Holds mutable working state (`username`, `role`, `object_type`, `object_name`, `privilege`) plus preloaded graphs/grants.

#### State Management

- **`StateManager`** (`state/state.py`): Simple JSON file persistence under `snowglobe/state/`. Supports save, load, and `get_dataframe()` (pandas). State files are gitignored.

#### Graphs

- **`RoleGraph`** (`graphs/role_graph.py`): Directed graph of role inheritance (child → parent edges). Key methods: `all_ancestors(role)` (iterative DFS), `all_paths(from, to)` (recursive DFS returning all paths), `parents_of(role)`.
- **`UserGraph`** (`graphs/user_graph.py`): Maps users to their directly assigned roles (both account and database roles). `effective_roles(user, role_graph)` resolves full transitive closure. Supports an exclude-list for filtering noisy system roles.

#### Collectors

- **`AccessCollector`** (`collectors/access.py`): Executes `SHOW USERS`, `SHOW ROLES`, `SHOW DATABASE ROLES`, and `SHOW GRANTS TO ROLE/USER` to build UserGraph, RoleGraph, and List[AccessGrant]. Uses naming conventions: `ACCOUNT_ROLE::<name>` and `DATABASE_ROLE::<db>::<name>`.
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

### Data Flow

#### Access Check Flow

```
CLI (access check) → AccessService
  → StateManager (load/refresh JSON state)
  → resolve_access_inputs (interactive prompts if args missing)
  → AccessResolver (build from grants + graphs)
  → AccessExplainer (user_access / role_access)
  → Output formatter (text or JSON)
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
  → Output: suggestions, tree, cost breakdown, AI result (also writes ai_suggestion.sql)
```

#### Interactive Shell Flow

```
CLI (shell) → start_shell
  → AccessService.get_graphs() (preload state)
  → PromptSession with FuzzyCompleter
  → REPL loop: dispatch(text, ctx) → COMMANDS[cmd](ctx, args)
  → Shell commands: use (set user/role), set (set object/privilege), access (run query)
```

---

### CLI Commands (Implemented)

| Command | Status | Description |
|---------|--------|-------------|
| `snowglobe shell` | Working | Interactive REPL with fuzzy completion |
| `snowglobe access check` | Working | Explain access for user/role on object |
| `snowglobe cost queries` | Working | Top expensive queries by credits or bytes |
| `snowglobe optimize query --query-id <id>` | Working | Full query analysis + AI suggestions |
| `snowglobe optimize top-queries` | Working | Batch analysis of top N queries |
| `snowglobe diff access` | Stub | Not implemented |
| `snowglobe report cost` | Stub | Not implemented |
| `snowglobe report access` | Stub | Not implemented |

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
2. **State caching**: Snowflake data is collected once and persisted to JSON. Subsequent runs load from disk unless `--refresh-state` is passed.
3. **Graph-based access resolution**: Role hierarchy is modeled as a directed graph. Access is resolved by computing transitive closures and finding all paths.
4. **Heuristic + AI**: Query optimization uses rule-based heuristics first, then feeds those results to Cortex AI for synthesized recommendations.
5. **Read-only enforcement**: The connection layer actively blocks DDL/DCL statements at the application level.
6. **Two-mode CLI**: Traditional subcommands (Typer) for scripted use + interactive shell (prompt_toolkit) for exploratory use.

---

### Current Limitations / Known Gaps

1. **No `daily` command** — Specified but not implemented.
2. **No CSV output** — Only table and JSON formats exist.
3. **No Slack integration** — Mentioned in spec but not implemented.
4. **Diff/Report commands are stubs** — Raise `NotImplementedError`.
5. **Test coverage is minimal** — Single test file with an import error (`models.enums` doesn't exist).
6. **State path is relative** — `StateManager` uses `snowglobe/state/` relative to CWD, not a fixed location.
7. **`CortexOptimizer` SQL syntax** — The AI_COMPLETE call has malformed SQL (response_format isn't properly formatted as a string parameter).
8. **No `cost summary` or `cost delta`** — Only `cost queries` exists.
9. **`report_app` is defined but not registered** in `app.py`.
10. **`Grant` model** (`models/grant.py`) exists but is unused; `AccessGrant` is the active model.

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

