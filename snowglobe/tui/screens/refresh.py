"""Refresh & status screen.

Stats grid (top-left), action buttons (top-right), streaming log (bottom).
Refreshes run in a thread worker, piping progress into the RichLog via
CallableRefreshProgress. Esc cancels any running worker in the "snowflake"
worker group.
"""
import os
from datetime import datetime, timezone

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, RichLog, Static


_LEVEL_STYLE: dict[str, str] = {
    "header":  "bold cyan",
    "step":    "cyan",
    "start":   "cyan",
    "ok":      "green",
    "fail":    "bold red",
    "info":    "dim",
    "warning": "yellow",
    "done":    "bold green",
}


def _format_log_line(level: str, msg: str) -> str:
    """Format a (level, msg) tuple for RichLog with Rich markup."""
    ts = datetime.now().strftime("%H:%M:%S")
    style = _LEVEL_STYLE.get(level, "")
    if style:
        return f"[dim]{ts}[/dim]  [{style}]{msg}[/{style}]"
    return f"[dim]{ts}[/dim]  {msg}"


class RefreshScreen(Vertical):
    """State management + connection diagnostics."""

    BINDINGS = [
        ("escape", "cancel_running", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        yield Static("Refresh & Status", classes="screen-title")

        with Horizontal(id="refresh-top"):
            with Vertical(id="refresh-stats", classes="panel"):
                yield Static("State", classes="panel-title")
                yield Static(id="stats-text", classes="stats-text")
            with Vertical(id="refresh-actions", classes="panel"):
                yield Static("Actions", classes="panel-title")
                yield Button("Incremental refresh", id="btn-incremental", variant="primary")
                yield Button("Full refresh",        id="btn-full",        variant="warning")
                yield Button("Connection check",    id="btn-debug")

        yield RichLog(id="refresh-log", wrap=True, highlight=False, markup=True, max_lines=500)

    # --- Lifecycle ----------------------------------------------------

    def on_mount(self) -> None:
        self._render_stats()
        # Refresh stats whenever cache age changes (e.g. after a refresh worker finishes).
        self.watch(self.app, "cache_age_minutes", lambda _v: self._render_stats())

    # --- Stats panel --------------------------------------------------

    def _render_stats(self) -> None:
        rows = self._gather_stats()
        text = "\n".join(f"  {label:<18}{value:>12}" for label, value in rows)
        self.query_one("#stats-text", Static).update(text)

    def _gather_stats(self) -> list[tuple[str, str]]:
        from snowglobe.state.db import StateDB
        db = StateDB()

        def count(table: str) -> str:
            try:
                row = db.conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
                return f"{row['n']:,}"
            except Exception:
                return "—"

        rows: list[tuple[str, str]] = [
            ("grants",           count("grants")),
            ("role edges",       count("role_edges")),
            ("user assignments", count("user_roles")),
            ("extra objects",    count("extra_objects")),
        ]

        refreshed_at = db.get_refreshed_at()
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
                rows.append(("last refreshed", age_str))
            except (ValueError, TypeError):
                rows.append(("last refreshed", "unknown"))
        else:
            rows.append(("last refreshed", "never"))

        try:
            size_mb = os.path.getsize(db.db_path) / (1024 * 1024)
            rows.append(("db size", f"{size_mb:.1f} MB"))
        except Exception:
            pass

        return rows

    # --- Buttons ------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-incremental":
            self._start_refresh(full=False)
        elif event.button.id == "btn-full":
            self._start_refresh(full=True)
        elif event.button.id == "btn-debug":
            self._start_diagnostics()

    def _set_busy(self, busy: bool) -> None:
        for bid in ("btn-incremental", "btn-full", "btn-debug"):
            try:
                self.query_one(f"#{bid}", Button).disabled = busy
            except Exception:
                pass

    def _log(self, level: str, msg: str) -> None:
        """Write one formatted line to the RichLog (call from main thread only)."""
        self.query_one("#refresh-log", RichLog).write(_format_log_line(level, msg))

    # --- Refresh worker ----------------------------------------------

    def _start_refresh(self, *, full: bool) -> None:
        if self.app.access_service is None:
            self.app.notify("State not yet loaded — wait a moment.", severity="warning")
            return
        self._set_busy(True)
        self._log("header", "Full refresh" if full else "Incremental refresh")
        self._refresh_worker(full=full)

    @work(thread=True, exclusive=True, group="snowflake")
    def _refresh_worker(self, *, full: bool) -> None:
        from snowglobe.core.access_service import CallableRefreshProgress

        progress = CallableRefreshProgress(
            lambda level, msg: self.app.call_from_thread(self._log, level, msg)
        )
        try:
            self.app.access_service.refresh_state(full=full, progress=progress)
        except Exception as e:
            self.app.call_from_thread(self._log, "fail", f"Refresh failed: {e}")
            self.app.call_from_thread(self._set_busy, False)
            return

        self.app.call_from_thread(self._on_refresh_complete)

    def _on_refresh_complete(self) -> None:
        svc = self.app.access_service
        # Re-bind app-level reactives so other screens (suggesters etc.) re-read.
        self.app.user_graph = svc.user_graph
        self.app.role_graph = svc.role_graph
        self.app.object_index = svc.object_index
        self.app._refresh_cache_age()
        self._render_stats()
        self._set_busy(False)
        self._log("done", "Refresh complete.")
        self.app.notify("Refresh complete.", timeout=3)

    # --- Diagnostics worker ------------------------------------------

    def _start_diagnostics(self) -> None:
        self._set_busy(True)
        self._log("header", "Connection diagnostics")
        self._diagnostics_worker()

    @work(thread=True, exclusive=True, group="snowflake")
    def _diagnostics_worker(self) -> None:
        from snowglobe.cli.debug import run_diagnostics, CallableReporter

        reporter = CallableReporter(
            lambda level, msg: self.app.call_from_thread(self._log, level, msg)
        )
        try:
            ok = run_diagnostics(
                profile_name=self.app.context.profile_name,
                verbose=self.app.context.verbose,
                reporter=reporter,
            )
        except Exception as e:
            self.app.call_from_thread(self._log, "fail", f"Diagnostics failed: {e}")
            self.app.call_from_thread(self._set_busy, False)
            return

        self.app.call_from_thread(self._set_busy, False)
        if ok:
            self.app.call_from_thread(self.app.notify, "Connection OK.", timeout=3)
        else:
            self.app.call_from_thread(
                self.app.notify, "Diagnostics failed — see log.", severity="error", timeout=5
            )

    # --- Cancel -------------------------------------------------------

    def action_cancel_running(self) -> None:
        """Cancel any in-flight Snowflake-bound worker."""
        cancelled = 0
        for worker in self.app.workers:
            if getattr(worker, "group", None) == "snowflake":
                worker.cancel()
                cancelled += 1
        if cancelled:
            self._log("warning", "Cancelled by user.")
            self._set_busy(False)
            self.app.notify("Cancelled.", severity="warning", timeout=3)
