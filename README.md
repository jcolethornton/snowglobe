<p align="center">
  <img src="assets/logo.svg" alt="Snowglobe" width="600"/>
</p>

# Snowglobe

**Explainable cost and access visibility for Snowflake — read-only by design.**

Snowglobe helps analytics, data platform, and security teams answer three questions about their Snowflake account:

1. **Where did our Snowflake spend come from?**
2. **Who owns and can access what?**
3. **Who is responsible when cost or access looks wrong?**

It observes, explains, and recommends. It never writes to Snowflake.

---

## Three ways to use it

| Interface | Command | When to use it |
|---|---|---|
| **TUI** *(default)* | `snowglobe` | Day-to-day exploration. Seven screens, mouse + keyboard, optional vim navigation, theme switcher. |
| **Interactive shell** | `snowglobe shell` | Wizards and quick lookups in a REPL. Useful when you only want one or two checks. |
| **Headless CLI** | `snowglobe <subcommand>` | CI, cron jobs, scripts, piping into other tools. Outputs `table`, `json`, or `csv` per command. |

All three share the same local SQLite cache and the same service layer, so anything you do in one is reflected in the others.

If you install without the `[tui]` extra and run `snowglobe` with no command, it falls back to the REPL shell with a one-line notice.

---

## Features

### Access explainability *(the killer feature)*

- **Why does X have access?** — Trace every role-inheritance path that grants a user or role a privilege on an object, not just a flat list of grants.
- **Who can access this?** — Reverse lookup an object: every role and user with access, grouped by privilege, including paths through inherited roles.
- **Where can this role create things?** — CREATE privilege visibility across account / database / schema scopes with the granting roles called out.
- **What roles does a user have?** — Direct, excluded, and inherited roles plus the total effective set.
- **Who has a specific role?** — Direct and inherited members.
- **Does role X inherit from role Y?** — Every inheritance path between two roles.
- **What's changed since last refresh?** — Drift detection across grants, role edges, and user assignments.

### Risk & privilege escalation

- **Escalation scan** — Walk every role in the account, find paths to admin roles (ACCOUNTADMIN, SYSADMIN, SECURITYADMIN, USERADMIN, or any role with `MANAGE GRANTS` / DB OWNERSHIP / IMPORTED PRIVILEGES on SNOWFLAKE), and score each path with a composite risk score (target weight × inverse hops × log of user count).
- **Single-role escalation check** — Pick one role and see exactly which admin targets it can reach and through which chain.
- **Dormant escalation risks** — Cross-references inactive users (no successful login in 90 days) against risk-bearing roles.
- **Direct privilege risks** — Roles with dangerous account-level grants that bypass the role graph entirely.
- **Unused privileges** — Roles with data grants but no recent `QUERY_HISTORY` activity, surfaced for cleanup.

### Cost & query attribution

