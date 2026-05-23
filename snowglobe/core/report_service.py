"""
Report generation service for Snowglobe.

Orchestrates data collection from CostService and renders markdown reports
using Jinja2 templates.
"""
from datetime import datetime, timezone
from pathlib import Path

import jinja2

from snowglobe.core.cost_service import CostService

TEMPLATE_DIR = Path(__file__).parent.parent / "templates"


class ReportService:
    """Generates combined cost/query/storage reports."""

    def __init__(self, context):
        self.context = context
        self.cost_service = CostService(context)
        self.env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(TEMPLATE_DIR)),
            undefined=jinja2.StrictUndefined,
        )

    def generate_full_report(self, days: int = 30, top_n: int = 10) -> dict:
        """
        Collect all report data. Returns a dict with DataFrames and metadata.
        """
        # Cost summary
        cost_df, _ = self.cost_service.get_account_summary(days)
        cost_total = float(cost_df["CREDITS"].sum()) if not cost_df.empty else 0

        # AI costs
        ai_df, _ = self.cost_service.get_ai_costs(days)
        ai_total = float(ai_df["TOTAL_CREDITS"].sum()) if not ai_df.empty else 0

        # Storage
        storage_df, _ = self.cost_service.get_storage_usage(days)
        storage_total_tb = float(storage_df["TOTAL_TB"].sum()) if not storage_df.empty else 0
        storage_total_cost = float(storage_df["EST_MONTHLY_COST"].sum()) if not storage_df.empty else 0
        storage_rate = self.cost_service.get_storage_rate()
        storage_rate_source = "contracted rate" if storage_rate != 23.0 else "$23/TB on-demand default"

        # Top queries
        queries_df, _ = self.cost_service.get_top_queries(days=min(days, 7), limit=top_n)

        return {
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "account": self.context.profile.get("account", "unknown"),
            "profile": self.context.profile_name,
            "days": days,
            "cost_summary": cost_df.to_dict("records") if not cost_df.empty else [],
            "cost_total": cost_total,
            "ai_costs": ai_df.to_dict("records") if not ai_df.empty else [],
            "ai_total": ai_total,
            "storage": storage_df.to_dict("records") if not storage_df.empty else [],
            "storage_total_tb": storage_total_tb,
            "storage_total_cost": storage_total_cost,
            "storage_rate_source": storage_rate_source,
            "top_queries": queries_df.to_dict("records") if not queries_df.empty else [],
        }

    def render_markdown(self, data: dict) -> str:
        """Render the report data to a markdown string."""
        template = self.env.get_template("report.md.j2")
        return template.render(**data)

    def generate_and_save(self, output_path: str, days: int = 30, top_n: int = 10) -> tuple[str, dict]:
        """
        Generate report, save to file, return (markdown_content, data_dict).
        """
        data = self.generate_full_report(days=days, top_n=top_n)
        markdown = self.render_markdown(data)

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(markdown)

        return markdown, data

    def terminal_summary(self, data: dict) -> str:
        """Generate a concise terminal summary from report data."""
        lines = []
        lines.append("")
        lines.append(f"  Snowglobe Report — {data['account']} ({data['days']} days)")
        lines.append(f"  {'─' * 45}")

        # Cost
        lines.append(f"  Total spend:        {data['cost_total']:,.2f} credits")
        if data["cost_summary"]:
            top3 = sorted(data["cost_summary"], key=lambda x: x.get("CREDITS", 0), reverse=True)[:3]
            drivers = ", ".join(f"{r['SERVICE_TYPE']} ({r['CREDITS']:.0f})" for r in top3)
            lines.append(f"  Top drivers:        {drivers}")

        # AI
        lines.append(f"  AI credits:         {data['ai_total']:,.2f}")

        # Storage
        lines.append(f"  Storage:            {data['storage_total_tb']:,.4f} TB (est. ${data['storage_total_cost']:,.2f}/mo)")

        # Queries
        if data["top_queries"]:
            top_q = data["top_queries"][0]
            lines.append(f"  Most expensive:     {top_q.get('QUERY_ID', '?')[:20]}... ({top_q.get('CREDITS', 0):.4f} credits)")

        lines.append("")
        return "\n".join(lines)
