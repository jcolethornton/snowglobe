import typer
import pandas as pd
from snowglobe.core.cost_service import CostService
from snowglobe.output import cli

cost_app = typer.Typer(
    help="Inspect Snowflake costs — compute, storage, AI, budgets, and more",
    no_args_is_help=True,
)


def _get_cost_service(ctx: typer.Context) -> CostService:
    return CostService(ctx.obj)


def _export_csv(df, csv_path: str | None) -> bool:
    if csv_path:
        df.to_csv(csv_path, index=False)
        typer.secho(f"Exported to: {csv_path}", fg=typer.colors.GREEN)
        return True
    return False


def _print_note(note: str | None) -> None:
    if note:
        typer.secho(f"⚠  {note}", fg=typer.colors.YELLOW)


@cost_app.command()
def summary(
    ctx: typer.Context,
    days: int = typer.Option(30, help="Number of days to analyze"),
    csv: str = typer.Option(None, help="Export to CSV file path"),
    refresh: bool = typer.Option(False, help="Force fresh query to Snowflake"),
):
    """Account cost summary by service type."""
    cost_service = _get_cost_service(ctx)
    df, cache_age = cost_service.get_account_summary(days, refresh=refresh)
    if df.empty:
        typer.echo("No cost data found.")
        return
    if _export_csv(df, csv):
        return
    total = df["CREDITS"].sum()
    typer.secho(f"\nTotal: {total:,.2f} credits ({days} days)", fg=typer.colors.GREEN, bold=True)
    typer.echo("")
    for _, row in df.iterrows():
        bar_len = int(row["PCT"] / 2)
        bar = "█" * bar_len
        typer.echo(f"  {row['SERVICE_TYPE']:<40} {row['CREDITS']:>10,.2f}  {row['PCT']:>5.1f}%  {bar}")
    typer.echo("")


@cost_app.command()
def warehouses(
    ctx: typer.Context,
    days: int = typer.Option(30, help="Number of days to analyze"),
    csv: str = typer.Option(None, help="Export to CSV file path"),
    refresh: bool = typer.Option(False, help="Force fresh query to Snowflake"),
):
    """Cost breakdown per warehouse."""
    cost_service = _get_cost_service(ctx)
    df, _ = cost_service.get_warehouse_breakdown(days, refresh=refresh)
    if df.empty:
        typer.echo("No warehouse data found.")
        return
    if _export_csv(df, csv):
        return
    cli.print_table(df, title=f"Warehouse Costs ({days} days)")


@cost_app.command()
def users(
    ctx: typer.Context,
    days: int = typer.Option(7, help="Number of days to analyze (max 7 recommended)"),
    csv: str = typer.Option(None, help="Export to CSV file path"),
    refresh: bool = typer.Option(False, help="Force fresh query to Snowflake"),
):
    """Complete cost per user — warehouse + AI services."""
    cost_service = _get_cost_service(ctx)
    df, _, note = cost_service.get_user_breakdown(min(days, 7), refresh=refresh)
    if df.empty:
        typer.echo("No user data found.")
        return
    if _export_csv(df, csv):
        return
    _print_note(note)
    cli.print_table(df, title=f"User Cost Attribution ({days} days)")


@cost_app.command()
def ai(
    ctx: typer.Context,
    days: int = typer.Option(30, help="Number of days to analyze"),
    csv: str = typer.Option(None, help="Export to CSV file path"),
    refresh: bool = typer.Option(False, help="Force fresh query to Snowflake"),
):
    """AI/ML token costs by service type."""
    cost_service = _get_cost_service(ctx)
    df, _, note = cost_service.get_ai_costs(days, refresh=refresh)
    if df.empty:
        typer.echo("No AI usage found.")
        return
    if _export_csv(df, csv):
        return
    _print_note(note)
    total = df["TOTAL_CREDITS"].astype(float).sum()
    typer.secho(f"\nTotal AI credits: {total:,.2f} ({days} days)", fg=typer.colors.GREEN, bold=True)
    typer.echo("")
    for _, row in df.iterrows():
        bar_len = int(row["PCT"] / 2)
        bar = "█" * bar_len
        typer.echo(f"  {row['SERVICE']:<30} {float(row['TOTAL_CREDITS']):>10,.2f}  {row['PCT']:>5.1f}%  {bar}")
    typer.echo("")


