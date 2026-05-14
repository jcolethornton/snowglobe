import typer
from snowglobe.core.optimizer import QueryOptimizerService
from snowglobe.core.query_service import QueryService
from snowglobe.output import cli

opt_app = typer.Typer(
    help="Query optimizer",
    no_args_is_help=True,
)

@opt_app.command()
def query(
    ctx: typer.Context,
    query_id: str = typer.Option(None, help="Snowflake query ID"),
):
    """
    Analyze and provide optimization suggestions for a query.
    """

    context = ctx.obj
    optimizer_service = QueryOptimizerService(context)
    optimizer_service.collect_query_profile(query_id)
    optimizer_service.analyze_query()
    opt_suggestions = optimizer_service.suggestions()

    suggestions = cli.format_optimizer_suggestions(
        query_id,
        opt_suggestions.suggestions
    )
    typer.echo(suggestions)

    tree = optimizer_service.build_operator_tree()
    scores = optimizer_service.score()
    cli.print_operator_tree(tree, scores)

    opt_cost_attribution = optimizer_service.cost_attribution()
    cost_attribution = cli.format_cost_attribution(opt_cost_attribution)
    typer.echo(cost_attribution)

    opt_exp = optimizer_service.expensive_operators()
    exp = cli.format_expensive_operators(opt_exp)
    typer.echo(exp)

    # AI
    ai = optimizer_service.ai_suggestion()
    from pathlib import Path
    output_path = Path("ai_suggestion.sql")
    with output_path.open("w") as f:
        f.write(ai)

    typer.echo(ai)



@opt_app.command()
def top_queries(
    ctx: typer.Context,
    days: int = typer.Option(7, help="Number of days of query history"),
    cost_type: str = typer.Option("credits", help="Sort query history by : credits, bytes"),
    limit: int = typer.Option(10, help="Number of top queries to analyze"),
    refresh_state: bool = typer.Option(False, help="Refresh state from Snowflake")
):
    """
    Analyze and provide optimization suggestions for top queries.
    """

    context = ctx.obj
    query_service = QueryService(context, days)
    output = query_service.inspect_query_history(
        refresh_state=refresh_state,
        cost_type=cost_type,
        limit=limit
    )
    cli.print_table(output, title=f"Most expensive queries by: {cost_type}")

    for query_id in output["query_id"]:

        optimizer_service = QueryOptimizerService(context)
        optimizer_service.collect_query_profile(query_id)
        result = optimizer_service.analyze_query()

        typer.echo(cli.format_optimizer_suggestions(query_id, result.suggestions))
