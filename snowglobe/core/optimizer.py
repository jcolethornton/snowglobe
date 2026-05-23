from typing import List, Dict
from snowglobe.collectors.query_profile import QueryProfileCollector
from snowglobe.engines.optimizer.query_optimizer import QueryOptimizerEngine
from snowglobe.engines.ai.cortex_optimizer import CortexOptimizer


class QueryOptimizerService:
    def __init__(self, context):
        self.context = context
        self.load_profile()

    def load_profile(self):
        self.context.load_profile()
        self.profile = self.context.profile

    def get_profile(self):
        return self.profile

    def collect_query_profile(self, query_id: str):
        conn = self.context.connect()
        self.collector = QueryProfileCollector(conn)
        self.sql_text = self.collector.fetch_sql_text(query_id)
        self.query_profile = self.collector.fetch_query_profile(query_id)
        self.query_id = query_id

    def collect_insights(self) -> List[dict]:
        """Fetch Snowflake-native query insights. Call after collect_query_profile."""
        conn = self.context.connect()
        collector = QueryProfileCollector(conn)
        self.query_insights = collector.fetch_query_insights(self.query_id)
        return self.query_insights

    def analyze_query(self):
        self.optimizer = QueryOptimizerEngine(self.query_profile)

    def suggestions(self):
        result = self.optimizer.get_suggestions()
        # Attach any collected insights
        if hasattr(self, 'query_insights'):
            result.insights = self.query_insights
        self.result_suggestions = result
        return result

    def score(self):
        return self.optimizer.build_score_map()

    def cost_attribution(self):
        self.result_cost_attribution = self.optimizer.calculate_cost_attribution()
        return self.result_cost_attribution

    def build_operator_tree(self) -> Dict:
        """
        Convert a flat list of QueryProfile operators into a tree using parent_operators.
        Uses (step_id, operator_id) as the unique key to prevent duplication.
        """
        def key(op):
            return (op.step_id, op.operator_id)

        op_map = {key(op): op for op in self.query_profile}
        tree: Dict[tuple, List[tuple]] = {key(op): [] for op in self.query_profile}
        child_keys = set()

        for op in self.query_profile:
            if op.parent_operators:
                for parent_id in op.parent_operators:
                    parent_key = (op.step_id, parent_id)
                    tree.setdefault(parent_key, []).append(key(op))
                    child_keys.add(key(op))

        roots = [k for k in op_map.keys() if k not in child_keys]

        return {
            "roots": roots,
            "tree": tree,
            "op_map": op_map
        }

    def expensive_operators(self):
        return self.optimizer.get_expensive_operators()

    def ai_suggestion(self, model: str = "claude-haiku-4-5"):
        conn = self.context.connect()
        cortex = CortexOptimizer(connection=conn)
        ai_result = cortex.analyze_query(
            self.sql_text,
            self.result_suggestions.suggestions,
            self.result_cost_attribution,
            model=model,
        )
        return ai_result
