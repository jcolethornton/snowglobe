"""Risk screen — five tabs over RiskService + AccessService.

Tabs:
  1. Scan          — full privilege-escalation scan with risk scoring
                     (RiskService.run_scan; touches Snowflake for dormant users)
  2. Escalation    — single-role escalation check (pure SQLite + in-memory)
  3. Dormant       — users inactive >90 days holding risk-bearing roles
                     (derived from the most recent Scan)
  4. Direct grants — dangerous direct grants (MANAGE GRANTS, OWNERSHIP, ...)
                     (pure SQLite)
  5. Unused        — roles with privileges but no recent activity
                     (AccessService.detect_unused_privileges; QUERY_HISTORY)
"""
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.suggester import SuggestFromList
from textual.widgets import (
    Button, DataTable, Input, Static, TabbedContent, TabPane, Tree,
)


class RiskScreen(Vertical):
    """Privilege-escalation scan + supporting risk views."""

    # Cache the most recent scan so Dormant + the KPI summary survive tab switches.
    _last_scan: dict | None = None

    def compose(self) -> ComposeResult:
        yield Static("Risk", classes="screen-title")

        with TabbedContent(initial="tab-scan"):

            # ----- 1. Scan -----
            with TabPane("Scan", id="tab-scan"):
                yield Static(
                    "No scan yet — press Run scan. (Touches Snowflake for dormant users.)",
                    id="rs-summary", classes="panel-title",
                )
                yield Static("", id="rs-diff", classes="hint")
                with Horizontal(id="rs-buttons", classes="actions-row"):
                    yield Button("Run scan", id="rs-run", variant="primary")
                    yield Button("Export CSV", id="rs-csv", disabled=True)
                    yield Button("Export JSON", id="rs-json", disabled=True)
                yield DataTable(id="rs-table", cursor_type="row", zebra_stripes=True)

            # ----- 2. Escalation -----
            with TabPane("Escalation", id="tab-escalation"):
                with Vertical(classes="access-form"):
                    with Horizontal(classes="form-row"):
                        yield Static("Role:", classes="form-label")
                        yield Input(
                            placeholder="ACCOUNT_ROLE::FOO  or  DATABASE_ROLE::DB::FOO",
                            id="es-role", classes="form-input",
                        )
                    yield Button("Run  (Enter)", id="es-run", variant="primary")
                yield Tree("Pick a role and run.", id="es-result")

            # ----- 3. Dormant -----
            with TabPane("Dormant", id="tab-dormant"):
                yield Static(
                    "Dormant users with risk paths are populated by the Scan tab.",
                    id="dm-status", classes="hint",
                )
                yield DataTable(id="dm-table", cursor_type="row", zebra_stripes=True)

            # ----- 4. Direct grants -----
            with TabPane("Direct grants", id="tab-direct"):
                yield Static(
                    "Roles with dangerous direct grants (MANAGE GRANTS / CREATE ROLE / "
                    "CREATE USER / IMPORTED PRIVILEGES / DB or warehouse OWNERSHIP).",
                    classes="hint",
                )
                with Horizontal(classes="actions-row"):
                    yield Button("Load", id="dg-run", variant="primary")
                yield DataTable(id="dg-table", cursor_type="row", zebra_stripes=True)

            # ----- 5. Unused -----
            with TabPane("Unused", id="tab-unused"):
                with Vertical(classes="access-form"):
                    with Horizontal(classes="form-row"):
                        yield Static("Inactive >", classes="form-label")
                        yield Input(value="90", id="un-days", classes="form-input")
                    yield Button("Run  (Snowflake call)", id="un-run", variant="warning")
                yield Static(
                    "Cross-checks granted roles against QUERY_HISTORY activity.",
                    id="un-status", classes="hint",
                )
                yield DataTable(id="un-table", cursor_type="row", zebra_stripes=True)

    # --- Lifecycle ----------------------------------------------------

    def on_mount(self) -> None:
        # Role suggester for Escalation tab.
        self.watch(self.app, "role_graph",
                   lambda _v: self._refresh_role_suggester())

    def _refresh_role_suggester(self) -> None:
        if not self.is_mounted or self.app.role_graph is None:
            return
        try:
            roles = sorted(self.app.role_graph.roles.keys())
            self.query_one("#es-role", Input).suggester = SuggestFromList(
                roles, case_sensitive=False
            )
        except Exception:
            pass

    # --- Events -------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if   bid == "rs-run":  self._start_scan()
        elif bid == "rs-csv":  self._export_csv()
        elif bid == "rs-json": self._export_json()
        elif bid == "es-run":  self._run_escalation()
        elif bid == "dg-run":  self._run_direct_grants()
        elif bid == "un-run":  self._start_unused()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        active = self.query_one(TabbedContent).active
        if active == "tab-escalation":
            self._run_escalation()
        elif active == "tab-unused":
            self._start_unused()

    def on_tab_activated(self, event) -> None:
        # When the user switches to Dormant, ensure the table reflects _last_scan.
        active = self.query_one(TabbedContent).active
        if active == "tab-dormant":
            self._render_dormant()

    # --- Tab 1: Scan --------------------------------------------------

    def _start_scan(self) -> None:
        if self.app.role_graph is None or self.app.user_graph is None:
            self.app.notify("State still loading.", severity="warning")
            return
        self._set_buttons_busy(True)
        self.query_one("#rs-summary", Static).update("Running escalation scan…")
        self._scan_worker()

    @work(thread=True, exclusive=True, group="snowflake")
    def _scan_worker(self) -> None:
        from snowglobe.core.risk_service import RiskService
        try:
            svc = RiskService(self.app.context)
            result = svc.run_scan(self.app.role_graph, self.app.user_graph)
        except Exception as e:
            self.app.call_from_thread(self._scan_failed, e)
            return
        self.app.call_from_thread(self._render_scan, result)

    def _scan_failed(self, err: Exception) -> None:
        self.query_one("#rs-summary", Static).update(f"Scan failed: {err}")
        self._set_buttons_busy(False)
        self.app.notify(f"Scan failed: {err}", severity="error", timeout=8)

    def _render_scan(self, result: dict) -> None:
        self._last_scan = result
        s = result["summary"]
        diff = result.get("diff")

        # Top KPI line
        kpi = (
            f"admin: {s['admin_roles']}  ·  "
            f"high: {s['high_risk']}  ·  "
            f"medium: {s['medium_risk']}  ·  "
            f"low: {s['low_risk']}  ·  "
            f"direct privilege risks: {s['direct_privilege_risks']}  ·  "
            f"dormant: {s['dormant_with_risk']}"
        )
        self.query_one("#rs-summary", Static).update(kpi)

        # Diff line
        diff_line = ""
        if diff:
            n_new = len(diff.get("new", []))
            n_res = len(diff.get("resolved", []))
            if n_new or n_res:
                parts = []
                if n_new: parts.append(f"+{n_new} new")
                if n_res: parts.append(f"-{n_res} resolved")
                diff_line = "Δ since last scan:  " + ", ".join(parts)
            else:
                diff_line = "No changes since last scan."
        self.query_one("#rs-diff", Static).update(diff_line)

        # Build the table
        new_roles = set(diff.get("new", [])) if diff else set()
        table = self.query_one("#rs-table", DataTable)
        table.clear(columns=True)
        table.add_columns("#", "SCORE", "ROLE", "TARGET", "HOPS", "USERS", "Δ")
        for i, entry in enumerate(result["flagged"], 1):
            delta = "NEW" if entry["role"] in new_roles else ""
            table.add_row(
                str(i),
                f"{entry['risk_score']:.1f}",
                entry["role"],
                entry["target"],
                str(entry["hops"]),
                str(entry["user_count"]),
                delta,
                key=entry["role"],
            )

        self._set_buttons_busy(False)
        self.query_one("#rs-csv", Button).disabled = False
        self.query_one("#rs-json", Button).disabled = False
        self.app.notify(
            f"Scan complete — {s['high_risk']} high, {s['medium_risk']} medium.",
            timeout=4,
        )
        # If the Dormant tab is active, refresh it too.
        if self.query_one(TabbedContent).active == "tab-dormant":
            self._render_dormant()

    def _set_buttons_busy(self, busy: bool) -> None:
        for bid in ("rs-run", "rs-csv", "rs-json"):
            try:
                self.query_one(f"#{bid}", Button).disabled = busy
            except Exception:
                pass
        if not busy:
            # Re-enable export only if we have a scan
            has_scan = self._last_scan is not None
            self.query_one("#rs-csv", Button).disabled = not has_scan
            self.query_one("#rs-json", Button).disabled = not has_scan
            self.query_one("#rs-run", Button).disabled = False

    def _export_csv(self) -> None:
        if not self._last_scan:
            return
        from snowglobe.core.risk_service import RiskService
        from datetime import date
        path = f"snowglobe_scan_{date.today().isoformat()}.csv"
        try:
            RiskService.export_scan_csv(self._last_scan["flagged"], path)
        except Exception as e:
            self.app.notify(f"Export failed: {e}", severity="error", timeout=6)
            return
        self.app.notify(f"Exported {path}", timeout=4)

    def _export_json(self) -> None:
        if not self._last_scan:
            return
        from snowglobe.core.risk_service import RiskService
        from datetime import date
        path = f"snowglobe_scan_{date.today().isoformat()}.json"
        try:
            RiskService.export_scan_json(self._last_scan, path)
        except Exception as e:
            self.app.notify(f"Export failed: {e}", severity="error", timeout=6)
            return
        self.app.notify(f"Exported {path}", timeout=4)

    # --- Tab 2: Escalation -------------------------------------------

    def _run_escalation(self) -> None:
        if self.app.role_graph is None or self.app.user_graph is None:
            self.app.notify("State still loading.", severity="warning")
            return
        role = self.query_one("#es-role", Input).value.strip()
        if not role:
            self.app.notify("Role required.", severity="warning")
            return
        from snowglobe.core.risk_service import RiskService
        try:
            svc = RiskService(self.app.context)
            result = svc.check_escalation(role, self.app.role_graph, self.app.user_graph)
        except Exception as e:
            self.app.notify(f"Escalation check failed: {e}", severity="error", timeout=6)
            return
        self._render_escalation(result)

    def _render_escalation(self, result: dict) -> None:
        tree = self.query_one("#es-result", Tree)
        tree.clear()
        role = result["role"]

        if result["is_privileged"]:
            tree.root.label = f"⚠ {role} IS itself a privileged role"
            tree.root.expand()
            return

        reachable = result["reachable_targets"]
        if not reachable:
            tree.root.label = f"✓ {role} has NO escalation path to admin"
            tree.root.expand()
            tree.root.add_leaf(
                "Cannot reach ACCOUNTADMIN, SYSADMIN, SECURITYADMIN, USERADMIN, "
                "or any role with MANAGE GRANTS / ownership of DBs."
            )
            return

        tree.root.label = f"✗ {role} can reach {len(reachable)} privileged role(s)"
        tree.root.expand()
        for entry in reachable:
            n = tree.root.add(
                f"{entry['target']}  ·  {entry['hops']} hop(s)",
                expand=True,
            )
            n.add_leaf(" → ".join(entry["path"]))

        # Affected users
        direct = result["affected_users"]["direct"]
        inherited = result["affected_users"]["inherited"]
        total = len(direct) + len(inherited)
        if total > 0:
            u = tree.root.add(f"Users who can escalate via {role} ({total})", expand=False)
            for usr in direct[:20]:
                u.add_leaf(f"{usr}  ·  (directly assigned)")
            for usr in inherited[:20]:
                u.add_leaf(f"{usr}  ·  (inherited)")
            tail = max(len(direct) - 20, 0) + max(len(inherited) - 20, 0)
            if tail:
                u.add_leaf(f"… and {tail} more")

    # --- Tab 3: Dormant ----------------------------------------------

    def _render_dormant(self) -> None:
        status = self.query_one("#dm-status", Static)
        table = self.query_one("#dm-table", DataTable)
        table.clear(columns=True)

        if not self._last_scan:
            status.update("Run a Scan first to populate dormant users.")
            return

        dormant = self._last_scan.get("dormant_users") or []
        # Dedupe by user, keep highest risk score
        seen: dict[str, dict] = {}
        for d in sorted(dormant, key=lambda x: x["risk_score"], reverse=True):
            seen.setdefault(d["user"], d)
        unique = list(seen.values())

        if not unique:
            status.update("No dormant users (inactive >90 days) hold risk-bearing roles.")
            return

        status.update(f"{len(unique)} dormant user(s) inactive >90 days with risk paths.")
        table.add_columns("USER", "VIA ROLE", "RISK SCORE")
        for d in unique:
            table.add_row(d["user"], d["role"], f"{d['risk_score']:.1f}", key=d["user"])

    # --- Tab 4: Direct grants ----------------------------------------

    def _run_direct_grants(self) -> None:
        from snowglobe.core.risk_service import RiskService
        try:
            svc = RiskService(self.app.context)
            rows = svc.get_dangerous_direct_grants()
        except Exception as e:
            self.app.notify(f"Direct grants lookup failed: {e}", severity="error", timeout=6)
            return
        table = self.query_one("#dg-table", DataTable)
        table.clear(columns=True)
        if not rows:
            table.add_columns("(no dangerous direct grants found)")
            return
        table.add_columns("ROLE", "PRIVILEGE", "OBJECT TYPE", "OBJECT")
        for r in rows:
            table.add_row(
                r["ROLE"], r["PRIVILEGE"], r["OBJECT_TYPE"], r["OBJECT"],
                key=f"{r['ROLE']}::{r['PRIVILEGE']}::{r['OBJECT']}",
            )

    # --- Tab 5: Unused -----------------------------------------------

    def _start_unused(self) -> None:
        if self.app.access_service is None:
            self.app.notify("State still loading.", severity="warning")
            return
        try:
            days = int(self.query_one("#un-days", Input).value.strip() or "90")
        except ValueError:
            self.app.notify("Days must be an integer.", severity="warning")
            return
        self.query_one("#un-status", Static).update(
            f"Fetching unused privileges (inactive >{days} days) — Snowflake call…"
        )
        self._unused_worker(days=days)

    @work(thread=True, exclusive=True, group="snowflake")
    def _unused_worker(self, *, days: int) -> None:
        try:
            df, error = self.app.access_service.detect_unused_privileges(days=days)
        except Exception as e:
            self.app.call_from_thread(self._unused_failed, e)
            return
        self.app.call_from_thread(self._render_unused, df, error, days)

    def _unused_failed(self, err: Exception) -> None:
        self.query_one("#un-status", Static).update(f"Failed: {err}")
        self.app.notify(f"Unused lookup failed: {err}", severity="error", timeout=8)

    def _render_unused(self, df, error: str | None, days: int) -> None:
        table = self.query_one("#un-table", DataTable)
        table.clear(columns=True)
        status = self.query_one("#un-status", Static)

        if error:
            status.update(error)
            return
        if df is None or df.empty:
            status.update(f"All roles with data grants are active in the last {days} days.")
            return

        status.update(f"{len(df)} role(s) inactive >{days} days with data privileges.")
        table.add_columns("ROLE", "GRANTED_OBJECTS", "DAYS_INACTIVE")
        for _, row in df.iterrows():
            table.add_row(
                str(row.get("ROLE", "")),
                str(row.get("GRANTED_OBJECTS", "")),
                str(row.get("DAYS_INACTIVE", "")),
                key=str(row.get("ROLE", "")),
            )
