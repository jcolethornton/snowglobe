"""Cost screen — Summary, Trend, Top queries, Warehouses, Users, AI, Storage, and more.

Layout:
  ┌─ window: 30d ▾    [ Re-fetch ] ─────────────────────────────────┐
  │ ┌─ views ──────────┐ ┌─ status ─────────────────────────────┐  │
  │ │ ▸ Summary        │ │ DataTable rendering the active view  │  │
  │ │   Trend          │ │                                       │  │
  │ │   Top queries    │ │                                       │  │
  │ │   Warehouses     │ │                                       │  │
  │ │   ...            │ │                                       │  │
  │ └──────────────────┘ └───────────────────────────────────────┘  │
  └──────────────────────────────────────────────────────────────────┘
"""
import pandas as pd

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Label, ListItem, ListView, Select, Static


_BAR_WIDTH = 24  # max █ characters in trend column
_WAREHOUSE_SERVICE_TYPE = "WAREHOUSE_METERING"
_AI_SERVICE_KEYWORDS = ("AI", "CORTEX", "INTELLIGENCE")


def _bar(pct_or_ratio: float, width: int = _BAR_WIDTH) -> str:
    """Render a percentage-style bar (input clamped to [0, 1])."""
    n = max(0, min(width, int(round(pct_or_ratio * width))))
    return "█" * n


