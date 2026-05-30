"""Reports screen — generate markdown reports via ReportService.

Three report types:
  - Full         — ReportService.generate_full_report (cost + AI + storage + top queries)
  - Cost-only    — same data, with top_queries cleared
  - User access  — AccessService.inspect_user_report(username) rendered inline

Generation runs in a worker (touches Snowflake). The Markdown widget
previews the result; the Save button writes it to the chosen path.
"""
from datetime import date
from pathlib import Path
from typing import Any

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.suggester import SuggestFromList
from textual.widgets import Button, Input, Markdown, Select, Static


_TYPES = [
    ("Full report (cost + AI + storage + top queries)", "full"),
    ("Cost-only report",                                  "cost"),
    ("User access report",                                "user"),
]


def _default_path(report_type: str) -> str:
    today = date.today().isoformat()
    prefix = {
        "full": "snowglobe_report",
        "cost": "snowglobe_cost",
        "user": "snowglobe_user_access",
    }.get(report_type, "snowglobe_report")
    return f"./{prefix}_{today}.md"


class ReportsScreen(Vertical):
    """Generate + preview + save markdown reports."""

    _last_markdown: str | None = None

    def compose(self) -> ComposeResult:
        yield Static("Reports", classes="screen-title")

        with Vertical(id="rp-form"):
            with Horizontal(classes="form-row"):
                yield Static("Report type:", classes="form-label")
                yield Select(_TYPES, value="full", id="rp-type",
                             classes="form-select", allow_blank=False)

            with Horizontal(classes="form-row", id="rp-days-row"):
                yield Static("Window:", classes="form-label")
                yield Input(value="30", id="rp-days", classes="form-input")

            with Horizontal(classes="form-row", id="rp-top-row"):
                yield Static("Top queries:", classes="form-label")
                yield Input(value="10", id="rp-top", classes="form-input")

            with Horizontal(classes="form-row", id="rp-user-row"):
                yield Static("Username:", classes="form-label")
                yield Input(placeholder="only used for the user-access report",
                            id="rp-user", classes="form-input")

            with Horizontal(classes="form-row"):
                yield Static("Output path:", classes="form-label")
                yield Input(value=_default_path("full"),
                            id="rp-path", classes="form-input")

            with Horizontal(classes="actions-row"):
                yield Button("Generate", id="rp-generate", variant="primary")
                yield Button("Save",     id="rp-save",     variant="warning", disabled=True)

        yield Static(
            "Preview will appear here after Generate. Save writes to the output path.",
            id="rp-status", classes="hint",
        )
        with VerticalScroll(id="rp-preview-scroll"):
            yield Markdown(
                "No report yet — fill the form and click Generate.",
                id="rp-preview",
            )

    # --- Lifecycle ----------------------------------------------------

    def on_mount(self) -> None:
        self._update_form_visibility("full")
        self.watch(self.app, "user_graph",
                   lambda _v: self._refresh_user_suggester())

    def _refresh_user_suggester(self) -> None:
        if not self.is_mounted or self.app.user_graph is None:
            return
        try:
            users = sorted(self.app.user_graph.assigned_roles.keys())
            self.query_one("#rp-user", Input).suggester = SuggestFromList(
                users, case_sensitive=False
            )
        except Exception:
            pass

    # --- Events -------------------------------------------------------

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "rp-type":
            rtype = str(event.value)
            self.query_one("#rp-path", Input).value = _default_path(rtype)
            self._update_form_visibility(rtype)

    def _update_form_visibility(self, rtype: str) -> None:
        is_user = rtype == "user"
        is_full = rtype == "full"
        self.query_one("#rp-days-row").display = not is_user
        self.query_one("#rp-top-row").display = is_full
        self.query_one("#rp-user-row").display = is_user

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "rp-generate":
            self._start_generate()
        elif event.button.id == "rp-save":
            self._save()

    # --- Generate -----------------------------------------------------

    def _start_generate(self) -> None:
        rtype = self.query_one("#rp-type", Select).value
        try:
            days = int(self.query_one("#rp-days", Input).value or "30")
            top_n = int(self.query_one("#rp-top", Input).value or "10")
        except ValueError:
            self.app.notify("Days and Top queries must be integers.", severity="warning")
            return

        if rtype == "user":
            username = self.query_one("#rp-user", Input).value.strip()
            if not username:
                self.app.notify("Username required for user-access reports.", severity="warning")
                return
            self.query_one("#rp-status", Static).update(
                f"Generating user-access report for {username}…"
            )
            self.query_one("#rp-generate", Button).disabled = True
            self.query_one("#rp-save", Button).disabled = True
            self._user_worker(username=username)
        else:
            label = "full" if rtype == "full" else "cost-only"
            self.query_one("#rp-status", Static).update(
                f"Generating {label} report ({days}d) — Snowflake call…"
            )
            self.query_one("#rp-generate", Button).disabled = True
            self.query_one("#rp-save", Button).disabled = True
            self._cost_worker(report_type=rtype, days=days, top_n=top_n)

    @work(thread=True, exclusive=True, group="snowflake")
    def _cost_worker(self, *, report_type: str, days: int, top_n: int) -> None:
        from snowglobe.core.report_service import ReportService
        try:
            svc = ReportService(self.app.context)
            data = svc.generate_full_report(days=days, top_n=top_n)
            if report_type == "cost":
                data["top_queries"] = []
            markdown = svc.render_markdown(data)
        except Exception as e:
            self.app.call_from_thread(self._generate_failed, e)
            return
        self.app.call_from_thread(self._render_markdown, markdown)

    @work(thread=True, exclusive=True, group="snowflake")
    def _user_worker(self, *, username: str) -> None:
        from snowglobe.core.access_service import AccessService
        try:
            # Reuse the app's preloaded service so state isn't reloaded.
            svc = self.app.access_service or AccessService(self.app.context)
            data = svc.inspect_user_report(username)
            markdown = _format_user_report(data)
        except Exception as e:
            self.app.call_from_thread(self._generate_failed, e)
            return
        self.app.call_from_thread(self._render_markdown, markdown)

    def _generate_failed(self, err: Exception) -> None:
        self.query_one("#rp-status", Static).update(f"Generation failed: {err}")
        self.query_one("#rp-generate", Button).disabled = False
        self.app.notify(f"Report generation failed: {err}", severity="error", timeout=8)

    def _render_markdown(self, markdown: str) -> None:
        self._last_markdown = markdown
        self.query_one("#rp-preview", Markdown).update(markdown)
        line_count = markdown.count("\n") + 1
        self.query_one("#rp-status", Static).update(
            f"Report generated — {line_count} lines. Click Save to write to disk."
        )
        self.query_one("#rp-generate", Button).disabled = False
        self.query_one("#rp-save", Button).disabled = False

    # --- Save ---------------------------------------------------------

    def _save(self) -> None:
        if not self._last_markdown:
            self.app.notify("Generate a report first.", severity="warning")
            return
        path = self.query_one("#rp-path", Input).value.strip()
        if not path:
            self.app.notify("Output path required.", severity="warning")
            return
        try:
            target = Path(path).expanduser()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(self._last_markdown)
        except Exception as e:
            self.app.notify(f"Save failed: {e}", severity="error", timeout=8)
            return
        self.query_one("#rp-status", Static).update(f"Saved {target}")
        self.app.notify(f"Saved to {target}", timeout=4)


