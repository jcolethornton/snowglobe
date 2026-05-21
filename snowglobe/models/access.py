from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from snowglobe.models.object_ref import ObjectRef
from snowglobe.models.object_type import ObjectType


@dataclass(frozen=True)
class AccessGrant:
    """
    Represents an effective access privilege in Snowflake.

    This is the *resolved* truth:
    - Who can do what
    - On which object
    - And why they can do it
    """

    role: str
    privilege: str

    object: ObjectRef

    # How this privilege was obtained
    granted_on: str               # e.g. TABLE, SCHEMA, DATABASE
    granted_by: str               # role that issued the grant
    inherited: bool               # True if via role hierarchy
    source_role: Optional[str]    # Role where the privilege originated (if inherited)
    role_type: str

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "privilege": self.privilege,
            "object_type": self.object.object_type.value,
            "object_name": self.object.name,
            "granted_on": self.granted_on,
            "granted_by": self.granted_by,
            "inherited": self.inherited,
            "source_role": self.source_role,
            "role_type": self.role_type
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AccessGrant":
        try:
            obj_type = ObjectType(d["object_type"])
        except ValueError:
            obj_type = ObjectType.UNKNOWN

        return cls(
            role=d["role"],
            privilege=d["privilege"],
            object=ObjectRef(
                object_type=obj_type,
                name=d["object_name"],
            ),
            granted_on=d["granted_on"],
            granted_by=d["granted_by"],
            inherited=d["inherited"],
            role_type=d["role_type"],
            source_role=d.get("source_role"),
        )

