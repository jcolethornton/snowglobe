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
        collector = QueryProfileCollector(conn)
        self.sql_text = collector.fetch_sql_text(query_id)
        self.query_profile = collector.fetch_query_profile(query_id)

    def analyze_query(self):
        self.optimizer = QueryOptimizerEngine(self.query_profile)

    def suggestions(self):
        self.result_suggestions = self.optimizer.get_suggestions()
        return self.result_suggestions

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
        # Unique key for each operator
        def key(op):
            return (op.step_id, op.operator_id)

        # Map operator keys to objects
        op_map = {key(op): op for op in self.query_profile}

        # Initialize child mapping
        tree: Dict[tuple, List[tuple]] = {key(op): [] for op in self.query_profile}
        child_keys = set()

        # Fill children
        for op in self.query_profile:
            if op.parent_operators:
                for parent_id in op.parent_operators:
                    parent_key = (op.step_id, parent_id)
                    tree.setdefault(parent_key, []).append(key(op))
                    child_keys.add(key(op))

        # Roots = operators that are never children
        roots = [k for k in op_map.keys() if k not in child_keys]

        return {
            "roots": roots,
            "tree": tree,
            "op_map": op_map
        }

    def expensive_operators(self):
        return self.optimizer.get_expensive_operators()

    def ai_suggestion(self):
        conn = self.context.connect()
        cortex = CortexOptimizer(connection=conn)
        ai_result = cortex.analyze_query(
            self.sql_text,
            self.result_suggestions.suggestions,
            self.result_cost_attribution
        )
        return ai_result



