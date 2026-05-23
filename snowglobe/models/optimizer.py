from dataclasses import dataclass, field
from typing import List

@dataclass
class QueryOptimizationResult:
    suggestions: List[str]
    insights: List[dict] = field(default_factory=list)  # Snowflake-native QUERY_INSIGHTS

@dataclass
class ExpensiveOperator:
    operator_type: str
    operator_id: int
    score: float
    detail: dict
    time_pct: float = 0.0  # overall_percentage from execution_time_breakdown
