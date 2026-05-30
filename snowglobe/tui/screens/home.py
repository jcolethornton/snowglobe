"""Home — landing dashboard.

Three KPI cards (Cache / Connection / This week) at the top.
Below: 30d spend trend (left) and recent expensive queries (right).
Both panels fire Snowflake workers on mount; KPI data is local/instant.
"""
from datetime import datetime, timezone

import pandas as pd

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Static


CACHE_TTL_SECONDS = 3600  # mirror CostService.CACHE_TTL_SECONDS


class HomeScreen(Vertical):
    """Landing dashboard."""

    BINDINGS = [
        ("a", "jump('access')",  "Access check"),
        ("w", "jump('access')",  "Who-access"),
        ("c", "jump('cost')",    "Cost"),
        ("s", "jump('risk')",    "Risk scan"),
        ("r", "jump('refresh')", "Refresh"),
    ]

    def compose(self) -> ComposeResult:
        yield Static("Home", classes="screen-title")

        with Horizontal(id="home-kpis"):
            with Vertical(classes="kpi-card"):
                yield Static("Cache",      classes="kpi-title")
                yield Static("loading…",   id="kpi-cache", classes="kpi-body")
            with Vertical(classes="kpi-card"):
                yield Static("Connection", classes="kpi-title")
                yield Static("loading…",   id="kpi-conn", classes="kpi-body")
            with Vertical(classes="kpi-card"):
                yield Static("This week",  classes="kpi-title")
                yield Static("loading…",   id="kpi-week", classes="kpi-body")

        with Horizontal(id="home-body"):
            with Vertical(id="home-trend", classes="panel"):
                yield Static("30d spend trend", classes="panel-title")
                yield DataTable(id="home-trend-table",
                                cursor_type="row", zebra_stripes=True)
            with Vertical(id="home-queries", classes="panel"):
                yield Static("Recent expensive queries (7d)", classes="panel-title")
                yield DataTable(id="home-queries-table",
                                cursor_type="row", zebra_stripes=True)

    # --- Lifecycle ----------------------------------------------------

    def on_mount(self) -> None:
        self._refresh_kpis()
        # Re-render KPIs whenever the app-level cache age ticks (every 30s).
        self.watch(self.app, "cache_age_minutes", lambda _v: self._refresh_kpis())
        # Fire both Snowflake workers on mount (different groups → concurrent).
        self._fetch_trend()
        self._fetch_queries()

    # --- Hotkey action -----------------------------------------------

    def action_jump(self, screen: str) -> None:
        self.app.action_switch(screen)

    # --- KPI cards (all local — instant) ------------------------------

    def _refresh_kpis(self) -> None:
        self._render_cache_kpi()
        self._render_connection_kpi()
        self._render_week_kpi()

    def _render_cache_kpi(self) -> None:
        from snowglobe.state.db import StateDB
        db = StateDB()

        def count(table: str) -> int:
            try:
                return db.conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            except Exception:
                return 0

        grants = count("grants")
        edges = count("role_edges")
        users = count("user_roles")

        refreshed_at = db.get_refreshed_at()
        age_str = "never"
        if refreshed_at:
            try:
                refreshed = datetime.fromisoformat(refreshed_at)
                age = datetime.now(timezone.utc) - refreshed
                hours = age.total_seconds() / 3600
                if hours < 1:
                    age_str = f"{int(age.total_seconds() / 60)}m ago"
                elif hours < 24:
                    age_str = f"{int(hours)}h ago"
                else:
                    age_str = f"{int(hours // 24)}d ago"
            except (ValueError, TypeError):
                age_str = "unknown"

        text = (
            f"{grants:>9,} grants\n"
            f"{edges:>9,} role edges\n"
            f"{users:>9,} user assignments\n"
            f"refreshed  {age_str}"
        )
        self.query_one("#kpi-cache", Static).update(text)

    def _render_connection_kpi(self) -> None:
        profile = self.app.context.profile or {}
        account = profile.get("account") or "(no profile)"
        role = profile.get("role") or "(no role)"
        warehouse = profile.get("warehouse") or "(no warehouse)"
        text = (
            f"✓ {account}\n"
            f"✓ {role}\n"
            f"✓ {warehouse}\n"
            f"ACCOUNT_USAGE lag ~45m"
        )
        self.query_one("#kpi-conn", Static).update(text)

    def _render_week_kpi(self) -> None:
        from snowglobe.state.db import StateDB
        db = StateDB()

        # 7d cost summary, only if cached fresh — don't fetch Snowflake from Home.
        week_credits = "Visit Cost ▸ Summary"
        try:
            age = db.get_cost_cache_age("cost_summary_7d_fetched_at")
            if age is not None and age < CACHE_TTL_SECONDS:
                cached = db.get_cost_summary_cache()
                if cached:
                    total = sum(float(r.get("CREDITS", 0) or 0) for r in cached)
                    week_credits = f"{total:,.0f} credits (cached)"
        except Exception:
            pass

        # Risk count from last scan
        risk_line = "(no scan yet — press s)"
        try:
            scan = db.get_json_cache("scan_results_last") or []
            high = sum(1 for s in scan if s.get("risk_score", 0) >= 10)
            medium = sum(1 for s in scan if 5 <= s.get("risk_score", 0) < 10)
            if high or medium:
                risk_line = f"{high} high-risk, {medium} medium"
            else:
                risk_line = "0 flagged roles"
        except Exception:
            pass

        text = (
            f"{week_credits}\n"
            f"\n"
            f"Risk:\n"
            f"  {risk_line}"
        )
        self.query_one("#kpi-week", Static).update(text)

    # --- 30d spend trend (one Snowflake call on mount) ---------------

    @work(thread=True, exclusive=True, group="trend")
    def _fetch_trend(self) -> None:
        try:
            df, _ = self.app.get_cost_service().get_daily_trend(days=30)
        except Exception as e:
            self.app.call_from_thread(self._trend_failed, e)
            return
        self.app.call_from_thread(self._render_trend, df)

    def _trend_failed(self, err: Exception) -> None:
        table = self.query_one("#home-trend-table", DataTable)
        table.clear(columns=True)
        table.add_columns(f"(could not load — {err})")

    def _render_trend(self, df: pd.DataFrame) -> None:
        table = self.query_one("#home-trend-table", DataTable)
        table.clear(columns=True)
        if df is None or df.empty:
            table.add_columns("(no trend data)")
            return
        table.add_columns("DATE", "CREDITS", "TREND")
        max_c = float(df["CREDITS"].max()) if not df.empty else 1.0
        for _, row in df.iterrows():
            credits = float(row["CREDITS"])
            bar_width = max(1, int(credits / max_c * 20)) if max_c > 0 else 0
            table.add_row(
                str(row["DATE"]),
                f"{credits:,.2f}",
                "█" * bar_width,
                key=str(row["DATE"]),
            )

    # --- Recent expensive queries (one Snowflake call on mount) -----

    @work(thread=True, exclusive=True, group="cost")
    def _fetch_queries(self) -> None:
        try:
            df, _, _ = self.app.get_cost_service().get_top_queries(days=7, limit=5)
        except Exception as e:
            self.app.call_from_thread(self._queries_failed, e)
            return
        self.app.call_from_thread(self._render_queries, df)

    def _queries_failed(self, err: Exception) -> None:
        table = self.query_one("#home-queries-table", DataTable)
        table.clear(columns=True)
        table.add_columns(f"(could not load — {err})")

    def _render_queries(self, df: pd.DataFrame) -> None:
        table = self.query_one("#home-queries-table", DataTable)
        table.clear(columns=True)
        if df is None or df.empty:
            table.add_columns("(no recent expensive queries)")
            return
        table.add_columns("CREDITS", "WAREHOUSE", "USER", "TYPE", "PREVIEW")
        for _, row in df.iterrows():
            table.add_row(
                f"{float(row.get('CREDITS', 0)):.2f}",
                str(row.get("WAREHOUSE_NAME", ""))[:18],
                str(row.get("USER_NAME", ""))[:24],
                str(row.get("QUERY_TYPE", "")),
                str(row.get("QUERY_PREVIEW", ""))[:48],
                key=str(row.get("QUERY_ID", "")),
            )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        key = event.row_key.value if event.row_key else None
        if not key:
            return

        if event.data_table.id == "home-trend-table":
            # Drill into that day on the Cost screen.
            try:
                from textual.widgets import ContentSwitcher
                from snowglobe.tui.screens.cost import CostScreen
                self.app.query_one(ContentSwitcher).current = "cost"
                self.app.query_one(CostScreen)._fetch_day_drill(key)
            except Exception as e:
                self.app.notify(f"Could not open day detail: {e}", severity="warning", timeout=4)
        else:
            # Queries table — open in Tune.
            try:
                from textual.widgets import ContentSwitcher, Input
                from snowglobe.tui.screens.tune import TuneScreen
                self.app.query_one(ContentSwitcher).current = "tune"
                tune = self.app.query_one(TuneScreen)
                tune.query_one("#tu-query-id", Input).value = key
                self.app.notify(f"Loaded {key[:24]}… into Tune. Press Analyse.", timeout=4)
            except Exception:
                self.app.notify(f"Query: {key[:24]}…", timeout=4)
