# Snowglobe — Evaluation & Priorities

## Where Snowglobe Provides Real Value

**1. Access path explainability — this is the killer feature.**

Snowflake's native tools (`SHOW GRANTS TO ROLE`, `SHOW GRANTS TO USER`) give you flat lists. They don't answer "why does user X have SELECT on this table?" You have to manually trace role hierarchies yourself. Snowglobe's graph-based resolver with `all_paths()` does this automatically and shows every inheritance chain. This is genuinely painful to do manually in large environments with 50+ roles and database roles.

**2. CREATE privilege visibility.**

Answering "where can this role create tables?" requires manually checking grants across every schema. Snowglobe resolves this with a single command, showing account/database/schema scope with inheritance paths.

**3. Reverse lookup: who can access this object?**

Answering "who has access to this PII table?" requires checking every role's grants and tracing inheritance. Snowglobe's `whoaccess` command does this instantly, showing all roles and users per privilege.

**4. Query cost estimation formula.**

Snowflake doesn't expose per-query credit cost in `QUERY_HISTORY`. You get execution time and warehouse size but have to do the math yourself. The warehouse multiplier formula (`POWER(2, size_index) * seconds / 3600`) is a reasonable approximation that saves repeated mental math.

**5. Heuristic query analysis on operator stats.**

`GET_QUERY_OPERATOR_STATS` is available natively, but it's raw JSON that nobody reads. The 8 heuristic detectors (join explosion, spill, pruning failure, etc.) translate that into actionable English. This is faster than clicking through the Query Profile UI in Snowsight for batch analysis.

---

## Completed Improvements

- [x] ~~Fix test file import error~~ (fixed: `models.enums` → `models.privilege`)
- [x] ~~Fix `CortexOptimizer` malformed SQL~~ (rewritten with proper `AI_COMPLETE` syntax)
- [x] ~~Register `report_app` in `app.py`~~
- [x] ~~Remove unused `Grant` model~~
- [x] ~~Fix `StateManager` relative path~~ (now uses `~/.snowglobe/state/`)
- [x] ~~Shell duplicates command system~~ (unified: one code path for shell + CLI)
- [x] ~~State caching is fragile~~ (added metadata timestamps, staleness warnings, auto-refresh on first run)
- [x] ~~Refresh takes forever~~ (switched from N+1 SHOW commands to bulk ACCOUNT_USAGE queries)
- [x] ~~No connection diagnostics~~ (added `snowglobe debug` command)
- [x] ~~`snowglobe shell shell` is bad UX~~ (now just `snowglobe` with no args launches the shell)
- [x] ~~Limited object types~~ (extended to 27 types including STREAMLIT, NOTEBOOK, DYNAMIC TABLE, ALERT, TAG, SECRET)
- [x] ~~No CREATE privilege checks~~ (added `snowglobe access create` + shell `create` command)
- [x] ~~No standalone refresh~~ (added `snowglobe refresh` command)
- [x] ~~CREATE grants slow (~80s)~~ (cached during refresh for instant lookups)
- [x] ~~Incremental refresh~~ (watermark-based delta merge: ~13s vs ~2.5 min full)
- [x] ~~No reverse lookup~~ (added `whoaccess` command — object-centric access view)
- [x] ~~DATABASE_ROLE key bug~~ (roles like OWN_ROLE correctly keyed as DATABASE_ROLE::DB::ROLE)
- [x] ~~Object access checks slow (~80s)~~ (migrated to SQLite — all 782K grants cached, instant lookups)
- [x] ~~JSON state fragile & large~~ (migrated to SQLite: single `snowglobe.db`, indexed, ACID)
- [x] ~~STREAMLIT/NOTEBOOK/etc not in object completions~~ (added `extra_objects` table + SHOW enumeration during refresh)
- [x] ~~Empty object_name crashes~~ (validates and exits gracefully)
- [x] ~~Privilege suggestions not context-aware~~ (per-object-type privilege lists)
- [x] ~~Shell UX unintuitive~~ (added guided `check` wizard, `roles`, `members`, `path` commands, `?` helper)
- [x] ~~No tab-completion for direct commands~~ (added intellisense for `roles`, `members`, `path`, `use`)

---

## Remaining Priorities

**Access explainability (core value):**

- [ ] Implement `diff access` — detect grant drift over time (snapshot comparison)
- [ ] Add ownership chain visualization
- [ ] Add future grants collection (low priority — only needed for governance/audit)

**Cost/Optimizer (decide: improve or cut):**

- [ ] Cost: Implement real attribution (by user, warehouse, role, query type with baselines) or remove the promise
- [ ] AI optimizer: Enrich context (feed DDL, table stats, data distribution) or remove it
- [ ] No `cost summary`, `cost delta`, or `daily` command exists

**Infrastructure:**

- [ ] Implement `report` commands (audit-ready output for compliance teams)
- [ ] Add proper test suite with fixtures (not just one stub test)
- [ ] Add `--format csv` output support
- [ ] `diff access` is still a stub

---

## Known Limitations

1. **ACCOUNT_USAGE has up to 45 min latency** — acceptable for a caching tool but means very recent changes won't appear.
2. **STREAMLIT/NOTEBOOK/DYNAMIC TABLE/ALERT/TAG/SECRET** grants not cached in SQLite — uses live `SHOW GRANTS ON` fallback (slower but works).
3. **Future grants not tracked** — only relevant for governance/audit, not for checking existing object access.
4. **SQLite DB is ~313MB** — acceptable for enterprise use, could be optimized by dropping redundant indexes.
