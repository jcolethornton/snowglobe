import typer
from snowglobe.cli.context import SnowglobeContext
from snowglobe.cli.access import access_app
from snowglobe.cli.optimizer import opt_app
from snowglobe.cli.cost import cost_app
from snowglobe.cli.diff import diff_app
from snowglobe.cli.report import report_app
from snowglobe.cli.debug import debug_app

app = typer.Typer(
    help="Snowglobe — Explainable cost and access visibility for Snowflake",
    no_args_is_help=False,
    context_settings={"ignore_unknown_options": True}
)

app.add_typer(access_app, name="access")
app.add_typer(cost_app, name="cost")
app.add_typer(diff_app, name="diff")
app.add_typer(opt_app, name="optimize")
app.add_typer(report_app, name="report")
app.add_typer(debug_app, name="debug")


@app.command()
def refresh(
    ctx: typer.Context,
    full: bool = typer.Option(False, "--full", help="Force full refresh (ignore incremental)")
):
    """Refresh cached state from Snowflake. Incremental by default."""
    from snowglobe.core.access_service import AccessService

    context = ctx.obj
    service = AccessService(context)
    service.setup_state()

    service.refresh_state(full=full)

    typer.secho(f"  Users:        {len(service.user_graph.assigned_roles)}", fg=typer.colors.GREEN)
    typer.secho(f"  Roles:        {len(service.role_graph.parents)}", fg=typer.colors.GREEN)
    total_objects = sum(len(v) for v in service.object_index.values())
    typer.secho(f"  Object index: {total_objects} FQNs", fg=typer.colors.GREEN)
    typer.secho("Done.", fg=typer.colors.GREEN, bold=True)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    profile_name: str = typer.Option(
        "default",
        "--profile",
        help="Snowflake connection profile to use",
    ),
    role: str | None = typer.Option(
        None,
        "--role",
        help="Override Snowflake role",
    ),
    output: str = typer.Option(
        "table",
        "--output",
        help="Output format: table | json",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose output"
    )
):
    """
    Inspect and understand Snowflake cost, access, and ownership.

    Snowglobe is read-only by design.
    Run without a command to start the interactive shell.
    """
    context = SnowglobeContext(
        profile_name=profile_name,
        role=role,
        output=output,
        verbose=verbose
    )
    context.load_profile()
    ctx.obj = context

    # No subcommand → launch interactive shell
    if ctx.invoked_subcommand is None:
        from snowglobe.cli.shell import start_shell
        start_shell(context)
