__all__ = [
    "resolve_access_inputs"
]

import sys
import typer
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter, FuzzyCompleter
from snowglobe.models.privilege import Privilege
from snowglobe.models.access import ObjectType


def is_interactive() -> bool:
    """Return True if stdin is a TTY (interactive terminal)."""
    return sys.stdin.isatty()


def prompt(label: str, session: PromptSession, items: list[str], strict: bool = False, output: bool = False):
    word = WordCompleter(items, ignore_case=True, sentence=True)
    fuzzy = FuzzyCompleter(word)

    def get_value(text):
        value = session.prompt(
            label,
            completer=text,
            complete_while_typing=True,
        ).strip()
        return value

    value = get_value(fuzzy)
    if not value and strict:
        typer.secho("Field required!", fg=typer.colors.YELLOW)
        value = get_value(fuzzy)
    elif value not in items and strict:
        typer.secho(f"{label} not found!", fg=typer.colors.YELLOW)
        value = get_value(fuzzy)

    if output:
        typer.secho(f"{label} {value}", fg=typer.colors.GREEN)
    return value


def resolve_access_inputs(
    *,
    username,
    role,
    object_type,
    object_name,
    privilege,
    user_graph,
    role_graph,
    grants,
    object_index=None,
) -> dict:
    """
    Resolve access query inputs. If all required args are provided, returns
    immediately (headless-safe). If args are missing and stdin is a TTY,
    prompts interactively. If args are missing and stdin is NOT a TTY,
    raises an error with a clear message.
    """

    # Inspect type: user or role
    if username and not role:
        inspect_type = "user"
    elif role and not username:
        inspect_type = "role"
    else:
        inspect_type = None

    # Inputs
    resolved_inputs = {
        "inspect_type": inspect_type,
        "username": username if username else None,
        "role": role if role else None,
        "object_type": object_type if object_type else None,
        "object_name": object_name.upper() if object_name else None,
        "database": object_name.split(".", 1)[0] if object_name else None,
        "privilege": privilege if privilege else None
    }

    # Return resolved inputs if all provided (headless-safe path)
    if all([username or role, object_type, object_name, privilege]):
        return resolved_inputs

    # In headless mode, fail fast with a clear error
    if not is_interactive():
        missing = []
        if not (username or role):
            missing.append("--username or --role")
        if not object_type:
            missing.append("--object-type")
        if not object_name:
            missing.append("--object-name")
        if not privilege:
            missing.append("--privilege")
        typer.secho(
            f"Error: Missing required arguments: {', '.join(missing)}. "
            "All arguments must be provided in non-interactive (headless) mode.",
            fg=typer.colors.RED
        )
        raise typer.Exit(1)

    # Interactive prompts for missing inputs
    session = PromptSession()
    if not inspect_type:
        choice = prompt("Inspect type (User or Role): ", session, ["User", "Role"])
        if choice.lower().startswith("u"):
            inspect_type = "user"
            resolved_inputs["inspect_type"] = "user"
        elif choice.lower().startswith("r"):
            inspect_type = "role"
            resolved_inputs["inspect_type"] = "role"
        else:
            typer.secho("Please choose 'User' or 'Role'. Exiting.", fg=typer.colors.RED)
            raise typer.Exit(1)

    if inspect_type == "user" and not username:
        items = list(user_graph.assigned_roles.keys())
        username = prompt("User: ", session, items, strict=True)
        resolved_inputs["username"] = username

    elif inspect_type == "role" and not role:
        items = list(role_graph.roles.keys())
        role = prompt("Role: ", session, items, strict=True)
        resolved_inputs["role"] = role

    if not object_type:
        items = [ot.value for ot in ObjectType]
        object_type = prompt("Select object type ", session, items, strict=True)
        typer.secho(f"Object type: {object_type}", fg=typer.colors.GREEN)
        resolved_inputs['object_type'] = object_type

    if not object_name:
        # Use object_index for completions if available, fall back to grants
        if object_index and object_type in object_index:
            items = object_index[object_type]
        elif object_index and object_type.upper() in object_index:
            items = object_index[object_type.upper()]
        else:
            items = sorted(set(g.object.name for g in grants if g.object.object_type.value == object_type))
        object_name = prompt("Object name (FQN): ", session, items, strict=False)
        if not object_name or not object_name.strip():
            typer.secho("Object name is required.", fg=typer.colors.RED)
            raise typer.Exit(1)
        resolved_inputs['object_name'] = object_name.upper()
        resolved_inputs["database"] = object_name.split(".", 1)[0]

    if not privilege:
        items = _privileges_for_object_type(object_type)
        privilege = prompt("Privilege to inspect : ", session, items, strict=False)
        if not privilege or not privilege.strip():
            typer.secho("Privilege is required.", fg=typer.colors.RED)
            raise typer.Exit(1)
        resolved_inputs['privilege'] = privilege.upper()

    return resolved_inputs


# Privilege suggestions per object type (most common Snowflake privileges)
PRIVILEGES_BY_TYPE = {
    "TABLE": ["SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "OWNERSHIP"],
    "VIEW": ["SELECT", "REFERENCES", "OWNERSHIP"],
    "MATERIALIZED VIEW": ["SELECT", "REFERENCES", "OWNERSHIP"],
    "SCHEMA": ["USAGE", "CREATE TABLE", "CREATE VIEW", "CREATE STAGE", "CREATE PIPE", "CREATE STREAM", "CREATE TASK", "CREATE FUNCTION", "CREATE PROCEDURE", "OWNERSHIP"],
    "DATABASE": ["USAGE", "MONITOR", "CREATE SCHEMA", "OWNERSHIP"],
    "WAREHOUSE": ["USAGE", "OPERATE", "MONITOR", "MODIFY", "OWNERSHIP"],
    "STAGE": ["USAGE", "READ", "WRITE", "OWNERSHIP"],
    "STREAM": ["SELECT", "OWNERSHIP"],
    "TASK": ["OPERATE", "MONITOR", "OWNERSHIP"],
    "PIPE": ["OPERATE", "MONITOR", "OWNERSHIP"],
    "FUNCTION": ["USAGE", "OWNERSHIP"],
    "PROCEDURE": ["USAGE", "OWNERSHIP"],
    "STREAMLIT": ["USAGE", "OWNERSHIP"],
    "NOTEBOOK": ["USAGE", "OWNERSHIP"],
    "DYNAMIC TABLE": ["SELECT", "OWNERSHIP"],
    "ALERT": ["OPERATE", "OWNERSHIP"],
    "FILE FORMAT": ["USAGE", "OWNERSHIP"],
    "SEQUENCE": ["USAGE", "OWNERSHIP"],
    "TAG": ["APPLY", "OWNERSHIP"],
    "SECRET": ["USAGE", "READ", "OWNERSHIP"],
}

# Default fallback
_DEFAULT_PRIVILEGES = ["SELECT", "INSERT", "UPDATE", "DELETE", "USAGE", "OWNERSHIP"]


def _privileges_for_object_type(object_type: str | None) -> list[str]:
    """Return context-appropriate privilege suggestions for the given object type."""
    if not object_type:
        return _DEFAULT_PRIVILEGES
    return PRIVILEGES_BY_TYPE.get(object_type.upper(), _DEFAULT_PRIVILEGES)
