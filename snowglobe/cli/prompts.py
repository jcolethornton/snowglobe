__all__ = [
    "resolve_access_inputs"
]

import typer
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter, FuzzyCompleter
from snowglobe.models.privilege import Privilege
from snowglobe.models.access import ObjectType

def prompt(label:str, session: PromptSession, items: list[str], strict: bool = False, output: bool = False):
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
    if not value and strict == True:
        typer.secho("Field required!", fg=typer.colors.YELLOW)
        value = get_value(fuzzy)
    elif value not in items and strict == True:
        typer.secho(f"{label} not found!", fg=typer.colors.YELLOW)
        value = get_value(fuzzy)
    else:
        pass
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
) -> dict:

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

    # Retrun resvoled inputs if all
    if all([username or role, object_type, object_name, privilege]):
        return resolved_inputs

    # Interactive prompts for missing inputs
    session = PromptSession()
    if not inspect_type:
        choice = prompt("Inspect type (User or Role): ",session, ["User", "Role"])
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
        object_type = prompt("Select object type ",session, items, strict=True)
        typer.secho(f"Object type: {object_type}", fg=typer.colors.GREEN)
        resolved_inputs['object_type'] = object_type

    if not object_name:
        items = sorted(set(g.object.name for g in grants if g.object.object_type.value == object_type))
        object_name = prompt("Object name (FQN): ",session, items, strict=True)
        resolved_inputs['object_name'] = object_name
        resolved_inputs["database"] = object_name.split(".", 1)[0] if object_name else None

    if not privilege:
        #TODO add in option for ANY
        items = [p.name for p in Privilege]
        privilege = prompt("Privilege to inspect : ",session, items, strict=True)
        resolved_inputs['privilege'] = privilege

    return resolved_inputs

# def resolve_query_inputs(
#     *,
#     ) -> dict:
#
#     # Interactive prompts for missing inputs
#     session = PromptSession()