def _format_user_report(data: dict) -> str:
    """Render the AccessService.inspect_user_report() dict as markdown."""
    lines: list[str] = []
    user = data.get("username", "?")
    lines.append(f"# Access report — {user}")
    lines.append("")
    lines.append(f"- Effective roles: **{data.get('role_count', 0)}**")
    lines.append(f"- Total objects with grants: **{data.get('total_objects', 0)}**")
    lines.append(f"- Total grants: **{data.get('total_grants', 0)}**")
    lines.append("")

    direct = data.get("direct_roles", [])
    excluded = data.get("excluded_roles", [])
    if direct:
        lines.append(f"## Direct roles ({len(direct)})")
        for r in direct: lines.append(f"- `{r}`")
        lines.append("")
    if excluded:
        lines.append(f"## Excluded by profile ({len(excluded)})")
        for r in excluded: lines.append(f"- `{r}`")
        lines.append("")

    summary = data.get("grant_summary", {}) or {}
    if summary:
        lines.append("## Grants by object type")
        lines.append("")
        lines.append("| Object type | Objects | Privileges |")
        lines.append("|---|---:|---|")
        for ot, info in sorted(summary.items()):
            privs = ", ".join(info.get("privileges", []))
            lines.append(f"| {ot} | {info.get('object_count', 0)} | {privs} |")
        lines.append("")
        for ot, info in sorted(summary.items()):
            objects = info.get("objects", [])
            if not objects:
                continue
            lines.append(f"### {ot}  ({info.get('object_count', 0)} object(s), "
                         f"{info.get('total_grants', 0)} grant(s))")
            for obj in objects:
                lines.append(f"- `{obj}`")
            lines.append("")

    return "\n".join(lines)
