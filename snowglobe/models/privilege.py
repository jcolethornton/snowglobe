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


# Privilege suggestions per object type — the privileges Snowflake supports
# on each object kind. Used by the interactive shell prompts and the TUI to
# narrow the privilege picker once an object type has been chosen.
PRIVILEGES_BY_TYPE: dict[str, list[str]] = {
    "TABLE":             ["SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "OWNERSHIP"],
    "VIEW":              ["SELECT", "REFERENCES", "OWNERSHIP"],
    "MATERIALIZED VIEW": ["SELECT", "REFERENCES", "OWNERSHIP"],
    "SCHEMA":            ["USAGE", "CREATE TABLE", "CREATE VIEW", "CREATE STAGE", "CREATE PIPE",
                          "CREATE STREAM", "CREATE TASK", "CREATE FUNCTION", "CREATE PROCEDURE", "OWNERSHIP"],
    "DATABASE":          ["USAGE", "MONITOR", "CREATE SCHEMA", "OWNERSHIP"],
    "WAREHOUSE":         ["USAGE", "OPERATE", "MONITOR", "MODIFY", "OWNERSHIP"],
    "STAGE":             ["USAGE", "READ", "WRITE", "OWNERSHIP"],
    "STREAM":            ["SELECT", "OWNERSHIP"],
    "TASK":              ["OPERATE", "MONITOR", "OWNERSHIP"],
    "PIPE":              ["OPERATE", "MONITOR", "OWNERSHIP"],
    "FUNCTION":          ["USAGE", "OWNERSHIP"],
    "PROCEDURE":         ["USAGE", "OWNERSHIP"],
    "STREAMLIT":         ["USAGE", "OWNERSHIP"],
    "NOTEBOOK":          ["USAGE", "OWNERSHIP"],
    "DYNAMIC TABLE":     ["SELECT", "OWNERSHIP"],
    "ALERT":             ["OPERATE", "OWNERSHIP"],
    "FILE FORMAT":       ["USAGE", "OWNERSHIP"],
    "SEQUENCE":          ["USAGE", "OWNERSHIP"],
    "TAG":               ["APPLY", "OWNERSHIP"],
    "SECRET":            ["USAGE", "READ", "OWNERSHIP"],
}

DEFAULT_PRIVILEGES: list[str] = ["SELECT", "INSERT", "UPDATE", "DELETE", "USAGE", "OWNERSHIP"]


def privileges_for_object_type(object_type: str | None) -> list[str]:
    """Return context-appropriate privilege suggestions for the given object type."""
    if not object_type:
        return DEFAULT_PRIVILEGES
    return PRIVILEGES_BY_TYPE.get(object_type.upper(), DEFAULT_PRIVILEGES)
