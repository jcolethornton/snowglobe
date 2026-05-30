"""
Cost analysis service for Snowglobe.

Queries ACCOUNT_USAGE views for comprehensive cost attribution across all Snowflake services.
Implements a 1-hour TTL cache via SQLite — repeated calls within the hour serve from cache.
Use refresh=True to force a fresh query to Snowflake.
"""
import pandas as pd
from datetime import date, datetime, timezone

from snowglobe.state.db import StateDB

def _sq(value: str) -> str:
    """Escape a string for embedding in a SQL single-quoted literal."""
    return value.replace("'", "''")


CACHE_TTL_SECONDS = 3600  # 1 hour
DEFAULT_STORAGE_RATE_PER_TB = 23.0  # On-demand standard rate $/TB/month

_NOTE_NO_QUERY_ATTRIBUTION = (
    "Warehouse credits unavailable — Query Attribution is not enabled on this account. "
    "Showing query counts only. Enable it under Admin → Cost Management → Query Attribution."
)
_NOTE_CORTEX_UNAVAILABLE = (
    "Some Cortex AI features are not available on this account or region — "
    "affected credits show as 0."
)
_NOTE_TOP_QUERIES_NO_CREDITS = (
    "Query Attribution is not enabled — showing top queries by runtime. "
    "Credit columns are unavailable."
)
_NOTE_USER_DETAIL_NO_CREDITS = (
    "Query Attribution is not enabled — showing warehouse usage by query count only. "
    "Credit columns are unavailable."
)


