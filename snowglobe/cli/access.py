import typer
from typing import Optional
from snowglobe.core.access_service import AccessService
from snowglobe.output import cli

access_app = typer.Typer(
    help="Inspect Snowflake access and identify roles/users with access and privileges on database objects",
    no_args_is_help=True,
)
# TODO
# Subcommands:
# check – check access for users/roles
# list – list all objects a user/role can access (optional)
# roles – show roles that have access to an object
# privileges – show privileges per object
# owbernship – show object ownership and responsibility

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

    context = ctx.obj
    access_service = AccessService(context)

    # Result
    query_output = access_service.inspect_access(
        username=username,
        role=role,
        object_type=object_type,
        object_name=object_name,
        privilege=privilege,
        ignore_excluded_roles=ignore_excluded_roles,
        refresh_state=refresh_state,
    )

    # Output
    if output == "text":
        typer.echo(cli.format_access_text(query_output))
    if output == "json":
        typer.echo(cli.format_json(query_output))
