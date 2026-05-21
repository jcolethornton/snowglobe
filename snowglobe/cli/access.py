import typer
from typing import Optional
from snowglobe.core.access_service import AccessService
from snowglobe.cli.prompts import resolve_access_inputs
from snowglobe.output import cli

access_app = typer.Typer(
    help="Inspect Snowflake access and identify roles/users with access and privileges on database objects",
    no_args_is_help=True,
)


@access_app.command()
def check(
    ctx: typer.Context,
    ignore_excluded_roles: bool = typer.Option(False, help="Ignore excluded roles"),
    role: Optional[str] = typer.Option(None, help="Role to inspect access for"),
    username: Optional[str] = typer.Option(None, help="Username to inspect access for"),
    object_type: Optional[str] = typer.Option(None, help="Object type (e.g. TABLE)"),
    object_name: Optional[str] = typer.Option(None, help="Object name (e.g. DB.SCHEMA.TABLE)"),
    privilege: Optional[str] = typer.Option(None, help="Privilege to check (e.g. SELECT)"),
    output: str = typer.Option("text", help="Output format: text, json"),
    refresh_state: bool = typer.Option(False, help="Refresh state from Snowflake")
):
    """
    Check access for a user or role on a specific object.

    In interactive mode (TTY), missing arguments will be prompted for
    with fuzzy completion. In headless mode (piped/CI), all arguments
    must be provided or the command will exit with an error.
    """

    context = ctx.obj
    access_service = AccessService(context)

    # Load graphs for interactive resolution (needed for completions)
    access_service.setup_state()
    if refresh_state:
        access_service.refresh_state()
    access_service.load_state()

    # Resolve missing inputs (interactive prompts or headless error)
    resolved = resolve_access_inputs(
        username=username,
        role=role,
        object_type=object_type,
        object_name=object_name,
        privilege=privilege,
        user_graph=access_service.user_graph,
        role_graph=access_service.role_graph,
        grants=[],
        object_index=access_service.object_index,
    )

    # Run the access check with fully resolved args
    query_output = access_service.inspect_access(
        username=resolved["username"],
        role=resolved["role"],
        object_type=resolved["object_type"],
        object_name=resolved["object_name"],
        privilege=resolved["privilege"],
        ignore_excluded_roles=ignore_excluded_roles,
        refresh_state=False,  # Already refreshed above if needed
    )

    # Output
    if output == "text":
        typer.echo(cli.format_access_text(query_output))
    elif output == "json":
        cli.format_json(query_output)


@access_app.command()
def create(
    ctx: typer.Context,
    role: Optional[str] = typer.Option(None, help="Role to check CREATE privilege for"),
    username: Optional[str] = typer.Option(None, help="Username to check CREATE privilege for"),
    privilege: str = typer.Option("CREATE TABLE", help="CREATE privilege (e.g. 'CREATE TABLE', 'CREATE VIEW')"),
    scope: Optional[str] = typer.Option(None, help="Optional scope: DB or DB.SCHEMA to filter"),
    output: str = typer.Option("text", help="Output format: text, json"),
):
    """
    Check CREATE privileges for a user or role.

    Shows where the role/user can create objects — at account level,
    specific databases, or specific schemas. Optionally filter by a
    specific database or schema scope.

    Examples:
        snowglobe access create --role SYSADMIN --privilege "CREATE TABLE"
        snowglobe access create --role DEV_DW_DESIGNER --privilege "CREATE TABLE" --scope DEV_REFINED.UNIFIED
    """
    context = ctx.obj

    if not role and not username:
        typer.secho("Must provide --role or --username.", fg=typer.colors.RED)
        raise typer.Exit(1)

    access_service = AccessService(context)
    result = access_service.inspect_create(
        username=username,
        role=role,
        privilege=privilege,
        scope=scope,
    )

    if output == "text":
        typer.echo(cli.format_create_text(result))
    elif output == "json":
        cli.format_json(result)


@access_app.command()
def whoaccess(
    ctx: typer.Context,
    object_type: Optional[str] = typer.Option(None, "--object-type", help="Object type (e.g. TABLE, VIEW, SCHEMA)"),
    object_name: Optional[str] = typer.Option(None, "--object-name", help="Object FQN (e.g. DB.SCHEMA.TABLE)"),
    privilege: Optional[str] = typer.Option(None, "--privilege", help="Filter to a specific privilege (e.g. SELECT)"),
    output: str = typer.Option("text", help="Output format: text, json"),
):
    """
    Reverse lookup: who can access this object?

    Shows all roles and users that have access to the specified object,
    grouped by privilege. Optionally filter to a specific privilege.

    Examples:
        snowglobe access whoaccess --object-type TABLE --object-name DEV_REFINED.UNIFIED.HUB_EMAIL
        snowglobe access whoaccess --object-type TABLE --object-name DEV_REFINED.UNIFIED.HUB_EMAIL --privilege SELECT
    """
    context = ctx.obj
    access_service = AccessService(context)

    # Load state for interactive completions
    access_service.setup_state()
    access_service.load_state()

    # Resolve missing inputs interactively if TTY
    if not object_type or not object_name:
        from snowglobe.cli.prompts import is_interactive
        if not is_interactive():
            missing = []
            if not object_type:
                missing.append("--object-type")
            if not object_name:
                missing.append("--object-name")
            typer.secho(
                f"Error: Missing required arguments: {', '.join(missing)}.",
                fg=typer.colors.RED
            )
            raise typer.Exit(1)

        from prompt_toolkit import PromptSession
        from prompt_toolkit.completion import WordCompleter, FuzzyCompleter
        from snowglobe.models.access import ObjectType

        session = PromptSession()

        if not object_type:
            items = [ot.value for ot in ObjectType]
            word = WordCompleter(items, ignore_case=True)
            fuzzy = FuzzyCompleter(word)
            object_type = session.prompt(
                "Object type: ",
                completer=fuzzy,
                complete_while_typing=True,
            ).strip().upper()

        if not object_name:
            obj_index = access_service.object_index or {}
            items = obj_index.get(object_type.upper(), [])
            word = WordCompleter(items, ignore_case=True, sentence=True)
            fuzzy = FuzzyCompleter(word)
            object_name = session.prompt(
                "Object name (FQN): ",
                completer=fuzzy,
                complete_while_typing=True,
            ).strip()

    result = access_service.inspect_reverse(
        object_type=object_type,
        object_name=object_name,
        privilege=privilege,
    )

    if output == "text":
        typer.echo(cli.format_reverse_text(result))
    elif output == "json":
        cli.format_json(result)
