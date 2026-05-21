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


class CostService:
    """Provides cost analysis across all Snowflake cost sources with caching."""

    def __init__(self, context):
        self.context = context
        self.context.load_profile()
        self.db = StateDB()

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
            # AI costs aren't stored in a dedicated snapshot table, so no cache read
            pass  # Fall through to Snowflake query
        else:
            pass

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
            self._mark_cached(cache_key)
        return df, None

    def get_ai_costs_by_user(self, days: int = 30, refresh: bool = False) -> tuple[pd.DataFrame, int | None]:
        """
        AI/ML token costs per user with per-service breakdown.
        Returns (df, cache_age_minutes).
        """
        cache_key = f"cost_ai_users_{days}d_fetched_at"

        # No dedicated cache table for ai-users — always query (but mark to avoid re-query)
        if not refresh and self._is_fresh(cache_key):
            pass  # Fall through — no cache storage for this view yet

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
            self._mark_cached(cache_key)
        return df, None

    def get_service_breakdown(self, days: int = 30, refresh: bool = False) -> tuple[pd.DataFrame, int | None]:
        """
        Non-warehouse, non-AI service costs.
        Returns (df, cache_age_minutes).
        """
        cache_key = f"cost_services_{days}d_fetched_at"

        # No dedicated cache table — always query
        if not refresh and self._is_fresh(cache_key):
            pass  # Fall through

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
