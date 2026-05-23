import typer
from snowglobe.core.optimizer import QueryOptimizerService
from snowglobe.core.query_service import QueryService
from snowglobe.output import cli

opt_app = typer.Typer(
    help="Query optimizer — analyze and suggest improvements for Snowflake queries",
    no_args_is_help=True,
)


@opt_app.command()
def query(
    ctx: typer.Context,
    query_id: str = typer.Option(..., help="Snowflake query ID to analyze"),
    no_ai: bool = typer.Option(False, "--no-ai", help="Skip AI analysis"),
    model: str = typer.Option("claude-haiku-4-5", help="Cortex AI model for suggestions"),
):
    """
    Analyze a query and provide optimization suggestions.
    Shows Snowflake-native insights, operator analysis, and optionally AI suggestions.
    """
    context = ctx.obj
    optimizer_service = QueryOptimizerService(context)
    optimizer_service.collect_query_profile(query_id)
    optimizer_service.analyze_query()

    # 1. Snowflake-native insights (primary)
    insights = optimizer_service.collect_insights()
    if insights:
        typer.echo(cli.format_query_insights(query_id, insights))

    # 2. Local rule-based suggestions
    opt_suggestions = optimizer_service.suggestions()
    typer.echo(cli.format_optimizer_suggestions(query_id, opt_suggestions.suggestions))

    # 3. Operator tree + scoring
    tree = optimizer_service.build_operator_tree()
    scores = optimizer_service.score()
    cli.print_operator_tree(tree, scores)

    # 4. Cost attribution
    opt_cost_attribution = optimizer_service.cost_attribution()
    typer.echo(cli.format_cost_attribution(opt_cost_attribution))

    # 5. Expensive operators
    opt_exp = optimizer_service.expensive_operators()
    typer.echo(cli.format_expensive_operators(opt_exp))

    # 6. AI suggestion (optional)
    if not no_ai:
        typer.echo("\nGenerating AI suggestions...")
        ai = optimizer_service.ai_suggestion(model=model)
        typer.echo(ai)


@opt_app.command()
def top_queries(
    ctx: typer.Context,
    days: int = typer.Option(7, help="Number of days of query history"),
    cost_type: str = typer.Option("credits", help="Sort query history by: credits, bytes"),
    limit: int = typer.Option(10, help="Number of top queries to analyze"),
    refresh_state: bool = typer.Option(False, help="Refresh state from Snowflake"),
    analyze: bool = typer.Option(False, help="Run optimizer analysis on each query"),
):
    """
    List top expensive queries, optionally with optimization analysis.
    """
    context = ctx.obj
    query_service = QueryService(context, days)
    output = query_service.inspect_query_history(
        refresh_state=refresh_state,
        cost_type=cost_type,
        limit=limit,
    )
    cli.print_table(output, title=f"Most expensive queries by: {cost_type}")

    if analyze:
        for query_id in output["query_id"]:
            typer.echo(f"\n{'═' * 60}")
            typer.echo(f"Analyzing: {query_id}")
            typer.echo(f"{'═' * 60}")

            optimizer_service = QueryOptimizerService(context)
            try:
                optimizer_service.collect_query_profile(query_id)
                optimizer_service.analyze_query()
                opt_result = optimizer_service.suggestions()
                typer.echo(cli.format_optimizer_suggestions(query_id, opt_result.suggestions))
            except Exception as e:
                typer.secho(f"  Could not analyze: {e}", fg=typer.colors.YELLOW)
