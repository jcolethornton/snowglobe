import typer

diff_app = typer.Typer(
    help="Compare Snowflake state over time",
    no_args_is_help=True,
)


@diff_app.command()
def access(
    ctx: typer.Context,
    days: int = typer.Option(
        None, "--days",
        help="Compare against N days ago. Default: since the last refresh.",
    ),
    output: str = typer.Option(
        "text", "--output",
        help="Output format: text, json",
    ),
):
    """
    Show access changes (grants, role edges, user assignments) since the
    last refresh, or in the last `--days` days.
    """
    from snowglobe.core.access_service import AccessService
    from snowglobe.output import cli

    service = AccessService(ctx.obj)
    result = service.detect_drift(days=days)

    if output == "json":
        cli.format_json(result)
    else:
        typer.echo(cli.format_drift_text(result))