@cost_app.command(name="ai-users")
def ai_users(
    ctx: typer.Context,
    days: int = typer.Option(30, help="Number of days to analyze"),
    csv: str = typer.Option(None, help="Export to CSV file path"),
    refresh: bool = typer.Option(False, help="Force fresh query to Snowflake"),
):
    """AI/ML token costs per user with service breakdown."""
    cost_service = _get_cost_service(ctx)
    df, _, note = cost_service.get_ai_costs_by_user(days, refresh=refresh)
    if df.empty:
        typer.echo("No AI usage found.")
        return
    if _export_csv(df, csv):
        return
    _print_note(note)
    cli.print_table(df, title=f"AI Token Costs by User ({days} days)")


@cost_app.command()
def services(
    ctx: typer.Context,
    days: int = typer.Option(30, help="Number of days to analyze"),
    csv: str = typer.Option(None, help="Export to CSV file path"),
    refresh: bool = typer.Option(False, help="Force fresh query to Snowflake"),
):
    """Non-warehouse service costs — pipes, tasks, SPCS, clustering."""
    cost_service = _get_cost_service(ctx)
    df, _ = cost_service.get_service_breakdown(days, refresh=refresh)
    if df.empty:
        typer.echo("No service cost data found.")
        return
    if _export_csv(df, csv):
        return
    cli.print_table(df, title=f"Service Resource Costs ({days} days)")


@cost_app.command()
def queries(
    ctx: typer.Context,
    days: int = typer.Option(7, help="Number of days of query history"),
    limit: int = typer.Option(10, help="Number of queries to return"),
    sort_by: str = typer.Option("credits", help="Sort by: credits or bytes"),
    csv: str = typer.Option(None, help="Export to CSV file path"),
    refresh: bool = typer.Option(False, help="Force fresh query to Snowflake"),
):
    """Top expensive individual queries by attributed credits."""
    cost_service = _get_cost_service(ctx)
    df, _, note = cost_service.get_top_queries(days, limit=limit, sort_by=sort_by, refresh=refresh)
    if df.empty:
        typer.echo("No query data found.")
        return
    if _export_csv(df, csv):
        return
    _print_note(note)
    cli.print_table(df, title=f"Top Expensive Queries ({days} days)")


@cost_app.command()
def trend(
    ctx: typer.Context,
    days: int = typer.Option(30, help="Number of days for trend analysis"),
    csv: str = typer.Option(None, help="Export to CSV file path"),
    refresh: bool = typer.Option(False, help="Force fresh query to Snowflake"),
):
    """Daily spend trend with day-over-day delta and 7-day rolling average."""
    cost_service = _get_cost_service(ctx)
    df, cache_age = cost_service.get_daily_trend(days, refresh=refresh)
    if df.empty:
        typer.echo("No trend data found.")
        return
    if _export_csv(df, csv):
        return

    total = df["CREDITS"].sum()
    avg_daily = df["CREDITS"].mean()
    typer.secho(f"\nTotal: {total:,.2f} credits | Avg daily: {avg_daily:,.2f}", fg=typer.colors.GREEN, bold=True)
    typer.echo("")
    typer.echo(f"  {'DATE':<12} {'CREDITS':>10} {'DELTA %':>9} {'7D AVG':>10}  {'TREND'}")
    typer.echo(f"  {'─' * 12} {'─' * 10} {'─' * 9} {'─' * 10}  {'─' * 20}")
    max_credits = df["CREDITS"].max() if not df.empty else 1
    for _, row in df.iterrows():
        bar_len = int((row["CREDITS"] / max_credits) * 20) if max_credits > 0 else 0
        bar = "▓" * bar_len
        delta_str = f"{row['DELTA_PCT']:+.1f}%" if pd.notna(row["DELTA_PCT"]) else "    —"
        avg_str = f"{row['ROLLING_7D_AVG']:,.2f}" if pd.notna(row["ROLLING_7D_AVG"]) else "—"
        typer.echo(f"  {str(row['DATE']):<12} {row['CREDITS']:>10,.2f} {delta_str:>9} {avg_str:>10}  {bar}")
    typer.echo("")


