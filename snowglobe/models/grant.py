from dataclasses import dataclass
from snowglobe.models.privilege import Privilege
from snowglobe.models.object_ref import ObjectRef

@dataclass(frozen=True)
class Grant:
    role: str
    privilege: Privilege
    object: ObjectRef
    inherited: bool = False
    source_role: str | None = None
