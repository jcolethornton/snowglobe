
from typing import List
from snowglobe.queries.query_history import get_warehouse_queries
from snowglobe.models.query import QueryStats


class QueryCollector:
    """
    Collects Snowflake query metadata.
    """

    def __init__(self, connection, days):
        """
        connection: SnowflakeReadOnly instance
        """
        self.connection = connection
        self.days = days

    def warehouse_queries(self) -> List[QueryStats]:
        """
        Collect queries against warehouses over X days
        """
        query_history: List[QueryStats] = []

        with self.connection:
            qh = get_warehouse_queries(days=self.days)
            rows = self.connection.query(qh)
            for q in rows:
                result = QueryStats(
                    query_id=q["QUERY_ID"],
                    user_name=q["USER_NAME"],
                    warehouse_name=q["WAREHOUSE_NAME"],
                    warehouse_size=q["WAREHOUSE_SIZE"],
                    query_text=q["QUERY_TEXT"],
                    query_tag=q["QUERY_TAG"],
                    query_type=q["QUERY_TYPE"],
                    bytes_scanned=q["BYTES_SCANNED"],
                    execution_time_sec=q["EXECUTION_TIME_SEC"],
                    start_time=q["START_TIME"],
                    warehouse_multiplier=q["WAREHOUSE_MULTIPLIER"],
                    estimated_credits=q["ESTIMATED_CREDITS"],
                )
                query_history.append(result)

        return query_history