@cost_app.command()
def storage(
    ctx: typer.Context,
    days: int = typer.Option(30, help="Number of days to average storage over"),
    csv: str = typer.Option(None, help="Export to CSV file path"),
    refresh: bool = typer.Option(False, help="Force fresh query to Snowflake"),
):
    """Per-database storage breakdown with estimated monthly cost."""
    cost_service = _get_cost_service(ctx)
    df, _ = cost_service.get_storage_usage(days, refresh=refresh)
    if df.empty:
        typer.echo("No storage data found.")
        return
    if _export_csv(df, csv):
        return

    total_tb = df["TOTAL_TB"].sum()
    total_cost = df["EST_MONTHLY_COST"].sum()
    rate = cost_service.get_storage_rate()
    typer.secho(f"\nTotal storage: {total_tb:,.4f} TB | Est. monthly: ${total_cost:,.2f}", fg=typer.colors.GREEN, bold=True)
    rate_source = "contracted rate" if rate != 23.0 else "on-demand default"
    typer.echo(f"(Estimated at ${rate:.2f}/TB/month — {rate_source})")
    typer.echo("")
    display_df = df[["DATABASE_NAME", "TOTAL_TB", "EST_MONTHLY_COST"]].copy()
    display_df = display_df[display_df["TOTAL_TB"] > 0]
    if not display_df.empty:
        cli.print_table(display_df, title=f"Storage by Database ({days}-day avg)")


@cost_app.command()
def budget(
    ctx: typer.Context,
    csv: str = typer.Option(None, help="Export to CSV file path"),
):
    """Snowflake-native budget status and spending history."""
    cost_service = _get_cost_service(ctx)
    df, error = cost_service.get_budget_status()
    if error:
        typer.secho(error, fg=typer.colors.YELLOW)
        return
    if df.empty:
        typer.echo("No budget spending history found.")
        return
    if _export_csv(df, csv):
        return
    cli.print_table(df, title="Budget Spending History")


@cost_app.command()
def replication(
    ctx: typer.Context,
    days: int = typer.Option(30, help="Number of days to analyze"),
    csv: str = typer.Option(None, help="Export to CSV file path"),
    refresh: bool = typer.Option(False, help="Force fresh query to Snowflake"),
):
    """Replication costs by replication group."""
    cost_service = _get_cost_service(ctx)
    df, _ = cost_service.get_replication_costs(days, refresh=refresh)
    if df.empty:
        typer.echo("No replication cost data found.")
        return
    if _export_csv(df, csv):
        return
    cli.print_table(df, title=f"Replication Costs ({days} days)")


@cost_app.command(name="mv")
def materialized_views(
    ctx: typer.Context,
    days: int = typer.Option(30, help="Number of days to analyze"),
    csv: str = typer.Option(None, help="Export to CSV file path"),
    refresh: bool = typer.Option(False, help="Force fresh query to Snowflake"),
):
    """Materialized view refresh costs."""
    cost_service = _get_cost_service(ctx)
    df, _ = cost_service.get_materialized_view_costs(days, refresh=refresh)
    if df.empty:
        typer.echo("No materialized view cost data found.")
        return
    if _export_csv(df, csv):
        return
    total = df["CREDITS"].sum() if "CREDITS" in df.columns else 0
    typer.secho(f"\nTotal MV refresh credits: {total:,.2f}", fg=typer.colors.GREEN, bold=True)
    typer.echo("")
    cli.print_table(df, title=f"Materialized View Costs ({days} days)")
