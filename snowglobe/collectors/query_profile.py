import json
import re
from typing import List
from snowglobe.models.query import QueryProfile

# Snowflake query IDs are UUIDs in the format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
QUERY_ID_PATTERN = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE)


def _validate_query_id(query_id: str) -> str:
    """Validate query_id matches Snowflake UUID format to prevent injection."""
    if not QUERY_ID_PATTERN.match(query_id):
        raise ValueError(f"Invalid query ID format: '{query_id}'. Expected UUID format.")
    return query_id


class QueryProfileCollector:

    def __init__(self, connection):
        self.connection = connection

    def fetch_sql_text(self, query_id: str):
        query_id = _validate_query_id(query_id)

        with self.connection:
            sql = f"SELECT query_text FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY WHERE query_id = '{query_id}'"
            result = self.connection.query(sql)

        if not result:
            raise ValueError(f"No query found with id {query_id}")

        return result[0]["QUERY_TEXT"]

    def fetch_query_profile(self, query_id: str) -> List[QueryProfile]:
        query_id = _validate_query_id(query_id)

        with self.connection:
            sql = f"SELECT * FROM TABLE(GET_QUERY_OPERATOR_STATS('{query_id}'))"
            try:
                rows = self.connection.query(sql)
            except Exception as e:
                err = str(e).lower()
                if "profile expired" in err:
                    raise ValueError(
                        f"Query profile for '{query_id}' has expired. "
                        "Snowflake retains profiles for ~14 days. Try a more recent query."
                    ) from None
                raise

            query_profile: List[QueryProfile] = []

            for q in rows:
                operator_statistics = json.loads(q["OPERATOR_STATISTICS"]) if q["OPERATOR_STATISTICS"] else {}
                execution_time_breakdown = json.loads(q["EXECUTION_TIME_BREAKDOWN"]) if q["EXECUTION_TIME_BREAKDOWN"] else {}
                operator_attributes = json.loads(q["OPERATOR_ATTRIBUTES"]) if q["OPERATOR_ATTRIBUTES"] else {}
                parent_operators = json.loads(q["PARENT_OPERATORS"]) if q["PARENT_OPERATORS"] else []

                result = QueryProfile(
                    query_id=q["QUERY_ID"],
                    step_id=q["STEP_ID"],
                    operator_id=q["OPERATOR_ID"],
                    parent_operators=parent_operators,
                    operator_type=q["OPERATOR_TYPE"],
                    operator_statistics=operator_statistics,
                    execution_time_breakdown=execution_time_breakdown,
                    operator_attributes=operator_attributes,
                )

                query_profile.append(result)

        return query_profile

    def fetch_query_insights(self, query_id: str) -> List[dict]:
        """
        Fetch Snowflake-native query insights from ACCOUNT_USAGE.QUERY_INSIGHTS.
        Returns a list of insight dicts. Empty list if no insights or view unavailable.
        Note: latency can be up to 90 minutes after query execution.
        """
        query_id = _validate_query_id(query_id)

        try:
            with self.connection:
                sql = f"""
                SELECT INSIGHT_TYPE_ID, MESSAGE, SUGGESTIONS, IS_OPPORTUNITY, INSIGHT_TOPIC
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_INSIGHTS
                WHERE QUERY_ID = '{query_id}'
                """
                rows = self.connection.query(sql)

            insights = []
            for row in rows:
                insights.append({
                    "type_id": row["INSIGHT_TYPE_ID"],
                    "message": row["MESSAGE"],
                    "suggestions": row["SUGGESTIONS"],
                    "is_opportunity": row["IS_OPPORTUNITY"],
                    "topic": row["INSIGHT_TOPIC"],
                })
            return insights
        except Exception:
            return []
