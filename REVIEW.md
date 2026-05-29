# Snowglobe Pre-Release Review

## Test Suite Results

57/58 tests pass. The one failure is structural:

```
FAILED tests/test_tui_tune.py::test_tune_screen_renders_real_engine_output
  ModuleNotFoundError: No module named 'textual'
```

The test imports `SnowglobeApp` at the top of the test file, which triggers a hard import of `textual` — an optional dependency. This test will fail for any user who runs `pytest tests/` without installing `snowglobe[tui]`. It should guard with `pytest.importorskip("textual")`.

---

## Issue Tracker

| # | Severity | Status | File | Issue |
|---|----------|--------|------|-------|
| 1 | **Critical** | ✅ Fixed | `core/cost_service.py:179,273,336` | Cortex UNION ALL crashes on accounts without Cortex features |
| 2 | **Critical** | ✅ Fixed | `core/cost_service.py:185,476,584` | `QUERY_ATTRIBUTION_HISTORY` not available everywhere |
| 3 | **High** | Open | `collectors/access.py:622`, `cost_service.py:565,584` | SQL injection via identifier embedding |
| 4 | **High** | Open | `engines/access/resolver.py:60` | Duplicate access paths for multi-role users |
| 5 | **High** | Open | `core/cost_service.py:250` / `state/db.py:423` | `QUERY_COUNT` silently missing from cached user data |
| 6 | **High** | Open | `graphs/user_graph.py:15` | Mutable default argument `{}` in `UserGraph.__init__` |
| 7 | **Medium** | Open | `tests/test_tui_tune.py:129` | Hard TUI import causes test failure without `[tui]` extra |
| 8 | **Medium** | Open | `cli/context.py:36` | `connect()` unsafe if called before `load_profile()` |
| 9 | **Medium** | Open | `engines/ai/cortex_optimizer.py:9` | Hardcoded model not available in all Snowflake regions |
| 10 | **Medium** | Open | `core/cost_service.py:103` | `DAYS_ACTIVE` always blank from cache |
| 11 | **Medium** | Open | Multiple | No startup validation of ACCOUNT_USAGE access |

---

## Detailed Findings

### #1 — Critical: AI/Cortex UNION ALL queries fail on accounts without those features

`get_user_breakdown` (`cost_service.py:179`) and `get_ai_costs` (`cost_service.py:273`) both use
`UNION ALL` across seven Cortex-specific views:

```
CORTEX_AI_FUNCTIONS_USAGE_HISTORY
CORTEX_ANALYST_USAGE_HISTORY
CORTEX_AGENT_USAGE_HISTORY
CORTEX_CODE_CLI_USAGE_HISTORY
CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY
CORTEX_CODE_DESKTOP_USAGE_HISTORY
SNOWFLAKE_INTELLIGENCE_USAGE_HISTORY
```

If **any one** of these views doesn't exist on the account — which is true for any account that
hasn't enabled Cortex features, or is on an older Snowflake tier, or is in a region where these
features aren't GA — the entire query fails with an object-does-not-exist error. `get_ai_costs_by_user`
(`cost_service.py:336`) has the same problem.

**Fix:** Query each Cortex view individually with `try/except` and union the results in Python.

---

### #2 — Critical: `QUERY_ATTRIBUTION_HISTORY` not available on all accounts

`get_user_breakdown` (`cost_service.py:185`), `get_top_queries` (`cost_service.py:476`), and
`get_user_detail` (`cost_service.py:584`) all depend on
`SNOWFLAKE.ACCOUNT_USAGE.QUERY_ATTRIBUTION_HISTORY`. This view requires Snowflake's Query
Attribution feature, which is opt-in and is not enabled on Standard tier or older accounts. Users
without it get an unhandled error when clicking "Users" or "Top queries" in the TUI, or running
the equivalent CLI commands.

**Fix:** Wrap in `try/except` and fall back to `QUERY_HISTORY` (which is universally available)
for warehouse credits and query counts.

---

### #3 — High: SQL injection via identifier embedding

Multiple methods build SQL via string interpolation without parameterization. While the DDL check
protects against mutation, identifiers can contain single quotes in some Snowflake configurations
(e.g., a database named `O'REILLY`), which breaks queries:

- `collectors/access.py:622-627` — object name parts (catalog, schema, name) embedded directly
- `collectors/access.py:539-544` — privilege string embedded directly
- `cost_service.py:565` — `warehouse_name` embedded directly
- `cost_service.py:584` — `user_name` embedded directly
- `cost_service.py:540-545` — `service_type` embedded directly

---

### #4 — High: `all_access_paths_for_user` generates duplicate paths

In `engines/access/resolver.py:60-76`, the outer loop iterates over a user's direct roles, but
inside calls `self.user_graph.effective_roles(username, self.role_graph)` which returns ALL
effective roles for the user across ALL their direct roles. So for a user with 2 direct roles A
and B, each iteration computes the full set `{A, B, all ancestors}`, causing every grant to be
processed twice. Users with many direct roles will see duplicate paths and doubled results.

---

### #5 — High: `QUERY_COUNT` missing from cached user breakdown

`get_user_breakdown` returns a `QUERY_COUNT` column in its live SQL result (`cost_service.py:250`),
but `save_cost_user_snapshot` (`state/db.py:423`) doesn't persist that column, and
`get_cost_user_cache` doesn't return it. The TUI handles this gracefully with
`row.get("QUERY_COUNT", 0)` (so it won't crash), but users who have the cache warm will always
see 0 in the QUERIES column — silently wrong data.

---

### #6 — High: Mutable default argument in `UserGraph`

`user_graph.py:15`:
```python
def __init__(self, assigned_roles: Dict[str, List[str]] = {}, **args):
```
The default `{}` is shared across all instances. If `UserGraph()` is ever called without arguments
and the dict is later mutated, all no-arg instances see the mutation. Not triggered by current
call sites (all pass data), but a latent bug.

---

### #7 — Medium: `test_tui_tune.py` needs `importorskip`

The test hardcodes an unconditional import of the TUI module at line 129. Should add
`pytest.importorskip("textual")` at the top or use a skip marker. As-is, running `pytest tests/`
on a base install always fails.

---

### #8 — Medium: `context.connect()` unsafe before `load_profile()`

`cli/context.py:36-47`: `connect()` accesses `self.profile["account"]` without checking that
`load_profile()` was called first. If a caller skips `load_profile()`, this throws
`TypeError: 'NoneType' object is not subscriptable`. All current callers do call `load_profile()`
first, but this is fragile for future code.

---

### #9 — Medium: Cortex model hardcoded, not available in all Snowflake regions

`engines/ai/cortex_optimizer.py:9` and `core/optimizer.py:81`: Default model is `claude-haiku-4-5`.
Cortex model availability varies by Snowflake region — not all regions have this model. No fallback
and no helpful error message when it isn't available.

---

### #10 — Medium: `DAYS_ACTIVE` always blank from cache

`cost_service.py:103-104`: The cost summary snapshot doesn't store `DAYS_ACTIVE`, so when served
from cache it is always `""`. The headless `cost summary` command displays this column; users who
run the command within 1 hour of their first fetch see blank data.

---

### #11 — Medium: No startup validation of ACCOUNT_USAGE access

No startup check validates that the role has read access to `SNOWFLAKE.ACCOUNT_USAGE`. If the
configured role lacks access, the first `refresh` call fails deep inside the collector with a raw
Snowflake error rather than a helpful message like:
"Your role needs IMPORTED PRIVILEGES ON DATABASE SNOWFLAKE."
