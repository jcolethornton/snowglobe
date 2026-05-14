import typer
from snowglobe.cli.context import SnowglobeContext
from snowglobe.cli.access import access_app
from snowglobe.cli.optimizer import opt_app
from snowglobe.cli.cost import cost_app
from snowglobe.cli.diff import diff_app
from snowglobe.cli.report import report_app
from snowglobe.cli.shell import shell_app

app = typer.Typer(
    help="Snowglobe — Explainable cost and access visibility for Snowflake",
    no_args_is_help=True,
    context_settings={"ignore_unknown_options": True}
)

app.add_typer(shell_app, name="shell")
app.add_typer(access_app, name="access")
app.add_typer(cost_app, name="cost")
app.add_typer(diff_app, name="diff")
app.add_typer(opt_app, name="optimize")
app.add_typer(report_app, name="report")

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
    """
    context = SnowglobeContext(
        profile_name=profile_name,
        role=role,
        output=output,
        verbose=verbose
    )
    context.load_profile()
    ctx.obj = context
