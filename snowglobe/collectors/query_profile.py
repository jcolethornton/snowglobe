import json
from typing import List
from snowglobe.models.query import QueryProfile


class QueryProfileCollector:

    def __init__(self, connection):
        self.connection = connection

    def fetch_sql_text(self, query_id: str):

        with self.connection:

            sql = f"""
            SELECT query_text
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
            WHERE query_id = '{query_id}';
            """
            result = self.connection.query(sql)

        if not result:
            raise ValueError(f"No query found with id {query_id}")

        return result[0]["QUERY_TEXT"]

    def fetch_query_profile(self, query_id: str) -> List[QueryProfile]:

        with self.connection:

            sql = f"SELECT * FROM TABLE(GET_QUERY_OPERATOR_STATS('{query_id}'))"
            rows = self.connection.query(sql)
            
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