class CostScreen(Vertical):
    """Cost analysis — Summary, trend, top queries, warehouses, users, AI, storage, and more."""

    BINDINGS = [
        ("escape", "back_from_drill", "Back"),
        ("r",      "refetch",         "Re-fetch"),
    ]

    # Active view: "summary" | "trend" | "top_queries" | "warehouses" | "users"
    # | "ai" | "ai_users" | "services" | "storage" | "replication" | "mv" | "budget"
    # | "drill_service" | "drill_warehouse" | "drill_user"
    # | "drill_day" | "drill_day_resource" | "drill_day_resource_users" | "drill_day_user_queries"
    _current_view: str = "summary"
    _drill_service: str | None = None
    _drill_warehouse: str | None = None
    _drill_user: str | None = None
    _drill_day: str | None = None
    _drill_day_service_type: str | None = None
    _drill_day_resource: str | None = None
    _drill_day_user: str | None = None
    # Becomes True after the user explicitly picks a view, so Select.Changed
    # events fired during the initial mount don't auto-trigger a Snowflake fetch.
    _user_initiated: bool = False

    def compose(self) -> ComposeResult:
        yield Static("Cost", classes="screen-title")

        with Horizontal(id="cost-controls"):
            yield Static("Window:", classes="form-label")
            yield Select(
                [("7 days", "7"), ("30 days", "30"), ("90 days", "90")],
                value="30",
                id="cost-days",
                allow_blank=False,
                classes="cost-window",
            )
            yield Button("Re-fetch", id="cost-refetch")

        with Horizontal(id="cost-main"):
            with Vertical(id="cost-views-pane", classes="panel"):
                yield Static("Views", classes="panel-title")
                yield ListView(
                    ListItem(Label("Summary"),       id="cv-summary"),
                    ListItem(Label("Trend"),         id="cv-trend"),
                    ListItem(Label("Top queries"),   id="cv-top_queries"),
                    ListItem(Label("Warehouses"),    id="cv-warehouses"),
                    ListItem(Label("Users"),         id="cv-users"),
                    ListItem(Label("AI services"),   id="cv-ai"),
                    ListItem(Label("AI by user"),    id="cv-ai_users"),
                    ListItem(Label("Services"),      id="cv-services"),
                    ListItem(Label("Storage"),       id="cv-storage"),
                    ListItem(Label("Replication"),   id="cv-replication"),
                    ListItem(Label("Materialized"),  id="cv-mv"),
                    ListItem(Label("Budget"),        id="cv-budget"),
                    id="cost-views-list",
                )
            with Vertical(id="cost-content", classes="panel"):
                yield Static("Choose a view to begin.", id="cost-status", classes="panel-title")
                yield DataTable(id="cost-table", cursor_type="row", zebra_stripes=True)

    # --- Lifecycle ----------------------------------------------------

    def on_mount(self) -> None:
        # No auto-fetch — every Snowflake call is a deliberate action. Pick a view.
        self._set_status("Pick a view from the list — Snowflake calls are explicit.")

    # --- Navigation ---------------------------------------------------

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.item is None or event.item.id is None:
            return
        item_id = event.item.id
        self._user_initiated = True
        dispatch = {
            "cv-summary":     self._fetch_summary,
            "cv-trend":       self._fetch_trend,
            "cv-top_queries": self._fetch_top_queries,
            "cv-warehouses":  self._fetch_warehouses,
            "cv-users":       self._fetch_users,
            "cv-ai":          self._fetch_ai,
            "cv-ai_users":    self._fetch_ai_users,
            "cv-services":    self._fetch_services,
            "cv-storage":     self._fetch_storage,
            "cv-replication": self._fetch_replication,
            "cv-mv":          self._fetch_mv,
            "cv-budget":      self._fetch_budget,
        }
        handler = dispatch.get(item_id)
        if handler:
            handler()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cost-refetch":
            self.action_refetch()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "cost-days" and self._user_initiated:
            # Window changed → re-fetch the current view with the new window.
            self.action_refetch()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        key = self._row_key_value(event)
        if not key:
            return
        if self._current_view == "summary":
            self._drill_service = key
            self._fetch_service_drill(key)
        elif self._current_view == "warehouses":
            self._drill_warehouse = key
            self._fetch_warehouse_drill(key)
        elif self._current_view == "users":
            self._drill_user = key
            self._fetch_user_drill(key)
        elif self._current_view == "trend":
            self._drill_day = key
            self._fetch_day_drill(key)
        elif self._current_view == "drill_day":
            self._drill_day_service_type = key
            self._fetch_day_resource_drill(self._drill_day, key)
        elif self._current_view == "drill_day_resource":
            upper = (self._drill_day_service_type or "").upper()
            can_drill = (
                upper == _WAREHOUSE_SERVICE_TYPE
                or any(kw in upper for kw in _AI_SERVICE_KEYWORDS)
            )
            if can_drill:
                self._fetch_day_resource_users(
                    self._drill_day, self._drill_day_service_type, key
                )
            else:
                self.app.notify(
                    "No user-level detail available for this resource type.", timeout=3
                )
        elif self._current_view == "drill_day_resource_users":
            if (self._drill_day_service_type or "").upper() == _WAREHOUSE_SERVICE_TYPE:
                self._fetch_day_user_queries(self._drill_day, self._drill_day_resource, key)
            else:
                self.app.notify("No query detail available for AI services.", timeout=3)
        elif self._current_view == "drill_day_user_queries":
            try:
                from textual.widgets import ContentSwitcher, Input
                from snowglobe.tui.screens.tune import TuneScreen
                self.app.query_one(ContentSwitcher).current = "tune"
                tune = self.app.query_one(TuneScreen)
                tune.query_one("#tu-query-id", Input).value = key
                self.app.notify(f"Loaded {key[:24]}… into Tune. Press Analyse.", timeout=4)
            except Exception:
                self.app.notify(f"Query: {key[:24]}…", timeout=4)
        elif self._current_view == "top_queries":
            # Hand off to Tune via the App's content switcher.
            try:
                from textual.widgets import ContentSwitcher, Input
                from snowglobe.tui.screens.tune import TuneScreen
                switcher = self.app.query_one(ContentSwitcher)
                switcher.current = "tune"
                tune = self.app.query_one(TuneScreen)
                tune.query_one("#tu-query-id", Input).value = key
                self.app.notify(f"Loaded {key[:24]}… into Tune. Press Analyse.", timeout=4)
            except Exception:
                self.app.notify(f"Tune screen unavailable. Query: {key[:24]}…", timeout=4)

    def _row_key_value(self, event: DataTable.RowSelected) -> str | None:
        """Recover the value stored as a row's key (set when we added the row)."""
        return event.row_key.value if event.row_key else None

    # --- Actions ------------------------------------------------------

    def action_refetch(self) -> None:
        refetch = {
            "summary":        lambda: self._fetch_summary(force=True),
            "trend":          lambda: self._fetch_trend(force=True),
            "top_queries":    lambda: self._fetch_top_queries(force=True),
            "warehouses":     lambda: self._fetch_warehouses(force=True),
            "users":          lambda: self._fetch_users(force=True),
            "ai":             lambda: self._fetch_ai(force=True),
            "ai_users":       lambda: self._fetch_ai_users(force=True),
            "services":       lambda: self._fetch_services(force=True),
            "storage":        lambda: self._fetch_storage(force=True),
            "replication":    lambda: self._fetch_replication(force=True),
            "mv":             lambda: self._fetch_mv(force=True),
            "budget":         lambda: self._fetch_budget(),  # no refresh param
        }
        h = refetch.get(self._current_view)
        if h:
            h()
        elif self._current_view == "drill_service" and self._drill_service:
            self._fetch_service_drill(self._drill_service, force=True)
        elif self._current_view == "drill_warehouse" and self._drill_warehouse:
            self._fetch_warehouse_drill(self._drill_warehouse)
        elif self._current_view == "drill_user" and self._drill_user:
            self._fetch_user_drill(self._drill_user)
        elif self._current_view == "drill_day" and self._drill_day:
            self._fetch_day_drill(self._drill_day)
        elif self._current_view == "drill_day_resource" and self._drill_day and self._drill_day_service_type:
            self._fetch_day_resource_drill(self._drill_day, self._drill_day_service_type)
        elif (self._current_view == "drill_day_resource_users"
              and self._drill_day and self._drill_day_service_type and self._drill_day_resource):
            self._fetch_day_resource_users(
                self._drill_day, self._drill_day_service_type, self._drill_day_resource
            )
        elif (self._current_view == "drill_day_user_queries"
              and self._drill_day and self._drill_day_resource and self._drill_day_user):
            self._fetch_day_user_queries(
                self._drill_day, self._drill_day_resource, self._drill_day_user
            )

    def action_back_from_drill(self) -> None:
        if self._current_view == "drill_service":
            self._drill_service = None
            self._fetch_summary()
        elif self._current_view == "drill_warehouse":
            self._drill_warehouse = None
            self._fetch_warehouses()
        elif self._current_view == "drill_user":
            self._drill_user = None
            self._fetch_users()
        elif self._current_view == "drill_day":
            self._drill_day = None
            self._drill_day_service_type = None
            self._fetch_trend()
        elif self._current_view == "drill_day_resource":
            self._drill_day_service_type = None
            self._fetch_day_drill(self._drill_day)
        elif self._current_view == "drill_day_resource_users":
            self._drill_day_resource = None
            self._fetch_day_resource_drill(self._drill_day, self._drill_day_service_type)
        elif self._current_view == "drill_day_user_queries":
            self._drill_day_user = None
            self._fetch_day_resource_users(
                self._drill_day, self._drill_day_service_type, self._drill_day_resource
            )

    # --- Days helper --------------------------------------------------

    def _days(self) -> int:
        return int(self.query_one("#cost-days", Select).value)

    # --- View 1: Summary ---------------------------------------------

    def _fetch_summary(self, force: bool = False) -> None:
        self._current_view = "summary"
        self._set_status(f"Loading account summary ({self._days()}d)…")
        self._summary_worker(days=self._days(), force=force)

    @work(thread=True, exclusive=True, group="cost")
    def _summary_worker(self, *, days: int, force: bool) -> None:
        try:
            df, cache_age = self.app.get_cost_service().get_account_summary(days, refresh=force)
        except Exception as e:
            self.app.call_from_thread(self._fetch_failed, e)
            return
        self.app.call_from_thread(self._render_summary, df, days, cache_age)

    def _render_summary(self, df: pd.DataFrame, days: int, cache_age: int | None) -> None:
        if df is None or df.empty:
            self._set_status("No cost data found.")
            self._clear_table()
            return

        total = float(df["CREDITS"].sum())
        suffix = f"  ·  cached {cache_age}m ago" if cache_age else ""
        self._set_status(
            f"Account summary — {days}d  ·  total {total:,.2f} credits{suffix}"
        )

        table = self.query_one(DataTable)
        self._reset_table()
        table.add_columns("SERVICE TYPE", "CREDITS", "PCT", "TREND")

        df_sorted = df.sort_values("CREDITS", ascending=False)
        max_pct = float(df_sorted["PCT"].max()) if "PCT" in df_sorted.columns else 0
        for _, row in df_sorted.iterrows():
            credits = float(row["CREDITS"])
            pct = float(row.get("PCT", 0))
            ratio = (pct / max_pct) if max_pct > 0 else 0
            table.add_row(
                row["SERVICE_TYPE"],
                f"{credits:,.2f}",
                f"{pct:.1f}%",
                _bar(ratio),
                key=row["SERVICE_TYPE"],
            )

    # --- View 2: Trend ------------------------------------------------

    def _fetch_trend(self, force: bool = False) -> None:
        self._current_view = "trend"
        self._set_status(f"Loading daily trend ({self._days()}d)…")
        self._trend_worker(days=self._days(), force=force)

    @work(thread=True, exclusive=True, group="cost")
    def _trend_worker(self, *, days: int, force: bool) -> None:
        try:
            df, cache_age = self.app.get_cost_service().get_daily_trend(days, refresh=force)
        except Exception as e:
            self.app.call_from_thread(self._fetch_failed, e)
            return
        self.app.call_from_thread(self._render_trend, df, days, cache_age)

    def _render_trend(self, df: pd.DataFrame, days: int, cache_age: int | None) -> None:
        if df is None or df.empty:
            self._set_status("No trend data found.")
            self._clear_table()
            return

        total = float(df["CREDITS"].sum())
        avg = float(df["CREDITS"].mean())
        suffix = f"  ·  cached {cache_age}m ago" if cache_age else ""
        self._set_status(
            f"Daily trend — {days}d  ·  total {total:,.2f}  ·  avg/day {avg:,.2f}{suffix}  ·  click a date to drill in"
        )

        table = self.query_one(DataTable)
        self._reset_table()
        table.add_columns("DATE", "CREDITS", "Δ %", "7D AVG", "TREND")

        max_c = float(df["CREDITS"].max()) if not df.empty else 1.0
        for _, row in df.iterrows():
            credits = float(row["CREDITS"])
            ratio = credits / max_c if max_c > 0 else 0
            delta_str = (
                f"{row['DELTA_PCT']:+.1f}%"
                if "DELTA_PCT" in row and pd.notna(row["DELTA_PCT"])
                else "—"
            )
            avg_str = (
                f"{row['ROLLING_7D_AVG']:,.2f}"
                if "ROLLING_7D_AVG" in row and pd.notna(row["ROLLING_7D_AVG"])
                else "—"
            )
            table.add_row(
                str(row["DATE"]),
                f"{credits:,.2f}",
                delta_str,
                avg_str,
                _bar(ratio),
                key=str(row["DATE"]),
            )

    # --- View 3: Top queries -----------------------------------------

    def _fetch_top_queries(self, force: bool = False) -> None:
        self._current_view = "top_queries"
        self._set_status(f"Loading top expensive queries ({self._days()}d)…")
        self._top_queries_worker(days=self._days())

    @work(thread=True, exclusive=True, group="cost")
    def _top_queries_worker(self, *, days: int) -> None:
        try:
            df, _, note = self.app.get_cost_service().get_top_queries(days=days, limit=20)
        except Exception as e:
            self.app.call_from_thread(self._fetch_failed, e)
            return
        self.app.call_from_thread(self._render_top_queries, df, days, note)

    def _render_top_queries(self, df: pd.DataFrame, days: int, note: str | None) -> None:
        if df is None or df.empty:
            self._set_status("No query data found.")
            self._clear_table()
            return

        note_suffix = f"  ·  ⚠ {note}" if note else ""
        self._set_status(
            f"Top expensive queries — {days}d  ·  {len(df)} rows{note_suffix}  ·  ⏎ to open in Tune"
        )

        table = self.query_one(DataTable)
        self._reset_table()
        table.add_columns("CREDITS", "USER", "WAREHOUSE", "TYPE", "SECONDS", "GB", "PREVIEW")

        for _, row in df.iterrows():
            preview = str(row.get("QUERY_PREVIEW", ""))[:48]
            table.add_row(
                f"{float(row.get('CREDITS', 0)):.4f}",
                str(row.get("USER_NAME", "")),
                str(row.get("WAREHOUSE_NAME", "")),
                str(row.get("QUERY_TYPE", "")),
                f"{float(row.get('SECONDS', 0)):.1f}",
                f"{float(row.get('GB_SCANNED', 0)):.2f}",
                preview,
                key=str(row.get("QUERY_ID", "")),
            )

    # --- Drill: per-service daily trend ------------------------------

    def _fetch_service_drill(self, service_type: str, force: bool = False) -> None:
        self._current_view = "drill_service"
        self._set_status(f"Loading daily trend for {service_type} ({self._days()}d)…  Esc to return")
        self._drill_worker(service_type=service_type, days=self._days())

    @work(thread=True, exclusive=True, group="cost")
    def _drill_worker(self, *, service_type: str, days: int) -> None:
        try:
            df = self.app.get_cost_service().get_service_daily_trend(service_type, days)
        except Exception as e:
            self.app.call_from_thread(self._fetch_failed, e)
            return
        self.app.call_from_thread(self._render_service_drill, df, service_type, days)

    def _render_service_drill(self, df: pd.DataFrame, service_type: str, days: int) -> None:
        if df is None or df.empty:
            self._set_status(f"No daily data for {service_type} ({days}d). Esc to return.")
            self._clear_table()
            return
        total = float(df["CREDITS"].sum())
        self._set_status(
            f"{service_type} daily trend — {days}d  ·  total {total:,.2f}  ·  Esc to return"
        )

        table = self.query_one(DataTable)
        self._reset_table()
        table.add_columns("DATE", "CREDITS", "TREND")
        max_c = float(df["CREDITS"].max()) if not df.empty else 1.0
        for _, row in df.iterrows():
            credits = float(row["CREDITS"])
            ratio = credits / max_c if max_c > 0 else 0
            table.add_row(str(row["DATE"]), f"{credits:,.2f}", _bar(ratio))

    # --- View 4: Warehouses ------------------------------------------

    def _fetch_warehouses(self, force: bool = False) -> None:
        self._current_view = "warehouses"
        self._set_status(f"Loading warehouse breakdown ({self._days()}d)…")
        self._warehouses_worker(days=self._days(), force=force)

    @work(thread=True, exclusive=True, group="cost")
    def _warehouses_worker(self, *, days: int, force: bool) -> None:
        try:
            df, cache_age = self.app.get_cost_service().get_warehouse_breakdown(days, refresh=force)
        except Exception as e:
            self.app.call_from_thread(self._fetch_failed, e)
            return
        self.app.call_from_thread(self._render_warehouses, df, days, cache_age)

    def _render_warehouses(self, df: pd.DataFrame, days: int, cache_age: int | None) -> None:
        if df is None or df.empty:
            self._set_status("No warehouse data found.")
            self._clear_table()
            return
        total = float(df["TOTAL_CREDITS"].sum())
        suffix = f"  ·  cached {cache_age}m ago" if cache_age else ""
        self._set_status(
            f"Warehouse breakdown — {days}d  ·  total {total:,.2f} credits{suffix}  ·  ⏎ drill"
        )
        table = self.query_one(DataTable)
        self._reset_table()
        table.add_columns("WAREHOUSE", "TOTAL", "COMPUTE", "CLOUD", "AVG/DAY")
        for _, row in df.iterrows():
            table.add_row(
                str(row["WAREHOUSE_NAME"]),
                f"{float(row.get('TOTAL_CREDITS', 0)):,.2f}",
                f"{float(row.get('COMPUTE_CREDITS', 0)):,.2f}",
                f"{float(row.get('CLOUD_CREDITS', 0)):,.2f}",
                f"{float(row.get('AVG_DAILY_CREDITS', 0)):,.2f}",
                key=str(row["WAREHOUSE_NAME"]),
            )

    def _fetch_warehouse_drill(self, warehouse_name: str) -> None:
        self._current_view = "drill_warehouse"
        self._set_status(f"Loading daily trend for {warehouse_name} ({self._days()}d)…  Esc to return")
        self._warehouse_drill_worker(warehouse_name=warehouse_name, days=self._days())

    @work(thread=True, exclusive=True, group="cost")
    def _warehouse_drill_worker(self, *, warehouse_name: str, days: int) -> None:
        try:
            df = self.app.get_cost_service().get_warehouse_daily_trend(warehouse_name, days)
        except Exception as e:
            self.app.call_from_thread(self._fetch_failed, e)
            return
        self.app.call_from_thread(self._render_warehouse_drill, df, warehouse_name, days)

    def _render_warehouse_drill(self, df: pd.DataFrame, warehouse_name: str, days: int) -> None:
        if df is None or df.empty:
            self._set_status(f"No daily data for {warehouse_name} ({days}d).  Esc to return")
            self._clear_table()
            return
        total = float(df["CREDITS"].sum())
        self._set_status(
            f"{warehouse_name} daily — {days}d  ·  total {total:,.2f}  ·  Esc to return"
        )
        table = self.query_one(DataTable)
        self._reset_table()
        table.add_columns("DATE", "CREDITS", "TREND")
        max_c = float(df["CREDITS"].max()) if not df.empty else 1.0
        for _, row in df.iterrows():
            credits = float(row["CREDITS"])
            ratio = credits / max_c if max_c > 0 else 0
            table.add_row(str(row["DATE"]), f"{credits:,.2f}", _bar(ratio))

    # --- View 5: Users -----------------------------------------------

    def _fetch_users(self, force: bool = False) -> None:
        self._current_view = "users"
        self._set_status(f"Loading user breakdown ({min(self._days(), 7)}d)…")
        self._users_worker(days=min(self._days(), 7), force=force)

    @work(thread=True, exclusive=True, group="cost")
    def _users_worker(self, *, days: int, force: bool) -> None:
        try:
            df, cache_age, note = self.app.get_cost_service().get_user_breakdown(days, refresh=force)
        except Exception as e:
            self.app.call_from_thread(self._fetch_failed, e)
            return
        self.app.call_from_thread(self._render_users, df, days, cache_age, note)

    def _render_users(self, df: pd.DataFrame, days: int, cache_age: int | None, note: str | None) -> None:
        if df is None or df.empty:
            self._set_status("No user data found.")
            self._clear_table()
            return
        total = float(df["TOTAL_CREDITS"].sum())
        cache_suffix = f"  ·  cached {cache_age}m ago" if cache_age else ""
        note_suffix = f"  ·  ⚠ {note}" if note else ""
        self._set_status(
            f"User cost attribution — {days}d  ·  top {len(df)}  ·  total {total:,.2f}{cache_suffix}{note_suffix}  ·  ⏎ drill"
        )
        table = self.query_one(DataTable)
        self._reset_table()
        no_credits = note is not None and "Query Attribution" in (note or "")
        table.add_columns("USER", "TOTAL", "WAREHOUSE", "QA", "CORTEX", "QUERIES")
        for _, row in df.iterrows():
            cortex_total = sum(
                float(row.get(c, 0) or 0) for c in (
                    "CORTEX_FUNCTIONS", "CORTEX_ANALYST", "CORTEX_AGENT",
                    "CORTEX_CODE", "SNOWFLAKE_INTELLIGENCE",
                )
            )
            wh_str = "—" if no_credits else f"{float(row.get('WAREHOUSE_CREDITS', 0)):,.2f}"
            qa_str = "—" if no_credits else f"{float(row.get('QA_CREDITS', 0)):,.4f}"
            table.add_row(
                str(row["USER_NAME"]),
                f"{float(row.get('TOTAL_CREDITS', 0)):,.2f}",
                wh_str,
                qa_str,
                f"{cortex_total:,.2f}",
                str(int(row.get("QUERY_COUNT", 0))),
                key=str(row["USER_NAME"]),
            )

    def _fetch_user_drill(self, user_name: str) -> None:
        self._current_view = "drill_user"
        self._set_status(f"Loading warehouse detail for {user_name} ({min(self._days(),7)}d)…  Esc to return")
        self._user_drill_worker(user_name=user_name, days=min(self._days(), 7))

    @work(thread=True, exclusive=True, group="cost")
    def _user_drill_worker(self, *, user_name: str, days: int) -> None:
        try:
            df, note = self.app.get_cost_service().get_user_detail(user_name, days)
        except Exception as e:
            self.app.call_from_thread(self._fetch_failed, e)
            return
        self.app.call_from_thread(self._render_user_drill, df, user_name, days, note)

    def _render_user_drill(self, df: pd.DataFrame, user_name: str, days: int, note: str | None) -> None:
        if df is None or df.empty:
            self._set_status(f"No attribution data for {user_name} ({days}d).  Esc to return")
            self._clear_table()
            return
        total = float(df["CREDITS"].sum())
        note_suffix = f"  ·  ⚠ {note}" if note else ""
        self._set_status(
            f"{user_name} per-warehouse — {days}d  ·  total {total:,.4f}{note_suffix}  ·  Esc to return"
        )
        no_credits = note is not None
        table = self.query_one(DataTable)
        self._reset_table()
        table.add_columns("WAREHOUSE", "CREDITS", "QUERIES", "AVG/QUERY")
        for _, row in df.iterrows():
            credits_str = "—" if no_credits else f"{float(row.get('CREDITS', 0)):,.4f}"
            avg_str = "—" if no_credits else f"{float(row.get('AVG_CREDIT_PER_QUERY', 0)):,.6f}"
            table.add_row(
                str(row.get("WAREHOUSE_NAME", "")),
                credits_str,
                str(int(row.get("QUERY_COUNT", 0))),
                avg_str,
            )

    # --- Drill: day breakdown (Level 1 — service types) --------------

    def _fetch_day_drill(self, date: str) -> None:
        self._current_view = "drill_day"
        self._set_status(f"Loading service breakdown for {date}…  Esc to return")
        self._day_drill_worker(date=date)

    @work(thread=True, exclusive=True, group="cost")
    def _day_drill_worker(self, *, date: str) -> None:
        try:
            df = self.app.get_cost_service().get_day_service_breakdown(date)
        except Exception as e:
            self.app.call_from_thread(self._fetch_failed, e)
            return
        self.app.call_from_thread(self._render_day_drill, df, date)

    def _render_day_drill(self, df: pd.DataFrame, date: str) -> None:
        self._reset_table()
        table = self.query_one(DataTable)
        if df is None or df.empty:
            table.add_columns("(no activity on this date)")
            self._set_status(f"{date}  ·  no data  ·  Esc to return")
            return
        total = float(df["CREDITS"].sum())
        max_c = float(df["CREDITS"].max()) if total > 0 else 1.0
        table.add_columns("SERVICE TYPE", "CREDITS", "% OF DAY", "BAR")
        for _, row in df.iterrows():
            credits = float(row["CREDITS"])
            pct = (credits / total * 100) if total > 0 else 0
            table.add_row(
                str(row["SERVICE_TYPE"]),
                f"{credits:,.4f}",
                f"{pct:.1f}%",
                _bar(credits / max_c),
                key=str(row["SERVICE_TYPE"]),
            )
        self._set_status(
            f"Day breakdown — {date}  ·  {total:,.4f} credits  ·  click a service to drill  ·  Esc to return"
        )

    # --- Drill: resource breakdown (Level 2 — all service types) -----

    def _fetch_day_resource_drill(self, date: str, service_type: str) -> None:
        self._current_view = "drill_day_resource"
        self._drill_day_service_type = service_type
        self._set_status(f"Loading {service_type} breakdown for {date}…  Esc to return")
        upper = service_type.upper()
        is_ai = any(kw in upper for kw in _AI_SERVICE_KEYWORDS)
        self._day_resource_drill_worker(date=date, service_type=service_type, is_ai=is_ai)

    @work(thread=True, exclusive=True, group="cost")
    def _day_resource_drill_worker(self, *, date: str, service_type: str, is_ai: bool) -> None:
        try:
            svc = self.app.get_cost_service()
            if is_ai:
                df, any_missing = svc.get_day_ai_breakdown(date)
                label = "AI Service"
                found = True
                note = "some Cortex views unavailable" if any_missing else None
            else:
                df, label, found = svc.get_day_resource_breakdown(date, service_type)
                note = None
        except Exception as e:
            self.app.call_from_thread(self._fetch_failed, e)
            return
        self.app.call_from_thread(
            self._render_day_resource_drill, df, date, service_type, label, found, note
        )

    def _render_day_resource_drill(self, df: pd.DataFrame, date: str, service_type: str,
                                    label: str, found: bool, note: str | None) -> None:
        self._reset_table()
        table = self.query_one(DataTable)
        note_suffix = f"  ·  ⚠ {note}" if note else ""
        if not found:
            table.add_columns("(no detail available for this service type)")
            self._set_status(
                f"{service_type} — {date}  ·  no resource detail available  ·  Esc to return"
            )
            return
        if df is None or df.empty:
            table.add_columns(f"(no {label.lower()} activity on this date)")
            self._set_status(f"{service_type} — {date}  ·  no data{note_suffix}  ·  Esc to return")
            return
        total = float(df["CREDITS"].sum())
        max_c = float(df["CREDITS"].max()) if total > 0 else 1.0
        has_requests = "REQUEST_COUNT" in df.columns
        if has_requests:
            table.add_columns(label.upper(), "CREDITS", "REQUESTS", "% OF SERVICE", "BAR")
        else:
            table.add_columns(label.upper(), "CREDITS", "% OF SERVICE", "BAR")
        for _, row in df.iterrows():
            credits = float(row["CREDITS"])
            pct = (credits / total * 100) if total > 0 else 0
            cells = [str(row["RESOURCE_NAME"]), f"{credits:,.4f}"]
            if has_requests:
                cells.append(str(int(row.get("REQUEST_COUNT", 0))))
            cells += [f"{pct:.1f}%", _bar(credits / max_c)]
            table.add_row(*cells, key=str(row["RESOURCE_NAME"]))
        upper = service_type.upper()
        can_drill_users = (
            upper == _WAREHOUSE_SERVICE_TYPE
            or any(kw in upper for kw in _AI_SERVICE_KEYWORDS)
        )
        user_hint = "  ·  click to see users" if can_drill_users else ""
        self._set_status(
            f"{service_type} — {date}  ·  {total:,.4f} credits{note_suffix}{user_hint}  ·  Esc to return"
        )

    # --- Drill: user breakdown (Level 3) -----------------------------

    def _fetch_day_resource_users(self, date: str, service_type: str, resource: str) -> None:
        self._current_view = "drill_day_resource_users"
        self._drill_day_resource = resource
        self._set_status(f"Loading users for {resource} on {date}…  Esc to return")
        self._day_resource_users_worker(date=date, service_type=service_type, resource=resource)

    @work(thread=True, exclusive=True, group="cost")
    def _day_resource_users_worker(self, *, date: str, service_type: str, resource: str) -> None:
        try:
            df, note = self.app.get_cost_service().get_day_resource_users(
                date, service_type, resource
            )
        except Exception as e:
            self.app.call_from_thread(self._fetch_failed, e)
            return
        self.app.call_from_thread(self._render_day_resource_users, df, date, resource, note)

    def _render_day_resource_users(self, df: pd.DataFrame, date: str,
                                    resource: str, note: str | None) -> None:
        self._reset_table()
        table = self.query_one(DataTable)
        note_suffix = f"  ·  ⚠ {note}" if note else ""
        if note and "No user-level" in note:
            table.add_columns("(no user-level detail available for this resource type)")
            self._set_status(f"{resource} — {date}{note_suffix}  ·  Esc to return")
            return
        if df is None or df.empty:
            table.add_columns("(no users found)")
            self._set_status(f"{resource} — {date}  ·  no users{note_suffix}  ·  Esc to return")
            return
        total = float(df["CREDITS"].sum())
        max_c = float(df["CREDITS"].max()) if total > 0 else 1.0
        table.add_columns("USER", "CREDITS", "QUERIES", "% OF RESOURCE", "BAR")
        for _, row in df.iterrows():
            credits = float(row["CREDITS"])
            pct = (credits / total * 100) if total > 0 else 0
            table.add_row(
                str(row["USER_NAME"]),
                f"{credits:,.4f}",
                str(int(row.get("REQUESTS", 0))),
                f"{pct:.1f}%",
                _bar(credits / max_c),
                key=str(row["USER_NAME"]),
            )
        query_hint = (
            "  ·  click user to see top queries"
            if (self._drill_day_service_type or "").upper() == _WAREHOUSE_SERVICE_TYPE
            else ""
        )
        self._set_status(
            f"{resource} users — {date}  ·  {total:,.4f} credits{note_suffix}{query_hint}  ·  Esc to return"
        )

    # --- Drill: top queries for a user (Level 4) ----------------------

    def _fetch_day_user_queries(self, date: str, warehouse: str, user: str) -> None:
        self._current_view = "drill_day_user_queries"
        self._drill_day_user = user
        self._set_status(
            f"Loading top queries for {user} on {warehouse} ({date})…  Esc to return"
        )
        self._day_user_queries_worker(date=date, warehouse=warehouse, user=user)

    @work(thread=True, exclusive=True, group="cost")
    def _day_user_queries_worker(self, *, date: str, warehouse: str, user: str) -> None:
        try:
            df, note = self.app.get_cost_service().get_day_user_queries(
                date, warehouse, user, limit=3
            )
        except Exception as e:
            self.app.call_from_thread(self._fetch_failed, e)
            return
        self.app.call_from_thread(self._render_day_user_queries, df, date, warehouse, user, note)

    def _render_day_user_queries(self, df: pd.DataFrame, date: str,
                                  warehouse: str, user: str, note: str | None) -> None:
        self._reset_table()
        table = self.query_one(DataTable)
        note_suffix = f"  ·  ⚠ {note}" if note else ""
        if df is None or df.empty:
            table.add_columns("(no queries found)")
            self._set_status(
                f"{user} on {warehouse} — {date}  ·  no queries{note_suffix}  ·  Esc to return"
            )
            return
        table.add_columns("CREDITS", "TYPE", "SECONDS", "GB", "PREVIEW")
        for _, row in df.iterrows():
            table.add_row(
                f"{float(row.get('CREDITS', 0)):,.4f}",
                str(row.get("QUERY_TYPE", "")),
                f"{float(row.get('SECONDS', 0)):.1f}",
                f"{float(row.get('GB_SCANNED', 0)):.2f}",
                str(row.get("QUERY_PREVIEW", ""))[:48],
                key=str(row.get("QUERY_ID", "")),
            )
        self._set_status(
            f"Top queries — {user} on {warehouse} — {date}{note_suffix}"
            f"  ·  ⏎ open in Tune  ·  Esc to return"
        )

    # --- View 6: AI services -----------------------------------------

    def _fetch_ai(self, force: bool = False) -> None:
        self._current_view = "ai"
        self._set_status(f"Loading AI service costs ({self._days()}d)…")
        self._ai_worker(days=self._days(), force=force)

    @work(thread=True, exclusive=True, group="cost")
    def _ai_worker(self, *, days: int, force: bool) -> None:
        try:
            df, cache_age, note = self.app.get_cost_service().get_ai_costs(days, refresh=force)
        except Exception as e:
            self.app.call_from_thread(self._fetch_failed, e)
            return
        self.app.call_from_thread(self._render_ai, df, days, cache_age, note)

    def _render_ai(self, df: pd.DataFrame, days: int, cache_age: int | None, note: str | None) -> None:
        if df is None or df.empty:
            self._set_status("No AI usage found.")
            self._clear_table()
            return
        total = float(df["TOTAL_CREDITS"].astype(float).sum())
        cache_suffix = f"  ·  cached {cache_age}m ago" if cache_age else ""
        note_suffix = f"  ·  ⚠ {note}" if note else ""
        self._set_status(
            f"AI token costs — {days}d  ·  total {total:,.2f} credits{cache_suffix}{note_suffix}"
        )
        table = self.query_one(DataTable)
        self._reset_table()
        table.add_columns("SERVICE", "CREDITS", "REQUESTS", "PCT", "TREND")
        max_pct = float(df["PCT"].max()) if "PCT" in df.columns and not df.empty else 0
        for _, row in df.iterrows():
            pct = float(row.get("PCT", 0))
            ratio = pct / max_pct if max_pct > 0 else 0
            table.add_row(
                str(row["SERVICE"]),
                f"{float(row.get('TOTAL_CREDITS', 0)):,.2f}",
                str(int(row.get("REQUEST_COUNT", 0))),
                f"{pct:.1f}%",
                _bar(ratio),
                key=str(row["SERVICE"]),
            )

    # --- View 7: AI by user ------------------------------------------

    def _fetch_ai_users(self, force: bool = False) -> None:
        self._current_view = "ai_users"
        self._set_status(f"Loading AI costs by user ({self._days()}d)…")
        self._ai_users_worker(days=self._days(), force=force)

    @work(thread=True, exclusive=True, group="cost")
    def _ai_users_worker(self, *, days: int, force: bool) -> None:
        try:
            df, cache_age, note = self.app.get_cost_service().get_ai_costs_by_user(days, refresh=force)
        except Exception as e:
            self.app.call_from_thread(self._fetch_failed, e)
            return
        self.app.call_from_thread(self._render_ai_users, df, days, cache_age, note)

    def _render_ai_users(self, df: pd.DataFrame, days: int, cache_age: int | None, note: str | None) -> None:
        if df is None or df.empty:
            self._set_status("No AI usage by user.")
            self._clear_table()
            return
        total = float(df["TOTAL_CREDITS"].astype(float).sum())
        cache_suffix = f"  ·  cached {cache_age}m ago" if cache_age else ""
        note_suffix = f"  ·  ⚠ {note}" if note else ""
        self._set_status(
            f"AI token costs by user — {days}d  ·  top {len(df)}  ·  total {total:,.2f}{cache_suffix}{note_suffix}"
        )
        table = self.query_one(DataTable)
        self._reset_table()
        table.add_columns("USER", "TOTAL", "FUNCTIONS", "ANALYST", "AGENT", "CODE", "INTELLIGENCE")
        for _, row in df.iterrows():
            def _f(col):
                v = row.get(col, 0)
                return f"{float(v or 0):,.2f}"
            table.add_row(
                str(row["USER_NAME"]),
                _f("TOTAL_CREDITS"),
                _f("CORTEX_FUNCTIONS"),
                _f("CORTEX_ANALYST"),
                _f("CORTEX_AGENT"),
                _f("CORTEX_CODE"),
                _f("SNOWFLAKE_INTELLIGENCE"),
                key=str(row["USER_NAME"]),
            )

    # --- View 8: Services (pipes, tasks, SPCS, ...) ------------------

    def _fetch_services(self, force: bool = False) -> None:
        self._current_view = "services"
        self._set_status(f"Loading service resource costs ({self._days()}d)…")
        self._services_worker(days=self._days(), force=force)

    @work(thread=True, exclusive=True, group="cost")
    def _services_worker(self, *, days: int, force: bool) -> None:
        try:
            df, cache_age = self.app.get_cost_service().get_service_breakdown(days, refresh=force)
        except Exception as e:
            self.app.call_from_thread(self._fetch_failed, e)
            return
        self.app.call_from_thread(self._render_services, df, days, cache_age)

    def _render_services(self, df: pd.DataFrame, days: int, cache_age: int | None) -> None:
        if df is None or df.empty:
            self._set_status("No non-warehouse service costs.")
            self._clear_table()
            return
        total = float(df["credits"].astype(float).sum())
        suffix = f"  ·  cached {cache_age}m ago" if cache_age else ""
        self._set_status(
            f"Services — {days}d  ·  total {total:,.2f} credits{suffix}"
        )
        table = self.query_one(DataTable)
        self._reset_table()
        table.add_columns("SERVICE", "RESOURCE", "CREDITS")
        for _, row in df.iterrows():
            table.add_row(
                str(row["service"]),
                str(row["resource_name"]),
                f"{float(row['credits']):,.2f}",
            )

    # --- View 9: Storage ---------------------------------------------

    def _fetch_storage(self, force: bool = False) -> None:
        self._current_view = "storage"
        self._set_status(f"Loading storage usage ({self._days()}d avg)…")
        self._storage_worker(days=self._days(), force=force)

    @work(thread=True, exclusive=True, group="cost")
    def _storage_worker(self, *, days: int, force: bool) -> None:
        try:
            df, cache_age = self.app.get_cost_service().get_storage_usage(days, refresh=force)
            rate = self.app.get_cost_service().get_storage_rate()
        except Exception as e:
            self.app.call_from_thread(self._fetch_failed, e)
            return
        self.app.call_from_thread(self._render_storage, df, days, cache_age, rate)

    def _render_storage(self, df: pd.DataFrame, days: int, cache_age: int | None,
                        rate: float) -> None:
        if df is None or df.empty:
            self._set_status("No storage data found.")
            self._clear_table()
            return
        df = df[df["TOTAL_TB"] > 0] if "TOTAL_TB" in df.columns else df
        if df.empty:
            self._set_status("No storage data found.")
            self._clear_table()
            return
        total_tb = float(df["TOTAL_TB"].sum())
        total_cost = float(df["EST_MONTHLY_COST"].sum())
        rate_src = "contracted" if rate != 23.0 else "$23/TB default"
        suffix = f"  ·  cached {cache_age}m ago" if cache_age else ""
        self._set_status(
            f"Storage — {days}d avg  ·  {total_tb:,.2f} TB  ·  est. ${total_cost:,.2f}/mo "
            f"(${rate:.2f}/TB · {rate_src}){suffix}"
        )
        table = self.query_one(DataTable)
        self._reset_table()
        table.add_columns("DATABASE", "TOTAL TB", "ACTIVE TB", "FAILSAFE TB", "EST $/MO")
        for _, row in df.sort_values("TOTAL_TB", ascending=False).iterrows():
            table.add_row(
                str(row["DATABASE_NAME"]),
                f"{float(row.get('TOTAL_TB', 0)):,.4f}",
                f"{float(row.get('ACTIVE_BYTES', 0)) / 1e12:,.4f}",
                f"{float(row.get('FAILSAFE_BYTES', 0)) / 1e12:,.4f}",
                f"${float(row.get('EST_MONTHLY_COST', 0)):,.2f}",
                key=str(row["DATABASE_NAME"]),
            )

    # --- View 10: Replication ----------------------------------------

    def _fetch_replication(self, force: bool = False) -> None:
        self._current_view = "replication"
        self._set_status(f"Loading replication costs ({self._days()}d)…")
        self._replication_worker(days=self._days(), force=force)

    @work(thread=True, exclusive=True, group="cost")
    def _replication_worker(self, *, days: int, force: bool) -> None:
        try:
            df, cache_age = self.app.get_cost_service().get_replication_costs(days, refresh=force)
        except Exception as e:
            self.app.call_from_thread(self._fetch_failed, e)
            return
        self.app.call_from_thread(self._render_replication, df, days, cache_age)

    def _render_replication(self, df: pd.DataFrame, days: int, cache_age: int | None) -> None:
        if df is None or df.empty:
            self._set_status("No replication costs.")
            self._clear_table()
            return
        suffix = f"  ·  cached {cache_age}m ago" if cache_age else ""
        total = float(df["CREDITS"].astype(float).sum()) if "CREDITS" in df.columns else 0
        self._set_status(
            f"Replication — {days}d  ·  total {total:,.2f} credits{suffix}"
        )
        table = self.query_one(DataTable)
        self._reset_table()
        # Two possible shapes — REPLICATION_GROUP_USAGE_HISTORY view or fallback by DATE
        cols = list(df.columns)
        table.add_columns(*[c.upper() for c in cols])
        for _, row in df.iterrows():
            table.add_row(*[str(row.get(c, "")) for c in cols])

    # --- View 11: Materialized view refresh costs --------------------

    def _fetch_mv(self, force: bool = False) -> None:
        self._current_view = "mv"
        self._set_status(f"Loading materialized view refresh costs ({self._days()}d)…")
        self._mv_worker(days=self._days(), force=force)

    @work(thread=True, exclusive=True, group="cost")
    def _mv_worker(self, *, days: int, force: bool) -> None:
        try:
            df, cache_age = self.app.get_cost_service().get_materialized_view_costs(days, refresh=force)
        except Exception as e:
            self.app.call_from_thread(self._fetch_failed, e)
            return
        self.app.call_from_thread(self._render_mv, df, days, cache_age)

    def _render_mv(self, df: pd.DataFrame, days: int, cache_age: int | None) -> None:
        if df is None or df.empty:
            self._set_status("No materialized-view refresh costs (no MVs or no recent refreshes).")
            self._clear_table()
            return
        total = float(df["CREDITS"].astype(float).sum()) if "CREDITS" in df.columns else 0
        suffix = f"  ·  cached {cache_age}m ago" if cache_age else ""
        self._set_status(
            f"Materialized views — {days}d  ·  total {total:,.2f} refresh credits{suffix}"
        )
        table = self.query_one(DataTable)
        self._reset_table()
        table.add_columns("MV", "CREDITS", "REFRESHES")
        for _, row in df.iterrows():
            table.add_row(
                str(row.get("MV_NAME", "")),
                f"{float(row.get('CREDITS', 0)):,.2f}",
                str(int(row.get("REFRESH_COUNT", 0))),
            )

    # --- View 12: Budget ---------------------------------------------

    def _fetch_budget(self) -> None:
        self._current_view = "budget"
        self._set_status("Loading Snowflake-native budget status…")
        self._budget_worker()

    @work(thread=True, exclusive=True, group="cost")
    def _budget_worker(self) -> None:
        try:
            df, error = self.app.get_cost_service().get_budget_status()
        except Exception as e:
            self.app.call_from_thread(self._fetch_failed, e)
            return
        self.app.call_from_thread(self._render_budget, df, error)

    def _render_budget(self, df: pd.DataFrame, error: str | None) -> None:
        if error:
            self._set_status(error)
            self._clear_table()
            return
        if df is None or df.empty:
            self._set_status("No budget spending history.")
            self._clear_table()
            return
        self._set_status(f"Budget spending history — {len(df)} entries")
        table = self.query_one(DataTable)
        self._reset_table()
        cols = list(df.columns)
        table.add_columns(*[c.upper() for c in cols])
        for _, row in df.iterrows():
            table.add_row(*[str(row.get(c, "")) for c in cols])

    # --- Helpers ------------------------------------------------------

    def _set_status(self, text: str) -> None:
        self.query_one("#cost-status", Static).update(text)

    def _clear_table(self) -> None:
        table = self.query_one(DataTable)
        table.clear(columns=True)

    def _reset_table(self) -> None:
        # Recreate columns so previous view's schema doesn't leak.
        table = self.query_one(DataTable)
        table.clear(columns=True)

    def _fetch_failed(self, err: Exception) -> None:
        self._set_status(f"Fetch failed: {err}")
        self.app.notify(f"Cost fetch failed: {err}", severity="error", timeout=8)