- **12 cost views** — Account summary, daily trend with rolling average, top expensive queries, per-warehouse, per-user (warehouse + Cortex AI), AI services (Cortex Functions / Analyst / Agent / Code, Snowflake Intelligence), services (pipes / tasks / SPCS / auto-clustering / search optimisation), per-DB storage with monthly cost estimate at your contracted or on-demand rate, replication, materialized-view refresh costs, and Snowflake-native budget status.
- **Real query attribution** — Uses `QUERY_ATTRIBUTION_HISTORY.CREDITS_ATTRIBUTED_COMPUTE` for per-query credit cost (Snowflake's own attribution, not an estimate).
- **1-hour TTL local cache** — Cost views are cached in SQLite so repeated visits within the hour are instant; `Re-fetch` forces a fresh Snowflake call.
- **Drill-downs** — Click a warehouse for its daily trend; click a user for their per-warehouse credit breakdown; click a service-type summary row for its day-by-day spend; click a top query to load it into the Tune screen.

### Query optimiser

- **Eight heuristic detectors** over `GET_QUERY_OPERATOR_STATS` — join explosion, disk spill, pruning failure, cartesian joins, large scans, large window functions, large aggregations, heavy network shuffle.
- **Snowflake-native insights** from `QUERY_INSIGHTS` (where available).
- **Operator tree** with per-operator score and time percentage.
- **Cortex AI suggestions** — opt-in Cortex `AI_COMPLETE` call (default model: `claude-haiku-4-5`) that takes the SQL + heuristic findings + cost attribution and produces a narrative optimisation recommendation.

### Reports

- **Full report** — cost summary + AI costs + storage + top queries, rendered as markdown via Jinja templates.
- **Cost-only report** — same shape minus the query section.
- **User access report** — every effective role and grant for a user, formatted as a markdown audit trail.
- **CSV exports** — most cost commands accept `--csv <path>` to write directly to a file; the risk scan supports `--csv` and `--json`.

### Local SQLite cache

- All ~780K grants, role edges, and user assignments cached locally for sub-100ms lookups.
- **Incremental refresh** — uses `MODIFIED_ON` / `DELETED_ON` watermarks to fetch only changed rows. Full refresh ~2.5 min; incremental ~13s.
- Cost data uses a 1-hour TTL in the same SQLite store.

---

## Installation

```bash
pip install 'snowglobe[tui]'        # includes the Textual TUI
```

Or from source:

```bash
git clone https://github.com/jcolethornton/snowglobe.git
cd snowglobe
pip install -e '.[tui]'
```

If you don't want the TUI:

```bash
pip install snowglobe               # CLI + shell only, no Textual dependency
```

---

## Requirements

- Python **3.12.3+**
- A Snowflake account
- A Snowflake role with read access to `SNOWFLAKE.ACCOUNT_USAGE` (and optionally `SNOWFLAKE.ORGANIZATION_USAGE.RATE_SHEET_DAILY` for accurate storage cost)

---

## Configuration

Snowglobe loads connection profiles from `~/.snowglobe/config.yaml`. Multiple profiles are supported and selected with `--profile <name>`.

```yaml
# ~/.snowglobe/config.yaml

default:
  account: "abc123.us-east-1"
  user: "jdoe@example.com"
  password: "/path/to/snowflake_key.p8"   # key-pair path, or an inline password
  role: "ANALYST"
  warehouse: "ANALYTICS_WH"
  vim: true                                # optional — enable vim navigation by default

prod:
  account: "abc123.us-east-1"
  user: "admin_user"
  password: "${SNOWFLAKE_PROD_PASSWORD}"   # environment variables are expanded
  role: "SYSADMIN"
  warehouse: "ETL_WH"
```

Supported auth: password, key-pair (point `password:` at the `.p8` file), and SSO.

---

## Quickstart

```bash
# First run — populate the local SQLite cache from Snowflake
snowglobe refresh

# Launch the TUI (the default)
snowglobe

# Or explicitly, with vim-style navigation
snowglobe tui --vim

# Drop into the REPL shell instead
snowglobe shell

# Or fire individual headless commands
snowglobe access check --user jdoe --object-type TABLE \
  --object-name MY_DB.PUBLIC.ORDERS --privilege SELECT
snowglobe cost summary --days 30
snowglobe optimize query --query-id <query_id>
snowglobe report full --days 30 --output report.md
```

---

## The TUI

`snowglobe` (or the explicit `snowglobe tui`) opens a full-screen Textual app. Persistent header at top (profile / role / cache age), nav sidebar on the left, footer with active keybindings at the bottom.

### Screens

Number keys `1`-`7` jump directly:

| # | Screen | What's on it |
|---|---|---|
| **1** | **Home** | KPI cards (cache health, connection, this week's spend + risk count), recent expensive queries, hotkeys (`a` access · `w` who-access · `c` cost · `s` risk · `r` refresh) |
| **2** | **Access** | Seven tabs: Check / Who-access / Create / Roles / Members / Path / Drift. Object-type aware privilege filtering. |
| **3** | **Risk** | Five tabs: Scan / Escalation / Dormant / Direct grants / Unused. Re-scan + CSV / JSON export. |
| **4** | **Cost** | All twelve cost views in one place. Window selector (7d / 30d / 90d), Re-fetch button, drill-downs into per-warehouse / per-user / per-service trends. |
| **5** | **Tune** | Query optimiser. Three-pane: SQL with syntax highlighting on the left; Heuristics / Native insights / Operator tree / Expensive ops / AI on the right. |
| **6** | **Reports** | Generate Full / Cost-only / User-access reports with live markdown preview + Save. |
| **7** | **Refresh** | State counts, refresh actions, connection diagnostics, streaming log. |

### Navigation

| Key | Action |
|---|---|
| `Tab` / `Shift-Tab` | Cycle focus between widgets |
| `Enter` | Activate (button press, fire query, open Select dropdown, expand tree node) |
| `↑` / `↓` | Navigate within lists / tables / dropdowns / trees |
| `Esc` | Close drill-downs / cancel running workers / blur input (vim mode) |
| `1`-`7` | Jump to screen by number |
| `Ctrl-P` | Command palette (switch themes, change profile, etc.) |
| `q` | Quit |

### Vim mode *(optional)*

Pass `--vim` or set `vim: true` in your profile config:

| Key | Action | Where |
|---|---|---|
| `j` / `k` | Cursor down / up | Lists, tables, trees |
| `g` / `G` | Top / bottom | Same |
| `h` / `l` | Collapse / expand | Tree nodes |
| `Ctrl-d` / `Ctrl-u` | Half-page down / up | Any scrollable |
| `Esc` | Blur the focused Input | Lets `j`/`k` navigate again after typing |

Typing characters into form fields still works as expected — Input widgets consume keypresses before the vim bindings fire.

### Themes

Two branded themes ship with the app: `snowglobe-dark` (default) and `snowglobe-light`. Open the command palette with **`Ctrl-P`**, type `theme`, and pick any — Textual's built-ins (`nord`, `monokai`, `dracula`, `catppuccin-*`, etc.) are also listed.

To customise colours directly, edit `snowglobe/tui/styles.tcss` (uses Textual CSS variables — `$primary`, `$accent`, `$background`, etc.).

---

## The interactive shell

`snowglobe shell` drops you into the REPL. All commands support fuzzy tab-completion on usernames, roles, and object FQNs.

| Command | Description |
|---|---|
| `check` | Guided wizard — covers all seven access-style checks step by step |
| `roles <user>` | Direct + inherited roles for a user |
| `members <role>` | Direct + inherited users for a role |
| `path <from> <to>` | Inheritance paths between two roles |
| `escalation <role>` | Can this role reach admin privileges? |
| `scan` | Full privilege-escalation scan with risk scoring; `--csv` / `--json` export |
| `cost` | Cost wizard, or use sub-verbs: `cost summary`, `cost warehouses`, `cost users`, `cost ai`, `cost queries`, `cost trend`, `cost storage`, `cost budget`, `cost replication`, `cost mv` |
| `optimize <query_id>` | Run the optimiser on a specific query |
| `drift` | Show access changes since last refresh (or `--days N`) |
| `unused` | Find roles with data privileges but no recent activity |
| `report <user>` | Markdown access report for a user |
| `report full` / `report cost` | Cost / AI / storage / top queries report saved to `.md` |
| `refresh` | Refresh cached state from Snowflake (`--full` for a complete rebuild) |
| `status` | Current working state + cache age |
| `debug` | Connection diagnostics |
| `help` / `?` | List commands |
| `use role <name>` / `use user <name>` | Set the active role / user for subsequent commands |
| `access` / `whoaccess` / `create` | Direct shortcuts that skip the wizard |
| `exit` | Quit |

---

## Headless CLI

For CI, cron, and scripts. Output formats: `--output table|json` plus per-command `--csv <path>`.

| Command | Description |
|---|---|
| `snowglobe` (no args) | Launch the TUI (the default; falls back to `shell` if Textual isn't installed) |
| `snowglobe tui [--vim]` | Launch the TUI explicitly (errors out if Textual isn't installed) |
| `snowglobe shell` | Launch the REPL shell |
| `snowglobe refresh [--full]` | Incremental (default) or full state refresh |
| `snowglobe debug` | Connection diagnostics (eight-step checklist) |
| `snowglobe access check` | Explain access for a user / role on an object |
| `snowglobe access create` | Where can a role create objects? |
| `snowglobe access whoaccess` | Reverse lookup — who can access this object? |
| `snowglobe cost summary` | Account spend by service type |
| `snowglobe cost warehouses` | Per-warehouse credit breakdown |
| `snowglobe cost users` | Complete cost per user (warehouse + Cortex) |
| `snowglobe cost ai` | AI/ML token costs by service |
| `snowglobe cost ai-users` | AI costs per user with service split |
| `snowglobe cost queries` | Top expensive queries by credits or bytes |
| `snowglobe cost trend` | Daily spend trend with Δ % and rolling 7-day average |
| `snowglobe cost storage` | Per-DB storage with estimated monthly cost |
| `snowglobe cost services` | Pipes / serverless tasks / SPCS / clustering / search optimisation |
| `snowglobe cost budget` | Snowflake-native budget status |
| `snowglobe cost replication` | Replication credits |
| `snowglobe cost mv` | Materialized-view refresh credits |
| `snowglobe optimize query --query-id <id>` | Full query analysis + Cortex AI suggestion |
| `snowglobe optimize top-queries [--analyze]` | List top expensive queries; optionally analyse each |
| `snowglobe report full` | Generate the full markdown report |
| `snowglobe report cost` | Cost-only markdown report |
| `snowglobe report queries` | Top-queries CSV export |

### Global options

- `--profile <name>` — connection profile (default: `default`)
- `--role <name>` — override the role from the profile
- `--output table|json` — output format (per-command `--csv <path>` also available where it makes sense)
- `--verbose` / `-v` — verbose output

---

## Security

Snowglobe is **read-only by design** — its guiding principle is that it earns trust by never touching production state.

- The Snowflake connection layer actively blocks `CREATE`, `ALTER`, `DROP`, `GRANT`, `REVOKE`, and `TRUNCATE` statements before they reach Snowflake.
- All metadata is fetched via bulk queries against `SNOWFLAKE.ACCOUNT_USAGE` (and `ORGANIZATION_USAGE.RATE_SHEET_DAILY` if available, for accurate storage rates).
- All data stays in your environment. No telemetry, no callbacks.
- Credentials are read from the local config file and never logged.
- Cortex AI calls run inside your Snowflake account via `AI_COMPLETE`; the SQL and operator stats never leave Snowflake.

---

## How it works

```
TUI / Shell / Headless CLI
   │
   ▼
Service layer
  AccessService · RiskService · CostService · QueryOptimizerService · ReportService
   │
   ▼
Engines
  AccessResolver · AccessExplainer · QueryOptimizerEngine · CortexOptimizer
   │      ◄── Graphs (RoleGraph / UserGraph)
   ▼
Collectors
  AccessCollector · QueryCollector · QueryProfileCollector
   │
   ▼
Snowflake ACCOUNT_USAGE / GET_QUERY_OPERATOR_STATS / Cortex AI_COMPLETE
   │
   ▼
Local SQLite cache  (~/.snowglobe/state/snowglobe.db)
```

The local cache holds grants, role-inheritance edges, user-role assignments, and cost snapshots in indexed tables. Refresh uses watermarks on `MODIFIED_ON` / `DELETED_ON` to fetch only changed rows.

For the deeper architecture story see `SPEC.md`; for the TUI design and rationale see `doc.md`.

---

## Limitations

- **`ACCOUNT_USAGE` has up to ~45 minutes of latency** — very recent grant or query changes won't appear until the next refresh.
- **STREAMLIT, NOTEBOOK, DYNAMIC TABLE, ALERT, TAG, SECRET** grants aren't in `GRANTS_TO_ROLES`; Snowglobe falls back to live `SHOW GRANTS ON` for those types (slower, but works).
- **Future grants are not tracked** — only relevant for governance / audit, not for checking existing object access.
- **`snowglobe diff access` (headless)** is the one stub left. Drift detection works via the TUI's Drift tab and via the shell's `drift` command; only the dedicated `diff access` CLI subcommand isn't wired yet.
- **No light terminal optimisation** — the dark theme is the primary; `snowglobe-light` exists but accent colours haven't been individually tuned for light backgrounds.

---

## Contributing

Pull requests and issues are welcome on [GitHub](https://github.com/jcolethornton/snowglobe).

---

## License

Apache-2.0 © 2025 Jaryd Thornton. See `LICENSE` for the full text.
