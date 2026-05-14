from dataclasses import dataclass
from typing import List

@dataclass
class QueryOptimizationResult:
    suggestions: List[str]

@dataclass
class ExpensiveOperator:
    operator_type: str
    operator_id: int
    score: float
    detail: dict
