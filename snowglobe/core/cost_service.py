"""
Cost analysis service for Snowglobe.

Queries ACCOUNT_USAGE views for comprehensive cost attribution across all Snowflake services.
Implements a 1-hour TTL cache via SQLite — repeated calls within the hour serve from cache.
Use refresh=True to force a fresh query to Snowflake.
"""
import pandas as pd
from datetime import date, datetime, timezone

from snowglobe.state.db import StateDB

CACHE_TTL_SECONDS = 3600  # 1 hour
DEFAULT_STORAGE_RATE_PER_TB = 23.0  # On-demand standard rate $/TB/month


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
                df["DAYS_ACTIVE"] = ""  # Not stored in cache
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

    def get_user_breakdown(self, days: int = 7, refresh: bool = False) -> tuple[pd.DataFrame, int | None]:
        """
        Complete cost per user — combines real warehouse attributed credits + all AI token costs.
        Returns (df, cache_age_minutes).
        """
        cache_key = f"cost_users_{days}d_fetched_at"

        if not refresh and self._is_fresh(cache_key):
            cached = self.db.get_cost_user_cache()
            if cached:
                df = pd.DataFrame(cached)
                df = df.sort_values("TOTAL_CREDITS", ascending=False).reset_index(drop=True)
                return df, self._cache_age_minutes(cache_key)

        sql = f"""
        WITH warehouse_costs AS (
            SELECT USER_NAME,
                   ROUND(SUM(CREDITS_ATTRIBUTED_COMPUTE), 2) AS warehouse_credits,
                   ROUND(SUM(COALESCE(CREDITS_USED_QUERY_ACCELERATION, 0)), 2) AS qa_credits,
                   COUNT(*) AS query_count
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_ATTRIBUTION_HISTORY
            WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
            GROUP BY 1
        ),
        ai_costs AS (
            SELECT USER_NAME, service, SUM(token_credits) AS credits
            FROM (
                SELECT u.LOGIN_NAME AS user_name, 'Cortex Functions' AS service, credits AS token_credits
                FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AI_FUNCTIONS_USAGE_HISTORY f
                INNER JOIN SNOWFLAKE.ACCOUNT_USAGE.USERS u ON u.USER_ID = f.USER_ID
                WHERE f.START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
                UNION ALL
                SELECT USERNAME, 'Cortex Analyst', credits
                FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_ANALYST_USAGE_HISTORY
                WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
                UNION ALL
                SELECT USER_NAME, 'Cortex Agent', token_credits
                FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AGENT_USAGE_HISTORY
                WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
                UNION ALL
                SELECT USER_NAME, 'Cortex Code', token_credits
                FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_CLI_USAGE_HISTORY
                WHERE USAGE_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
                UNION ALL
                SELECT USER_NAME, 'Cortex Code', token_credits
                FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY
                WHERE USAGE_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
                UNION ALL
                SELECT USER_NAME, 'Cortex Code', token_credits
                FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_DESKTOP_USAGE_HISTORY
                WHERE USAGE_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
                UNION ALL
                SELECT USER_NAME, 'Snowflake Intelligence', token_credits
                FROM SNOWFLAKE.ACCOUNT_USAGE.SNOWFLAKE_INTELLIGENCE_USAGE_HISTORY
                WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
            ) sub
            WHERE token_credits > 0
            GROUP BY 1, 2
        ),
        ai_pivot AS (
            SELECT USER_NAME,
                   ROUND(SUM(CASE WHEN service = 'Cortex Functions' THEN credits END), 2) AS cortex_functions,
                   ROUND(SUM(CASE WHEN service = 'Cortex Analyst' THEN credits END), 2) AS cortex_analyst,
                   ROUND(SUM(CASE WHEN service = 'Cortex Agent' THEN credits END), 2) AS cortex_agent,
                   ROUND(SUM(CASE WHEN service = 'Cortex Code' THEN credits END), 2) AS cortex_code,
                   ROUND(SUM(CASE WHEN service = 'Snowflake Intelligence' THEN credits END), 2) AS snowflake_intelligence,
                   ROUND(SUM(credits), 2) AS total_ai_credits
            FROM ai_costs
            GROUP BY 1
        )
        SELECT COALESCE(w.USER_NAME, a.USER_NAME) AS USER_NAME,
               COALESCE(w.query_count, 0) AS QUERY_COUNT,
               COALESCE(w.warehouse_credits, 0) AS WAREHOUSE_CREDITS,
               COALESCE(w.qa_credits, 0) AS QA_CREDITS,
               COALESCE(a.cortex_functions, 0) AS CORTEX_FUNCTIONS,
               COALESCE(a.cortex_analyst, 0) AS CORTEX_ANALYST,
               COALESCE(a.cortex_agent, 0) AS CORTEX_AGENT,
               COALESCE(a.cortex_code, 0) AS CORTEX_CODE,
               COALESCE(a.snowflake_intelligence, 0) AS SNOWFLAKE_INTELLIGENCE,
               ROUND(COALESCE(w.warehouse_credits, 0) + COALESCE(w.qa_credits, 0) + COALESCE(a.total_ai_credits, 0), 2) AS TOTAL_CREDITS
        FROM warehouse_costs w
        FULL OUTER JOIN ai_pivot a ON w.USER_NAME = a.USER_NAME
        ORDER BY TOTAL_CREDITS DESC
        LIMIT 30
        """
        conn = self.context.connect()
        with conn:
            rows = conn.query(sql)
        df = pd.DataFrame(rows)
        if not df.empty:
            today = date.today().isoformat()
            self.db.save_cost_user_snapshot(today, df.to_dict("records"))
            self._mark_cached(cache_key)
        return df, None

    def get_ai_costs(self, days: int = 30, refresh: bool = False) -> tuple[pd.DataFrame, int | None]:
        """
        AI/ML token costs aggregated by service type.
        Returns (df, cache_age_minutes).
        """
        cache_key = f"cost_ai_{days}d_fetched_at"

        if not refresh and self._is_fresh(cache_key):
            cached = self.db.get_json_cache(f"cost_ai_{days}d_data")
            if cached:
                df = pd.DataFrame(cached)
                return df, self._cache_age_minutes(cache_key)

        sql = f"""
        SELECT service AS SERVICE,
               ROUND(SUM(token_credits), 2) AS TOTAL_CREDITS,
               COUNT(*) AS REQUEST_COUNT
        FROM (
            SELECT 'Cortex Functions' AS service, credits AS token_credits
            FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AI_FUNCTIONS_USAGE_HISTORY
            WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
            UNION ALL
            SELECT 'Cortex Analyst', credits
            FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_ANALYST_USAGE_HISTORY
            WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
            UNION ALL
            SELECT 'Cortex Agent', token_credits
            FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AGENT_USAGE_HISTORY
            WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
            UNION ALL
            SELECT 'Cortex Code (CLI)', token_credits
            FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_CLI_USAGE_HISTORY
            WHERE USAGE_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
            UNION ALL
            SELECT 'Cortex Code (Snowsight)', token_credits
            FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY
            WHERE USAGE_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
            UNION ALL
            SELECT 'Cortex Code (Desktop)', token_credits
            FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_DESKTOP_USAGE_HISTORY
            WHERE USAGE_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
            UNION ALL
            SELECT 'Snowflake Intelligence', token_credits
            FROM SNOWFLAKE.ACCOUNT_USAGE.SNOWFLAKE_INTELLIGENCE_USAGE_HISTORY
            WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
        ) sub
        WHERE token_credits > 0
        GROUP BY 1
        ORDER BY 2 DESC
        """
        conn = self.context.connect()
        with conn:
            rows = conn.query(sql)
        df = pd.DataFrame(rows)
        if not df.empty:
            df["TOTAL_CREDITS"] = df["TOTAL_CREDITS"].astype(float)
            total = df["TOTAL_CREDITS"].sum()
            df["PCT"] = (df["TOTAL_CREDITS"] / total * 100).round(1)
            self.db.set_json_cache(f"cost_ai_{days}d_data", df.to_dict("records"))
            self._mark_cached(cache_key)
        return df, None

    def get_ai_costs_by_user(self, days: int = 30, refresh: bool = False) -> tuple[pd.DataFrame, int | None]:
        """
        AI/ML token costs per user with per-service breakdown.
        Returns (df, cache_age_minutes).
        """
        cache_key = f"cost_ai_users_{days}d_fetched_at"

        # No dedicated cache table for ai-users — use JSON cache
        if not refresh and self._is_fresh(cache_key):
            cached = self.db.get_json_cache(f"cost_ai_users_{days}d_data")
            if cached:
                df = pd.DataFrame(cached)
                return df, self._cache_age_minutes(cache_key)

        sql = f"""
        WITH cte AS (
            SELECT u.LOGIN_NAME AS user_name, 'Cortex Functions' AS service, credits AS token_credits
            FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AI_FUNCTIONS_USAGE_HISTORY f
            INNER JOIN SNOWFLAKE.ACCOUNT_USAGE.USERS u ON u.USER_ID = f.USER_ID
            WHERE f.START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
            UNION ALL
            SELECT USERNAME, 'Cortex Analyst', credits
            FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_ANALYST_USAGE_HISTORY
            WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
            UNION ALL
            SELECT USER_NAME, 'Cortex Agent', token_credits
            FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AGENT_USAGE_HISTORY
            WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
            UNION ALL
            SELECT USER_NAME, 'Cortex Code', token_credits
            FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_CLI_USAGE_HISTORY
            WHERE USAGE_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
            UNION ALL
            SELECT USER_NAME, 'Cortex Code', token_credits
            FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY
            WHERE USAGE_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
            UNION ALL
            SELECT USER_NAME, 'Cortex Code', token_credits
            FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_DESKTOP_USAGE_HISTORY
            WHERE USAGE_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
            UNION ALL
            SELECT USER_NAME, 'Snowflake Intelligence', token_credits
            FROM SNOWFLAKE.ACCOUNT_USAGE.SNOWFLAKE_INTELLIGENCE_USAGE_HISTORY
            WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
        )
        SELECT
            user_name AS USER_NAME,
            ROUND(SUM(CASE WHEN service = 'Cortex Functions' THEN token_credits END), 2) AS CORTEX_FUNCTIONS,
            ROUND(SUM(CASE WHEN service = 'Cortex Analyst' THEN token_credits END), 2) AS CORTEX_ANALYST,
            ROUND(SUM(CASE WHEN service = 'Cortex Agent' THEN token_credits END), 2) AS CORTEX_AGENT,
            ROUND(SUM(CASE WHEN service = 'Cortex Code' THEN token_credits END), 2) AS CORTEX_CODE,
            ROUND(SUM(CASE WHEN service = 'Snowflake Intelligence' THEN token_credits END), 2) AS SNOWFLAKE_INTELLIGENCE,
            ROUND(SUM(token_credits), 2) AS TOTAL_CREDITS
        FROM cte
        WHERE token_credits > 0
        GROUP BY ALL
        ORDER BY TOTAL_CREDITS DESC
        LIMIT 30
        """
        conn = self.context.connect()
        with conn:
            rows = conn.query(sql)
        df = pd.DataFrame(rows)
        if not df.empty:
            self.db.set_json_cache(f"cost_ai_users_{days}d_data", df.to_dict("records"))
            self._mark_cached(cache_key)
        return df, None

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

    def get_top_queries(self, days: int = 7, limit: int = 10, sort_by: str = "credits", refresh: bool = False) -> tuple[pd.DataFrame, int | None]:
        """
        Top expensive individual queries using real attributed credits.
        Never cached — always fresh (results are per-query, not aggregate).
        """
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
        ORDER BY {'"CREDITS"' if sort_by == "credits" else '"GB_SCANNED"'} DESC
        LIMIT {limit}
        """
        conn = self.context.connect()
        with conn:
            rows = conn.query(sql)
        return pd.DataFrame(rows), None

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

    def get_budget_status(self) -> tuple[pd.DataFrame, str | None]:
        """
        Surface Snowflake-native budget status.
        Calls the account root budget spending history and lists custom budgets.
        Returns (df, error_message) — error_message is set if budgets are not activated.
        """
        conn = self.context.connect()
        try:
            with conn:
                # Get spending history from account budget
                rows = conn.query("""
                    SELECT *
                    FROM TABLE(SNOWFLAKE.LOCAL.ACCOUNT_ROOT_BUDGET!GET_SPENDING_HISTORY())
                """)
            df = pd.DataFrame(rows)
            return df, None
        except Exception as e:
            err_msg = str(e)
            if "not activated" in err_msg.lower() or "does not exist" in err_msg.lower():
                return pd.DataFrame(), "Budgets are not activated on this account. Use Snowsight or CALL SNOWFLAKE.LOCAL.ACCOUNT_ROOT_BUDGET!ACTIVATE() to enable."
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
