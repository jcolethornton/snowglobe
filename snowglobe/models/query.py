from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List

@dataclass
class QueryProfile:
    query_id: str
    step_id: int
    operator_id: int
    parent_operators: List[int]
    operator_type: str
    operator_statistics: Dict[str, Any]
    execution_time_breakdown: Dict[str, Any]
    operator_attributes: Dict[str, Any]

    def __post_init__(self):
        import json
        for field in [
            "operator_statistics",
            "execution_time_breakdown",
            "operator_attributes"
            ]:

            value = getattr(self, field)

            if isinstance(value, str):
                setattr(self, field, json.loads(value))

@dataclass
class QueryStats:
    query_id: str
    user_name: str
    warehouse_name: str
    warehouse_size: str
    query_text: str
    query_tag: str
    query_type: str
    bytes_scanned: int
    execution_time_sec: float
    start_time: datetime
    warehouse_multiplier: int
    estimated_credits: float

    def to_dict(self) -> dict:

        return {
            "query_id": self.query_id,
            "user_name": self.user_name,
            "warehouse_name": self.warehouse_name,
            "warehouse_size": self.warehouse_size,
            "query_text": self.query_text,
            "query_tag": self.query_tag,
            "query_type": self.query_type,
            "bytes_scanned": self.bytes_scanned,
            "execution_time_sec": float(self.execution_time_sec or 0),
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "warehouse_multiplier": self.warehouse_multiplier,
            "estimated_credits": float(self.estimated_credits or 0)
        }
