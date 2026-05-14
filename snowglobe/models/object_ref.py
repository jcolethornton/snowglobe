from dataclasses import dataclass
from snowglobe.models.object_type import ObjectType

@dataclass(frozen=True)
class ObjectRef:
    object_type: ObjectType
    name: str #fqn

    def __str__(self) -> str:
        return f"{self.object_type}:{self.name}"

