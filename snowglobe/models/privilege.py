from enum import Enum


class Privilege(str, Enum):
    USAGE = "USAGE"
    MONITOR = "MONITOR"
    SELECT = "SELECT"
    INSERT = "INSERT"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    OWNERSHIP = "OWNERSHIP"
    OTHER = "OTHER"

    @classmethod
    def from_value(cls, value: str) -> "Privilege":
        """
        Convert a string privilege to a Privilege enum.
        Unknown privileges map to OTHER.
        """
        try:
            return cls(value.upper())
        except Exception:
            return cls.OTHER

    @classmethod
    def matches(cls, granted: str, requested: str) -> bool:
        """
        Check if a granted privilege satisfies a requested privilege.

        Snowflake semantics:
        - OWNERSHIP implies all privileges
        - Other privileges must match exactly
        """

        granted_priv = cls.from_value(granted) if isinstance(granted, str) else granted
        requested_priv = cls.from_value(requested) if isinstance(requested, str) else requested

        if granted_priv == cls.OWNERSHIP:
            return True

        return granted_priv == requested_priv
