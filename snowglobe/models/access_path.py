from dataclasses import dataclass
from typing import List, Dict
from snowglobe.models.access import AccessGrant


@dataclass(frozen=True)
class AccessPath:
    id: str
    role_chain: List[str]
    grant: AccessGrant

@dataclass()
class AccessPathReturn:
    access_paths: Dict

