<p align="center">
  <img src="assets/logo.svg" alt="Snowglobe" width="600"/>
</p>

# Snowglobe

**Explainable cost and access visibility for Snowflake — read-only by design.**

Snowglobe is a CLI that helps analytics and data platform engineers answer three questions about their Snowflake account:

1. **Where did our Snowflake spend come from?**
2. **Who owns and can access what?**
3. **Who is responsible when cost or access looks wrong?**

It observes, explains, and recommends. It does not manage, deploy, or enforce Snowflake state.

---

## Features

- **Access explainability** — trace *why* a user or role has a privilege on an object, with every role-inheritance path made explicit (not just flat grant lists).
- **Reverse lookup** — given an object, see every role and user who can access it and through which paths.
- **CREATE privilege visibility** — answer "where can this role create tables?" across account, database and schema scopes.
- **Query cost estimation** — per-query credit cost using a warehouse-multiplier formula (Snowflake does not expose this in `QUERY_HISTORY`).
- **Heuristic query optimizer** — eight detectors over `GET_QUERY_OPERATOR_STATS` (join explosion, disk spill, pruning failures, cartesian joins, large scans, heavy shuffle, etc.) translated into actionable English.
- **AI-synthesized recommendations** — heuristic results passed to Snowflake Cortex `AI_COMPLETE` for a narrative suggestion.
- **Interactive shell** — `snowglobe` with no arguments drops you into a REPL with fuzzy tab-completion, a guided `check` wizard, and shortcuts.
- **Local SQLite cache** — all grants, role edges and user assignments cached locally for sub-100ms lookups. Incremental refresh in ~13s.

---

## Installation

### From PyPI

```bash
pip install snowglobe
```

### From source

```bash
git clone https://github.com/jcolethornton/snowglobe.git
cd snowglobe
pip install .
```

---

## Requirements

- Python 3.12.3+
- A Snowflake account
- A Snowflake role with read access to `SNOWFLAKE.ACCOUNT_USAGE`

---

## Configuration

Snowglobe loads connection profiles from `~/.snowglobe/config.yaml`. Multiple profiles are supported and selected with `--profile <name>`.

```yaml
# ~/.snowglobe/config.yaml

default:
  user: "jdoe@example.com"
  password: "/path/to/snowflake_key.p8"   # path to a key-pair file, or an inline password
  account: "abc123.us-east-1"
  role: "ANALYST"
  warehouse: "ANALYTICS_WH"

prod:
  user: "admin_user"
  password: "${SNOWFLAKE_PROD_PASSWORD}"   # environment variables are expanded in values
  account: "abc123.us-east-1"
  role: "SYSADMIN"
  warehouse: "ETL_WH"
```

Supported auth: password, key-pair (point `password:` at the `.p8` file), and SSO.

---

## Quickstart

```bash
# First run — caches account state into a local SQLite DB
snowglobe refresh

# Drop into the interactive shell
snowglobe

# Or run headless commands directly
snowglobe access check --user jdoe --object MY_DB.PUBLIC.ORDERS --privilege SELECT
snowglobe access whoaccess --object MY_DB.PUBLIC.PII_CUSTOMERS
snowglobe cost queries --top 20
snowglobe optimize query --query-id <query_id>
```

---

## Commands

### CLI

| Command | Description |
|---|---|
| `snowglobe` | Launch the interactive shell |
| `snowglobe refresh` | Incremental refresh of cached state from Snowflake |
| `snowglobe refresh --full` | Full rebuild of the local SQLite cache |
| `snowglobe debug` | Connection diagnostics (eight-step checklist) |
| `snowglobe access check` | Explain access for a user or role on an object, with inheritance paths |
| `snowglobe access create` | Show where a role can create objects, scoped by hierarchy |
| `snowglobe access whoaccess` | Reverse lookup — who can access this object? |
| `snowglobe cost queries` | Top expensive queries by credits or bytes |
| `snowglobe optimize query --query-id <id>` | Full operator-level analysis plus AI suggestions |
| `snowglobe optimize top-queries` | Batch analysis of the top N expensive queries |

### Global options

- `--profile <name>` — connection profile (default: `default`)
- `--role <name>` — override the Snowflake role from the profile
- `--output table|json` — output format
- `--verbose` / `-v` — verbose output

### Interactive shell

The shell uses a guided wizard as the primary entry point, with shortcuts for power users. All arguments support fuzzy tab-completion.

| Command | Description |
|---|---|
| `check` | Guided wizard — walks through an access or privilege check step by step |
| `roles <user>` | What roles does a user have? (direct + inherited) |
| `members <role>` | Who has this role? (direct + inherited users) |
| `path <from> <to>` | Does one role inherit from another? Shows inheritance paths |
| `cost` | Show top expensive queries |
| `optimize <id>` | Analyse a specific query |
| `refresh` | Refresh cached state from Snowflake |
| `status` | Current working state and cache age |
| `debug` | Connection diagnostics |
| `use role <name>` / `use user <name>` | Set active role or user for subsequent commands |
| `access` / `whoaccess` / `create` | Direct shortcuts that skip the wizard |
| `help` or `?` | List commands |
| `exit` | Exit the shell |

---

## Security

Snowglobe is **read-only by design** — its guiding principle is that it earns trust by never touching production state.

- The Snowflake connection layer actively blocks `CREATE`, `ALTER`, `DROP`, `GRANT`, `REVOKE`, and `TRUNCATE` statements before they reach Snowflake.
- All metadata is fetched via bulk queries against `SNOWFLAKE.ACCOUNT_USAGE`.
- No data leaves your environment by default. The optional Slack integration only sends summary text.
- Credentials are read from the local config file and never logged.

---

## How it works

```
CLI / Shell
   │
   ▼
Service layer (access / cost / optimizer)
   │
   ▼
Engines (resolver, explainer, optimizer)  ◄── Graphs (role / user)
   │
   ▼
Collectors  ──►  Snowflake ACCOUNT_USAGE / GET_QUERY_OPERATOR_STATS
   │
   ▼
Local SQLite state cache (~/.snowglobe/state/snowglobe.db)
```

The local cache holds ~782K grants, role-inheritance edges, and user-role assignments in indexed tables. Refresh uses watermarks on `MODIFIED_ON` / `DELETED_ON` to fetch only changed rows.

See `SPEC.md` for a deeper architecture reference.

---

## Limitations

- `ACCOUNT_USAGE` has up to 45 minutes of latency — very recent grant or query changes will not appear until the next refresh.
- `STREAMLIT`, `NOTEBOOK`, `DYNAMIC TABLE`, `ALERT`, `TAG`, and `SECRET` grants are not in `GRANTS_TO_ROLES`; Snowglobe falls back to live `SHOW GRANTS ON` for those types (slower but works).
- Future grants are not tracked yet.
- `diff access` and the `report` commands are stubs in this release.
- CSV output is not yet supported (table and JSON only).

See `TODO.md` for the current roadmap.

---

## Contributing

Pull requests and issues are welcome on [GitHub](https://github.com/jcolethornton/snowglobe).

---

## License

Apache-2.0 © 2025 Jaryd Thornton. See `LICENSE` for the full text.
