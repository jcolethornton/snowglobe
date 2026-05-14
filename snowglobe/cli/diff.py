import typer

diff_app = typer.Typer(
    help="Compare Snowflake state over time",
    no_args_is_help=True,
)

@diff_app.command()
def access():
    """Diff access and grants between snapshots"""
    raise NotImplementedError("diff access not implemented yet")
