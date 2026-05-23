import typer
from datetime import date

report_app = typer.Typer(
    help="Generate summarized reports — cost, AI, storage, queries",
    no_args_is_help=True,
)


def _default_output_path() -> str:
    return f"snowglobe_report_{date.today().isoformat()}.md"


@report_app.command()
def full(
    ctx: typer.Context,
    days: int = typer.Option(30, help="Number of days to cover"),
    top: int = typer.Option(10, help="Number of top queries to include"),
    output: str = typer.Option(None, "--output", "-o", help="Output file path (default: snowglobe_report_DATE.md)"),
):
    """Generate a full report: cost summary, AI costs, storage, top queries."""
    from snowglobe.core.report_service import ReportService

    output_path = output or _default_output_path()
    context = ctx.obj

    typer.echo(f"\nGenerating full report ({days} days)...")
    service = ReportService(context)
    _, data = service.generate_and_save(output_path, days=days, top_n=top)

    # Print terminal summary
    typer.echo(service.terminal_summary(data))
    typer.secho(f"  Report saved: {output_path}", fg=typer.colors.GREEN, bold=True)
    typer.echo("")


@report_app.command()
def cost(
    ctx: typer.Context,
    days: int = typer.Option(30, help="Number of days to cover"),
    output: str = typer.Option(None, "--output", "-o", help="Output file path"),
):
    """Generate a cost-focused report: summary, AI, storage."""
    from snowglobe.core.report_service import ReportService

    output_path = output or f"snowglobe_cost_{date.today().isoformat()}.md"
    context = ctx.obj

    typer.echo(f"\nGenerating cost report ({days} days)...")
    service = ReportService(context)
    data = service.generate_full_report(days=days, top_n=0)
    # Clear queries for cost-only report
    data["top_queries"] = []
    markdown = service.render_markdown(data)

    from pathlib import Path
    Path(output_path).write_text(markdown)

    typer.echo(service.terminal_summary(data))
    typer.secho(f"  Report saved: {output_path}", fg=typer.colors.GREEN, bold=True)
    typer.echo("")


@report_app.command()
def queries(
    ctx: typer.Context,
    days: int = typer.Option(7, help="Number of days to cover"),
    top: int = typer.Option(10, help="Number of queries to include"),
    output: str = typer.Option(None, "--output", "-o", help="Output file path"),
):
    """Generate a top-queries report with optimization details."""
    from snowglobe.core.cost_service import CostService
    from snowglobe.output import cli

    context = ctx.obj
    cost_service = CostService(context)

    typer.echo(f"\nFetching top {top} queries ({days} days)...")
    df, _ = cost_service.get_top_queries(days=days, limit=top)

    if df.empty:
        typer.echo("  No query data found.")
        return

    # Terminal output
    cli.print_table(df, title=f"Top {top} Expensive Queries ({days} days)")

    # Save to file if requested
    if output:
        df.to_csv(output, index=False)
        typer.secho(f"\n  Exported to: {output}", fg=typer.colors.GREEN)