class CostService:
    """Provides cost analysis across all Snowflake cost sources with caching."""

    def __init__(self, context):
        self.context = context
        self.context.load_profile()
        self.db = StateDB()
        self._storage_rate: float | None = None

    def _is_fresh(self, cache_key: str) -> bool:
        """Check if a cache entry exists and is less than 1 hour old."""
        age = self.db.get_cost_cache_age(cache_key)
        if age is None:
            return False
        return age < CACHE_TTL_SECONDS

    def _cache_age_minutes(self, cache_key: str) -> int | None:
        """Return cache age in minutes, or None if not cached."""
        age = self.db.get_cost_cache_age(cache_key)
        if age is None:
            return None
        return int(age / 60)

    def _mark_cached(self, cache_key: str):
        """Record the current timestamp for a cache key."""
        self.db.set_metadata(cache_key, datetime.now(timezone.utc).isoformat())

    def get_storage_rate(self) -> float:
        """
        Get the effective storage rate ($/TB/month) from ORGANIZATION_USAGE.RATE_SHEET_DAILY.
        Falls back to DEFAULT_STORAGE_RATE_PER_TB if org-level view is unavailable.
        Result is cached for the session.
        """
        if self._storage_rate is not None:
            return self._storage_rate

        # Check if we have a cached rate in metadata (refreshed daily)
        cached_rate = self.db.get_metadata("storage_rate_per_tb")
        if cached_rate:
            cache_age = self.db.get_cost_cache_age("storage_rate_fetched_at")
            if cache_age is not None and cache_age < 86400:  # 24 hours
                self._storage_rate = float(cached_rate)
                return self._storage_rate

        # Try to fetch from ORGANIZATION_USAGE (requires ORGADMIN or appropriate grants)
        sql = """
        SELECT EFFECTIVE_RATE
        FROM SNOWFLAKE.ORGANIZATION_USAGE.RATE_SHEET_DAILY
        WHERE RATING_TYPE = 'storage'
          AND SERVICE_TYPE = 'storage'
          AND BILLING_TYPE = 'consumption'
          AND IS_ADJUSTMENT = FALSE
        ORDER BY DATE DESC
        LIMIT 1
        """
        conn = self.context.connect()
        try:
            with conn:
                rows = conn.query(sql)
            if rows:
                rate = float(rows[0]["EFFECTIVE_RATE"])
                self._storage_rate = rate
                self.db.set_metadata("storage_rate_per_tb", str(rate))
                self.db.set_metadata("storage_rate_fetched_at", datetime.now(timezone.utc).isoformat())
                return rate
        except Exception:
            pass  # View unavailable — use default

        self._storage_rate = DEFAULT_STORAGE_RATE_PER_TB
        return self._storage_rate

    def get_account_summary(self, days: int = 30, refresh: bool = False) -> tuple[pd.DataFrame, int | None]:
        """
        Total account spend by service type over N days.
        Returns (df, cache_age_minutes) — cache_age is None if freshly fetched.
        """
        cache_key = f"cost_summary_{days}d_fetched_at"

        if not refresh and self._is_fresh(cache_key):
            cached = self.db.get_cost_summary_cache()
            if cached:
                df = pd.DataFrame(cached)
                df["CREDITS"] = df["CREDITS"].astype(float)
                df = df.sort_values("CREDITS", ascending=False).reset_index(drop=True)
                total = df["CREDITS"].sum()
                df["PCT"] = (df["CREDITS"] / total * 100).round(1)
                return df, self._cache_age_minutes(cache_key)

        # Cache miss — query Snowflake
        sql = f"""
        SELECT SERVICE_TYPE,
               ROUND(SUM(CREDITS_BILLED), 2) AS credits,
               COUNT(DISTINCT USAGE_DATE) AS days_active
        FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY
        WHERE USAGE_DATE >= DATEADD(day, -{days}, CURRENT_DATE())
        GROUP BY 1
        ORDER BY 2 DESC
        """
        conn = self.context.connect()
        with conn:
            rows = conn.query(sql)
        df = pd.DataFrame(rows)
        if not df.empty:
            df["CREDITS"] = df["CREDITS"].astype(float)
            total = df["CREDITS"].sum()
            df["PCT"] = (df["CREDITS"] / total * 100).round(1)
            # Save to cache
            today = date.today().isoformat()
            self.db.save_cost_summary_snapshot(today, df.to_dict("records"))
            self._mark_cached(cache_key)
        return df, None

    def get_warehouse_breakdown(self, days: int = 30, refresh: bool = False) -> tuple[pd.DataFrame, int | None]:
        """
        Cost per warehouse over N days.
        Returns (df, cache_age_minutes).
        """
        cache_key = f"cost_warehouses_{days}d_fetched_at"

        if not refresh and self._is_fresh(cache_key):
            cached = self.db.get_cost_warehouse_cache()
            if cached:
                df = pd.DataFrame(cached)
                df = df.sort_values("TOTAL_CREDITS", ascending=False).reset_index(drop=True)
                return df, self._cache_age_minutes(cache_key)

        sql = f"""
        SELECT WAREHOUSE_NAME,
               ROUND(SUM(CREDITS_USED), 2) AS TOTAL_CREDITS,
               ROUND(SUM(CREDITS_USED_COMPUTE), 2) AS COMPUTE_CREDITS,
               ROUND(SUM(CREDITS_USED_CLOUD_SERVICES), 2) AS CLOUD_CREDITS,
               ROUND(AVG(CREDITS_USED) * 24, 2) AS AVG_DAILY_CREDITS
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
        WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
        GROUP BY 1
        ORDER BY 2 DESC
        """
        conn = self.context.connect()
        with conn:
            rows = conn.query(sql)
        df = pd.DataFrame(rows)
        if not df.empty:
            today = date.today().isoformat()
            self.db.save_cost_warehouse_snapshot(today, df.to_dict("records"))
            self._mark_cached(cache_key)
        return df, None

    # --- Resilient Cortex / QUERY_ATTRIBUTION_HISTORY helpers ---

    def _query_warehouse_costs(self, conn, days: int) -> tuple[pd.DataFrame, bool]:
        """
        Per-user warehouse costs.  Returns (df, credits_available).

        credits_available=True  → QUERY_ATTRIBUTION_HISTORY succeeded; WAREHOUSE_CREDITS
                                   and QA_CREDITS are real attributed values.
        credits_available=False → fell back to QUERY_HISTORY; WAREHOUSE_CREDITS and
                                   QA_CREDITS are 0 (Query Attribution not enabled).
        """
        _empty = pd.DataFrame(columns=["USER_NAME", "WAREHOUSE_CREDITS", "QA_CREDITS", "QUERY_COUNT"])
        try:
            rows = conn.query(f"""
                SELECT USER_NAME,
                       ROUND(SUM(CREDITS_ATTRIBUTED_COMPUTE), 2) AS WAREHOUSE_CREDITS,
                       ROUND(SUM(COALESCE(CREDITS_USED_QUERY_ACCELERATION, 0)), 2) AS QA_CREDITS,
                       COUNT(*) AS QUERY_COUNT
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_ATTRIBUTION_HISTORY
                WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
                GROUP BY 1
            """)
            return (pd.DataFrame(rows) if rows else _empty, True)
        except Exception:
            pass

        try:
            rows = conn.query(f"""
                SELECT USER_NAME,
                       0.0 AS WAREHOUSE_CREDITS,
                       0.0 AS QA_CREDITS,
                       COUNT(*) AS QUERY_COUNT
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
                  AND EXECUTION_STATUS = 'SUCCESS'
                GROUP BY 1
            """)
            return (pd.DataFrame(rows) if rows else _empty, False)
        except Exception:
            return (_empty, False)

    def _query_cortex_ai_rows(self, conn, days: int) -> tuple[pd.DataFrame, bool]:
        """
        Query every Cortex AI usage view individually.  Returns (df, any_views_missing).

        any_views_missing=True means at least one view raised an exception (view does not
        exist on this account / tier / region).  The DataFrame contains rows only from
        views that did respond — it may still be non-empty if some views exist.
        """
        sources = [
            ("Cortex Functions", f"""
                SELECT u.LOGIN_NAME AS USER_NAME,
                       'Cortex Functions' AS SERVICE,
                       f.credits AS TOKEN_CREDITS
                FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AI_FUNCTIONS_USAGE_HISTORY f
                INNER JOIN SNOWFLAKE.ACCOUNT_USAGE.USERS u ON u.USER_ID = f.USER_ID
                WHERE f.START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
                  AND f.credits > 0
            """),
            ("Cortex Analyst", f"""
                SELECT USERNAME AS USER_NAME,
                       'Cortex Analyst' AS SERVICE,
                       credits AS TOKEN_CREDITS
                FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_ANALYST_USAGE_HISTORY
                WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
                  AND credits > 0
            """),
            ("Cortex Agent", f"""
                SELECT USER_NAME,
                       'Cortex Agent' AS SERVICE,
                       token_credits AS TOKEN_CREDITS
                FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AGENT_USAGE_HISTORY
                WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
                  AND token_credits > 0
            """),
            ("Cortex Code (CLI)", f"""
                SELECT USER_NAME,
                       'Cortex Code' AS SERVICE,
                       token_credits AS TOKEN_CREDITS
                FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_CLI_USAGE_HISTORY
                WHERE USAGE_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
                  AND token_credits > 0
            """),
            ("Cortex Code (Snowsight)", f"""
                SELECT USER_NAME,
                       'Cortex Code' AS SERVICE,
                       token_credits AS TOKEN_CREDITS
                FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY
                WHERE USAGE_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
                  AND token_credits > 0
            """),
            ("Cortex Code (Desktop)", f"""
                SELECT USER_NAME,
                       'Cortex Code' AS SERVICE,
                       token_credits AS TOKEN_CREDITS
                FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_DESKTOP_USAGE_HISTORY
                WHERE USAGE_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
                  AND token_credits > 0
            """),
            ("Snowflake Intelligence", f"""
                SELECT USER_NAME,
                       'Snowflake Intelligence' AS SERVICE,
                       token_credits AS TOKEN_CREDITS
                FROM SNOWFLAKE.ACCOUNT_USAGE.SNOWFLAKE_INTELLIGENCE_USAGE_HISTORY
                WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
                  AND token_credits > 0
            """),
        ]

        frames = []
        any_missing = False
        for _, sql in sources:
            try:
                rows = conn.query(sql)
                if rows:
                    frames.append(pd.DataFrame(rows))
            except Exception:
                any_missing = True  # view doesn't exist on this account

        if not frames:
            return pd.DataFrame(columns=["USER_NAME", "SERVICE", "TOKEN_CREDITS"]), any_missing
        result = pd.concat(frames, ignore_index=True)
        result["TOKEN_CREDITS"] = result["TOKEN_CREDITS"].astype(float)
        return result, any_missing

    def get_user_breakdown(self, days: int = 7, refresh: bool = False) -> tuple[pd.DataFrame, int | None, str | None]:
        """
        Complete cost per user — combines warehouse attributed credits + all AI token costs.
        Each data source is queried independently so accounts that are missing Cortex views
        or QUERY_ATTRIBUTION_HISTORY still get a meaningful (partial) result.
        Returns (df, cache_age_minutes, note).
        """
        cache_key = f"cost_users_{days}d_fetched_at"

        if not refresh and self._is_fresh(cache_key):
            cached = self.db.get_cost_user_cache()
            if cached:
                df = pd.DataFrame(cached)
                numeric_cols = ["WAREHOUSE_CREDITS", "QA_CREDITS", "QUERY_COUNT",
                                "CORTEX_FUNCTIONS", "CORTEX_ANALYST", "CORTEX_AGENT",
                                "CORTEX_CODE", "SNOWFLAKE_INTELLIGENCE", "TOTAL_CREDITS"]
                for col in numeric_cols:
                    if col in df.columns:
                        df[col] = df[col].astype(float)
                df = df.sort_values("TOTAL_CREDITS", ascending=False).reset_index(drop=True)
                return df, self._cache_age_minutes(cache_key), None

        conn = self.context.connect()
        with conn:
            wh_df, credits_available = self._query_warehouse_costs(conn, days)
            ai_raw, any_missing = self._query_cortex_ai_rows(conn, days)

        # Pivot AI rows to one row per user
        ai_services = ["Cortex Functions", "Cortex Analyst", "Cortex Agent",
                        "Cortex Code", "Snowflake Intelligence"]
        if not ai_raw.empty:
            ai_pivot = (
                ai_raw.groupby(["USER_NAME", "SERVICE"])["TOKEN_CREDITS"]
                .sum()
                .reset_index()
                .pivot(index="USER_NAME", columns="SERVICE", values="TOKEN_CREDITS")
                .reset_index()
            )
            for svc in ai_services:
                if svc not in ai_pivot.columns:
                    ai_pivot[svc] = 0.0
        else:
            ai_pivot = pd.DataFrame(columns=["USER_NAME"] + ai_services)

        ai_pivot = ai_pivot.rename(columns={
            "Cortex Functions":     "CORTEX_FUNCTIONS",
            "Cortex Analyst":       "CORTEX_ANALYST",
            "Cortex Agent":         "CORTEX_AGENT",
            "Cortex Code":          "CORTEX_CODE",
            "Snowflake Intelligence": "SNOWFLAKE_INTELLIGENCE",
        })

        # Full outer join on USER_NAME
        df = wh_df.merge(ai_pivot, on="USER_NAME", how="outer")

        ai_cols = ["CORTEX_FUNCTIONS", "CORTEX_ANALYST", "CORTEX_AGENT",
                   "CORTEX_CODE", "SNOWFLAKE_INTELLIGENCE"]
        for col in ["WAREHOUSE_CREDITS", "QA_CREDITS", "QUERY_COUNT"] + ai_cols:
            if col not in df.columns:
                df[col] = 0.0
            df[col] = df[col].fillna(0)

        df["TOTAL_CREDITS"] = (
            df["WAREHOUSE_CREDITS"] + df["QA_CREDITS"] + df[ai_cols].sum(axis=1)
        ).round(2)

        df = df.sort_values("TOTAL_CREDITS", ascending=False).head(30).reset_index(drop=True)

        if not df.empty:
            today = date.today().isoformat()
            self.db.save_cost_user_snapshot(today, df.to_dict("records"))
            self._mark_cached(cache_key)

        parts = []
        if not credits_available:
            parts.append(_NOTE_NO_QUERY_ATTRIBUTION)
        if any_missing:
            parts.append(_NOTE_CORTEX_UNAVAILABLE)
        note = " ".join(parts) if parts else None

        return df, None, note

    def get_ai_costs(self, days: int = 30, refresh: bool = False) -> tuple[pd.DataFrame, int | None, str | None]:
        """
        AI/ML token costs aggregated by service type.
        Each Cortex view is queried independently — missing views are skipped rather
        than failing the whole result.
        Returns (df, cache_age_minutes, note).
        """
        cache_key = f"cost_ai_{days}d_fetched_at"

        if not refresh and self._is_fresh(cache_key):
            cached = self.db.get_json_cache(f"cost_ai_{days}d_data")
            if cached:
                df = pd.DataFrame(cached)
                df["TOTAL_CREDITS"] = df["TOTAL_CREDITS"].astype(float)
                return df, self._cache_age_minutes(cache_key), None

        conn = self.context.connect()
        with conn:
            ai_raw, any_missing = self._query_cortex_ai_rows(conn, days)

        note = _NOTE_CORTEX_UNAVAILABLE if any_missing else None

        if ai_raw.empty:
            return pd.DataFrame(), None, note

        df = (
            ai_raw.groupby("SERVICE")
            .agg(TOTAL_CREDITS=("TOKEN_CREDITS", "sum"), REQUEST_COUNT=("TOKEN_CREDITS", "count"))
            .reset_index()
            .rename(columns={"SERVICE": "SERVICE"})
            .sort_values("TOTAL_CREDITS", ascending=False)
            .reset_index(drop=True)
        )
        df["TOTAL_CREDITS"] = df["TOTAL_CREDITS"].round(2).astype(float)
        total = df["TOTAL_CREDITS"].sum()
        df["PCT"] = (df["TOTAL_CREDITS"] / total * 100).round(1) if total > 0 else 0.0

        self.db.set_json_cache(f"cost_ai_{days}d_data", df.to_dict("records"))
        self._mark_cached(cache_key)
        return df, None, note

    def get_ai_costs_by_user(self, days: int = 30, refresh: bool = False) -> tuple[pd.DataFrame, int | None, str | None]:
        """
        AI/ML token costs per user with per-service breakdown.
        Each Cortex view is queried independently — missing views contribute zero.
        Returns (df, cache_age_minutes, note).
        """
        cache_key = f"cost_ai_users_{days}d_fetched_at"

        if not refresh and self._is_fresh(cache_key):
            cached = self.db.get_json_cache(f"cost_ai_users_{days}d_data")
            if cached:
                df = pd.DataFrame(cached)
                ai_cols = ["CORTEX_FUNCTIONS", "CORTEX_ANALYST", "CORTEX_AGENT",
                           "CORTEX_CODE", "SNOWFLAKE_INTELLIGENCE", "TOTAL_CREDITS"]
                for col in ai_cols:
                    if col in df.columns:
                        df[col] = df[col].astype(float)
                return df, self._cache_age_minutes(cache_key), None

        conn = self.context.connect()
        with conn:
            ai_raw, any_missing = self._query_cortex_ai_rows(conn, days)

        note = _NOTE_CORTEX_UNAVAILABLE if any_missing else None

        if ai_raw.empty:
            return pd.DataFrame(), None, note

        ai_services = ["Cortex Functions", "Cortex Analyst", "Cortex Agent",
                        "Cortex Code", "Snowflake Intelligence"]
        pivot = (
            ai_raw.groupby(["USER_NAME", "SERVICE"])["TOKEN_CREDITS"]
            .sum()
            .reset_index()
            .pivot(index="USER_NAME", columns="SERVICE", values="TOKEN_CREDITS")
            .reset_index()
        )
        for svc in ai_services:
            if svc not in pivot.columns:
                pivot[svc] = 0.0

        pivot = pivot.rename(columns={
            "Cortex Functions":       "CORTEX_FUNCTIONS",
            "Cortex Analyst":         "CORTEX_ANALYST",
            "Cortex Agent":           "CORTEX_AGENT",
            "Cortex Code":            "CORTEX_CODE",
            "Snowflake Intelligence":  "SNOWFLAKE_INTELLIGENCE",
        })

        ai_cols = ["CORTEX_FUNCTIONS", "CORTEX_ANALYST", "CORTEX_AGENT",
                   "CORTEX_CODE", "SNOWFLAKE_INTELLIGENCE"]
        for col in ai_cols:
            pivot[col] = pivot[col].fillna(0).round(2)

        pivot["TOTAL_CREDITS"] = pivot[ai_cols].sum(axis=1).round(2)
        pivot = pivot.sort_values("TOTAL_CREDITS", ascending=False).head(30).reset_index(drop=True)

        self.db.set_json_cache(f"cost_ai_users_{days}d_data", pivot.to_dict("records"))
        self._mark_cached(cache_key)
        return pivot, None, note

    def get_service_breakdown(self, days: int = 30, refresh: bool = False) -> tuple[pd.DataFrame, int | None]:
        """
        Non-warehouse, non-AI service costs.
        Returns (df, cache_age_minutes).
        """
        cache_key = f"cost_services_{days}d_fetched_at"

        if not refresh and self._is_fresh(cache_key):
            cached = self.db.get_json_cache(f"cost_services_{days}d_data")
            if cached:
                df = pd.DataFrame(cached)
                return df, self._cache_age_minutes(cache_key)

        sql = f"""
        WITH pipe_costs AS (
            SELECT 'Snowpipe' AS service,
                   PIPE_NAME AS resource_name,
                   ROUND(SUM(CREDITS_USED), 2) AS credits
            FROM SNOWFLAKE.ACCOUNT_USAGE.PIPE_USAGE_HISTORY
            WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
            GROUP BY 2
        ),
        task_costs AS (
            SELECT 'Serverless Task' AS service,
                   DATABASE_NAME || '.' || SCHEMA_NAME || '.' || TASK_NAME AS resource_name,
                   ROUND(SUM(CREDITS_USED), 2) AS credits
            FROM SNOWFLAKE.ACCOUNT_USAGE.SERVERLESS_TASK_HISTORY
            WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
            GROUP BY 2
        ),
        spcs_costs AS (
            SELECT 'Container Services' AS service,
                   COMPUTE_POOL_NAME AS resource_name,
                   ROUND(SUM(CREDITS_USED), 2) AS credits
            FROM SNOWFLAKE.ACCOUNT_USAGE.SNOWPARK_CONTAINER_SERVICES_HISTORY
            WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
            GROUP BY 2
        ),
        clustering_costs AS (
            SELECT 'Auto Clustering' AS service,
                   DATABASE_NAME || '.' || SCHEMA_NAME || '.' || TABLE_NAME AS resource_name,
                   ROUND(SUM(CREDITS_USED), 2) AS credits
            FROM SNOWFLAKE.ACCOUNT_USAGE.AUTOMATIC_CLUSTERING_HISTORY
            WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
            GROUP BY 2
        ),
        search_costs AS (
            SELECT 'Search Optimization' AS service,
                   DATABASE_NAME || '.' || SCHEMA_NAME || '.' || TABLE_NAME AS resource_name,
                   ROUND(SUM(CREDITS_USED), 2) AS credits
            FROM SNOWFLAKE.ACCOUNT_USAGE.SEARCH_OPTIMIZATION_HISTORY
            WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
            GROUP BY 2
        )
        SELECT * FROM pipe_costs WHERE credits > 0
        UNION ALL SELECT * FROM task_costs WHERE credits > 0
        UNION ALL SELECT * FROM spcs_costs WHERE credits > 0
        UNION ALL SELECT * FROM clustering_costs WHERE credits > 0
        UNION ALL SELECT * FROM search_costs WHERE credits > 0
        ORDER BY credits DESC
        """
        conn = self.context.connect()
        with conn:
            rows = conn.query(sql)
        df = pd.DataFrame(rows)
        if not df.empty:
            self.db.set_json_cache(f"cost_services_{days}d_data", df.to_dict("records"))
            self._mark_cached(cache_key)
        return df, None

    def get_top_queries(self, days: int = 7, limit: int = 10, sort_by: str = "credits", refresh: bool = False) -> tuple[pd.DataFrame, int | None, str | None]:
        """
        Top expensive individual queries. Uses QUERY_ATTRIBUTION_HISTORY for attributed
        compute credits where available; falls back to QUERY_HISTORY (ranked by elapsed
        time or bytes scanned) for accounts without Query Attribution enabled.
        Never cached — always fresh (results are per-query, not aggregate).
        Returns (df, None, note).
        """
        conn = self.context.connect()

        # Preferred: attributed compute credits
        try:
            sort_col = "CREDITS" if sort_by == "credits" else "GB_SCANNED"
            sql = f"""
            SELECT
                a.QUERY_ID,
                a.USER_NAME,
                a.WAREHOUSE_NAME,
                ROUND(a.CREDITS_ATTRIBUTED_COMPUTE, 4) AS CREDITS,
                ROUND(COALESCE(a.CREDITS_USED_QUERY_ACCELERATION, 0), 4) AS QA_CREDITS,
                q.QUERY_TYPE,
                LEFT(q.QUERY_TEXT, 80) AS QUERY_PREVIEW,
                ROUND(q.TOTAL_ELAPSED_TIME / 1000, 1) AS SECONDS,
                ROUND(q.BYTES_SCANNED / 1e9, 2) AS GB_SCANNED
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_ATTRIBUTION_HISTORY a
            LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q ON a.QUERY_ID = q.QUERY_ID
            WHERE a.START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
            ORDER BY {sort_col} DESC
            LIMIT {limit}
            """
            with conn:
                rows = conn.query(sql)
            return pd.DataFrame(rows), None, None
        except Exception:
            pass

        # Fallback: QUERY_HISTORY — credits always 0, sort by elapsed time or scan size
        sort_col = "SECONDS" if sort_by == "credits" else "GB_SCANNED"
        sql_fallback = f"""
        SELECT
            QUERY_ID,
            USER_NAME,
            WAREHOUSE_NAME,
            0.0 AS CREDITS,
            0.0 AS QA_CREDITS,
            QUERY_TYPE,
            LEFT(QUERY_TEXT, 80) AS QUERY_PREVIEW,
            ROUND(TOTAL_ELAPSED_TIME / 1000, 1) AS SECONDS,
            ROUND(BYTES_SCANNED / 1e9, 2) AS GB_SCANNED
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
          AND EXECUTION_STATUS = 'SUCCESS'
          AND QUERY_TYPE = 'SELECT'
        ORDER BY {sort_col} DESC
        LIMIT {limit}
        """
        conn2 = self.context.connect()
        with conn2:
            rows = conn2.query(sql_fallback)
        return pd.DataFrame(rows), None, _NOTE_TOP_QUERIES_NO_CREDITS

    # --- Daily trend ---

    def get_daily_trend(self, days: int = 30, refresh: bool = False) -> tuple[pd.DataFrame, int | None]:
        """
        Daily credit spend with day-over-day delta and 7-day rolling average.
        Uses METERING_DAILY_HISTORY for per-day granularity.
        Returns (df, cache_age_minutes).
        """
        cache_key = f"cost_trend_{days}d_fetched_at"

        if not refresh and self._is_fresh(cache_key):
            cached = self.db.get_cost_trend_cache(days)
            if cached:
                df = pd.DataFrame(cached)
                df["total_credits"] = df["total_credits"].astype(float)
                # Compute delta_pct from cached data
                df["delta_pct"] = df["total_credits"].pct_change() * 100
                df = df.rename(columns={
                    "snapshot_date": "DATE",
                    "total_credits": "CREDITS",
                    "rolling_7d_avg": "ROLLING_7D_AVG",
                    "delta_pct": "DELTA_PCT",
                })
                return df, self._cache_age_minutes(cache_key)

        sql = f"""
        SELECT USAGE_DATE AS dt,
               ROUND(SUM(CREDITS_BILLED), 2) AS total_credits
        FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY
        WHERE USAGE_DATE >= DATEADD(day, -{days}, CURRENT_DATE())
        GROUP BY 1
        ORDER BY 1
        """
        conn = self.context.connect()
        with conn:
            rows = conn.query(sql)
        df = pd.DataFrame(rows)
        if not df.empty:
            df.columns = ["DATE", "CREDITS"]
            df["CREDITS"] = df["CREDITS"].astype(float)
            df["ROLLING_7D_AVG"] = df["CREDITS"].rolling(window=7, min_periods=1).mean().round(2)
            df["DELTA_PCT"] = (df["CREDITS"].pct_change() * 100).round(1)
            # Save to cache
            cache_rows = [
                {"snapshot_date": str(row["DATE"]), "total_credits": row["CREDITS"], "rolling_7d_avg": row["ROLLING_7D_AVG"]}
                for _, row in df.iterrows()
            ]
            self.db.save_cost_trend_snapshot(cache_rows)
            self._mark_cached(cache_key)
        return df, None

    # --- Drill-down detail methods ---

    def get_service_daily_trend(self, service_type: str, days: int = 30) -> pd.DataFrame:
        """Daily credits for a specific service type."""
        sql = f"""
        SELECT USAGE_DATE AS DATE,
               ROUND(SUM(CREDITS_BILLED), 2) AS CREDITS
        FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY
        WHERE SERVICE_TYPE = '{_sq(service_type)}'
          AND USAGE_DATE >= DATEADD(day, -{days}, CURRENT_DATE())
        GROUP BY 1
        ORDER BY 1
        """
        conn = self.context.connect()
        with conn:
            rows = conn.query(sql)
        df = pd.DataFrame(rows)
        if not df.empty:
            df["CREDITS"] = df["CREDITS"].astype(float)
        return df

    def get_warehouse_daily_trend(self, warehouse_name: str, days: int = 30) -> pd.DataFrame:
        """Daily credits for a specific warehouse."""
        sql = f"""
        SELECT DATE_TRUNC('day', START_TIME)::DATE AS DATE,
               ROUND(SUM(CREDITS_USED), 2) AS CREDITS
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
        WHERE WAREHOUSE_NAME = '{_sq(warehouse_name)}'
          AND START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
        GROUP BY 1
        ORDER BY 1
        """
        conn = self.context.connect()
        with conn:
            rows = conn.query(sql)
        df = pd.DataFrame(rows)
        if not df.empty:
            df["CREDITS"] = df["CREDITS"].astype(float)
        return df

    def get_user_detail(self, user_name: str, days: int = 7) -> tuple[pd.DataFrame, str | None]:
        """
        Per-warehouse credit breakdown for a specific user.
        Uses QUERY_ATTRIBUTION_HISTORY where available; falls back to QUERY_HISTORY
        (credits will be 0) for accounts without Query Attribution enabled.
        Returns (df, note).
        """
        safe_user = user_name.replace("'", "''")
        conn = self.context.connect()

        try:
            sql = f"""
            SELECT WAREHOUSE_NAME,
                   ROUND(SUM(CREDITS_ATTRIBUTED_COMPUTE), 4) AS CREDITS,
                   COUNT(*) AS QUERY_COUNT,
                   ROUND(AVG(CREDITS_ATTRIBUTED_COMPUTE), 6) AS AVG_CREDIT_PER_QUERY
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_ATTRIBUTION_HISTORY
            WHERE USER_NAME = '{safe_user}'
              AND START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
            GROUP BY 1
            ORDER BY 2 DESC
            """
            with conn:
                rows = conn.query(sql)
            return pd.DataFrame(rows), None
        except Exception:
            pass

        # Fallback — no attributed credits, but show warehouse usage by query count
        sql_fallback = f"""
        SELECT WAREHOUSE_NAME,
               0.0 AS CREDITS,
               COUNT(*) AS QUERY_COUNT,
               0.0 AS AVG_CREDIT_PER_QUERY
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE USER_NAME = '{safe_user}'
          AND START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
          AND EXECUTION_STATUS = 'SUCCESS'
        GROUP BY 1
        ORDER BY QUERY_COUNT DESC
        """
        conn2 = self.context.connect()
        with conn2:
            rows = conn2.query(sql_fallback)
        return pd.DataFrame(rows), _NOTE_USER_DETAIL_NO_CREDITS

    # --- Storage usage ---

    def get_storage_usage(self, days: int = 30, refresh: bool = False) -> tuple[pd.DataFrame, int | None]:
        """
        Storage breakdown per database (active + failsafe + time travel) plus stage storage.
        Uses DATABASE_STORAGE_USAGE_HISTORY and STAGE_STORAGE_USAGE_HISTORY.
        Returns storage in TB with estimated monthly cost using the org's contracted rate
        (from RATE_SHEET_DAILY) or $23/TB on-demand default.
        """
        cache_key = f"cost_storage_{days}d_fetched_at"

        if not refresh and self._is_fresh(cache_key):
            cached = self.db.get_cost_storage_cache()
            if cached:
                df = pd.DataFrame(cached)
                df["TOTAL_BYTES"] = df["ACTIVE_BYTES"] + df["FAILSAFE_BYTES"] + df["STAGE_BYTES"]
                df["TOTAL_TB"] = (df["TOTAL_BYTES"] / 1e12).round(4)
                rate = self.get_storage_rate()
                df["EST_MONTHLY_COST"] = (df["TOTAL_TB"] * rate).round(2)
                df = df.sort_values("TOTAL_BYTES", ascending=False).reset_index(drop=True)
                return df, self._cache_age_minutes(cache_key)

        sql = f"""
        WITH db_storage AS (
            SELECT DATABASE_NAME,
                   AVG(AVERAGE_DATABASE_BYTES) AS active_bytes,
                   AVG(AVERAGE_FAILSAFE_BYTES) AS failsafe_bytes
            FROM SNOWFLAKE.ACCOUNT_USAGE.DATABASE_STORAGE_USAGE_HISTORY
            WHERE USAGE_DATE >= DATEADD(day, -{days}, CURRENT_DATE())
            GROUP BY 1
        ),
        stage_storage AS (
            SELECT AVG(AVERAGE_STAGE_BYTES) AS stage_bytes
            FROM SNOWFLAKE.ACCOUNT_USAGE.STAGE_STORAGE_USAGE_HISTORY
            WHERE USAGE_DATE >= DATEADD(day, -{days}, CURRENT_DATE())
        )
        SELECT d.DATABASE_NAME,
               ROUND(d.active_bytes, 0) AS ACTIVE_BYTES,
               ROUND(d.failsafe_bytes, 0) AS FAILSAFE_BYTES,
               0 AS STAGE_BYTES
        FROM db_storage d
        UNION ALL
        SELECT '(Internal Stages)' AS DATABASE_NAME,
               0 AS ACTIVE_BYTES,
               0 AS FAILSAFE_BYTES,
               ROUND(s.stage_bytes, 0) AS STAGE_BYTES
        FROM stage_storage s
        WHERE s.stage_bytes > 0
        ORDER BY ACTIVE_BYTES DESC
        """
        conn = self.context.connect()
        with conn:
            rows = conn.query(sql)
        df = pd.DataFrame(rows)
        if not df.empty:
            df["ACTIVE_BYTES"] = df["ACTIVE_BYTES"].astype(float)
            df["FAILSAFE_BYTES"] = df["FAILSAFE_BYTES"].astype(float)
            df["STAGE_BYTES"] = df["STAGE_BYTES"].astype(float)
            df["TOTAL_BYTES"] = df["ACTIVE_BYTES"] + df["FAILSAFE_BYTES"] + df["STAGE_BYTES"]
            df["TOTAL_TB"] = (df["TOTAL_BYTES"] / 1e12).round(4)
            rate = self.get_storage_rate()
            df["EST_MONTHLY_COST"] = (df["TOTAL_TB"] * rate).round(2)
            # Cache
            today = date.today().isoformat()
            self.db.save_cost_storage_snapshot(today, df.to_dict("records"))
            self._mark_cached(cache_key)
        return df, None

    # --- Budget status (Snowflake-native budgets) ---

    def get_budget_status(self, days: int = 30) -> tuple[pd.DataFrame, str | None]:
        """
        Surface Snowflake-native budget status.
        GET_SPENDING_HISTORY is a stored procedure, not a table function — must use CALL.
        Returns (df, error_message) — error_message is set if budgets are not activated.
        """
        conn = self.context.connect()
        try:
            with conn:
                rows = conn.query(f"""
                    CALL SNOWFLAKE.LOCAL.ACCOUNT_ROOT_BUDGET!GET_SPENDING_HISTORY(
                        TIME_LOWER_BOUND => DATEADD('days', -{int(days)}, CURRENT_TIMESTAMP()),
                        TIME_UPPER_BOUND => CURRENT_TIMESTAMP()
                    )
                """)
            df = pd.DataFrame(rows)
            return df, None
        except Exception as e:
            err_msg = str(e)
            not_activated = (
                "ACCOUNT_ROOT_BUDGET_NOT_ACTIVATED" in err_msg
                or "not activated" in err_msg.lower()
                or "does not exist" in err_msg.lower()
            )
            if not_activated:
                return pd.DataFrame(), (
                    "Snowflake budgets are not activated on this account.\n\n"
                    "To enable, run the following in a Snowsight worksheet as ACCOUNTADMIN:\n\n"
                    "  CALL SNOWFLAKE.LOCAL.ACCOUNT_ROOT_BUDGET!ACTIVATE();"
                )
            return pd.DataFrame(), f"Could not retrieve budget status: {err_msg}"

    # --- Replication costs ---

    def get_replication_costs(self, days: int = 30, refresh: bool = False) -> tuple[pd.DataFrame, int | None]:
        """
        Replication credit costs from REPLICATION_GROUP_USAGE_HISTORY.
        Falls back to METERING_DAILY_HISTORY filtered by REPLICATION service type.
        """
        cache_key = f"cost_replication_{days}d_fetched_at"

        if not refresh and self._is_fresh(cache_key):
            cached = self.db.get_json_cache(f"cost_replication_{days}d_data")
            if cached:
                df = pd.DataFrame(cached)
                return df, self._cache_age_minutes(cache_key)

        # Try detailed replication view first
        sql = f"""
        SELECT REPLICATION_GROUP_NAME,
               ROUND(SUM(CREDITS_USED), 2) AS CREDITS,
               ROUND(SUM(BYTES_TRANSFERRED) / 1e9, 2) AS GB_TRANSFERRED
        FROM SNOWFLAKE.ACCOUNT_USAGE.REPLICATION_GROUP_USAGE_HISTORY
        WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
        GROUP BY 1
        ORDER BY 2 DESC
        """
        conn = self.context.connect()
        try:
            with conn:
                rows = conn.query(sql)
            df = pd.DataFrame(rows)
            if not df.empty:
                self.db.set_json_cache(f"cost_replication_{days}d_data", df.to_dict("records"))
                self._mark_cached(cache_key)
            return df, None
        except Exception:
            # Fallback: use metering daily history
            sql_fallback = f"""
            SELECT USAGE_DATE AS DATE,
                   ROUND(SUM(CREDITS_BILLED), 2) AS CREDITS
            FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY
            WHERE SERVICE_TYPE = 'REPLICATION'
              AND USAGE_DATE >= DATEADD(day, -{days}, CURRENT_DATE())
            GROUP BY 1
            ORDER BY 1
            """
            conn2 = self.context.connect()
            with conn2:
                rows = conn2.query(sql_fallback)
            df = pd.DataFrame(rows)
            if not df.empty:
                self.db.set_json_cache(f"cost_replication_{days}d_data", df.to_dict("records"))
                self._mark_cached(cache_key)
            return df, None

    # --- Materialized view costs ---

    def get_materialized_view_costs(self, days: int = 30, refresh: bool = False) -> tuple[pd.DataFrame, int | None]:
        """
        Per-materialized-view refresh costs from MATERIALIZED_VIEW_REFRESH_HISTORY.
        """
        cache_key = f"cost_mv_{days}d_fetched_at"

        if not refresh and self._is_fresh(cache_key):
            cached = self.db.get_json_cache(f"cost_mv_{days}d_data")
            if cached:
                df = pd.DataFrame(cached)
                return df, self._cache_age_minutes(cache_key)

        sql = f"""
        SELECT DATABASE_NAME || '.' || SCHEMA_NAME || '.' || TABLE_NAME AS MV_NAME,
               ROUND(SUM(CREDITS_USED), 2) AS CREDITS,
               COUNT(*) AS REFRESH_COUNT
        FROM SNOWFLAKE.ACCOUNT_USAGE.MATERIALIZED_VIEW_REFRESH_HISTORY
        WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
        GROUP BY 1
        ORDER BY 2 DESC
        """
        conn = self.context.connect()
        try:
            with conn:
                rows = conn.query(sql)
            df = pd.DataFrame(rows)
            if not df.empty:
                self.db.set_json_cache(f"cost_mv_{days}d_data", df.to_dict("records"))
                self._mark_cached(cache_key)
            return df, None
        except Exception:
            # View may not exist if no MVs are used
            return pd.DataFrame(), None
