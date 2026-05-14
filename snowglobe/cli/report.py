import typer

report_app = typer.Typer(
    help="Generate summarized reports",
    no_args_is_help=True,
)

@report_app.command()
def cost():
    """Generate cost summary reports"""
    raise NotImplementedError("report cost not implemented yet")

@report_app.command()
def access():
    """Generate access and permission reports"""
    raise NotImplementedError("report access not implemented yet")

