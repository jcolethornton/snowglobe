import pandas as pd
from snowglobe.state.state import StateManager
from snowglobe.collectors.query_history import QueryCollector

class QueryService:
    def __init__(self, context, days):
        self.context = context
        self.days = days
        self.load_profile()

    def load_profile(self):
        self.context.load_profile()
        self.profile = self.context.profile

    def get_profile(self):
        return self.profile

    def setup_state(self):
        self.state = StateManager(file="query_history.json")

    def refresh_state(self):
        conn = self.context.connect()
        collector = QueryCollector(conn, self.days)
        qh = collector.warehouse_queries()
        self.state.save([x.to_dict() for x in qh])

    def inspect_query_history(
        self,
        refresh_state: bool = False,
        cost_type: str = "credits",
        limit: int = 10
        ) -> pd.DataFrame:

        self.setup_state()

        if refresh_state:
            self.refresh_state()

        df = self.state.get_dataframe()
        df["start_time"] = pd.to_datetime(df["start_time"])

        if cost_type.endswith('credits'):
            df = df.sort_values("estimated_credits", ascending=False)

        if cost_type.startswith('bytes'):
            df = df.sort_values("bytes_scanned", ascending=False)

        return df.head(limit)
