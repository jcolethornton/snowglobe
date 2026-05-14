import typer
from snowglobe.core.query_service import QueryService
from snowglobe.output import cli

cost_app = typer.Typer(
    help="Inspect Snowflake costs",
    no_args_is_help=True,
)
# TODO
# Subcommands:
# queries – top expensive queries
# users – cost per user (next section)
# warehouses – cost per warehouse (optional)
# Options:
# --top N – number of queries to show
# --metric [credits|bytes] – how to measure cost

@cost_app.command()
def queries(
    ctx: typer.Context,
    days: int = typer.Option(7, help="Number of days of query history"),
    cost_type: str = typer.Option("credits", help="Sort query history by : credits, bytes"),
    refresh_state: bool = typer.Option(False, help="Refresh state from Snowflake")
    ):

    context = ctx.obj
    query_service = QueryService(context, days)
    output = query_service.inspect_query_history(
        refresh_state=refresh_state,
        cost_type=cost_type,
        limit=10
    )
    cli.print_table(output, title=f"Most expensive queries by: {cost_type}")

