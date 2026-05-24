"""Access screen — seven tabs.

Tabs (matching the shell's 'check' wizard order):
  1. Check        — Can identity X access object Y with privilege Z?
  2. Who-access   — Who can access object Y?
  3. Create       — Where can identity X create objects?
  4. Roles        — What roles does user Y have?
  5. Members      — Who has role Y?
  6. Path         — Does role X inherit from role Y?
  7. Drift        — What's changed since last refresh?

Check / Who-access / Create / Roles / Members / Path are SQLite-only and run
synchronously. Drift hits Snowflake and runs in a background worker.

Privilege options on Check and Who-access narrow automatically when
object_type changes (matches shell behaviour).
"""
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.suggester import SuggestFromList
from textual.widgets import (
    Button, Input, Select, Static, TabbedContent, TabPane, Tree,
)

from snowglobe.models.object_type import ObjectType
from snowglobe.models.privilege import privileges_for_object_type
from snowglobe.tui.widgets.access_paths import AccessPathsTree


_CREATE_PRIVILEGES = [
    "CREATE TABLE", "CREATE VIEW", "CREATE SCHEMA", "CREATE DATABASE",
    "CREATE DYNAMIC TABLE", "CREATE STREAMLIT", "CREATE NOTEBOOK",
    "CREATE STAGE", "CREATE STREAM", "CREATE PIPE", "CREATE TASK",
    "CREATE FUNCTION", "CREATE PROCEDURE", "CREATE ALERT",
    "CREATE FILE FORMAT", "CREATE SEQUENCE", "CREATE TAG",
    "CREATE SECRET", "CREATE WAREHOUSE", "CREATE ROLE",
    "CREATE MATERIALIZED VIEW", "CREATE EXTERNAL TABLE",
    "CREATE ICEBERG TABLE", "CREATE MODEL",
]

_IDENTITY_TYPES = [("User", "user"), ("Role", "role")]

_DRIFT_WINDOWS = [
    ("Since last refresh", "0"),
    ("Last 24 hours",      "1"),
    ("Last 7 days",        "7"),
    ("Last 30 days",       "30"),
]

_DEFAULT_OBJECT_TYPE = "TABLE"


def _object_type_options() -> list[tuple[str, str]]:
    return [(t.value, t.value) for t in ObjectType if t != ObjectType.UNKNOWN]


def _priv_opts(items: list[str]) -> list[tuple[str, str]]:
    return [(p, p) for p in items]


class AccessScreen(Vertical):
    """Access — seven tabs sharing the App's AccessService and graphs."""

    def compose(self) -> ComposeResult:
        yield Static("Access", classes="screen-title")

        default_privs = privileges_for_object_type(_DEFAULT_OBJECT_TYPE)

        with TabbedContent(initial="tab-check"):

            # ----- 1. Check -----
            with TabPane("Check", id="tab-check"):
                with Vertical(classes="access-form"):
                    with Horizontal(classes="form-row"):
                        yield Static("Type:", classes="form-label")
                        yield Select(_IDENTITY_TYPES, value="user",
                                     id="check-type", classes="form-select", allow_blank=False)
                    with Horizontal(classes="form-row"):
                        yield Static("Identity:", classes="form-label")
                        yield Input(placeholder="user name or role key",
                                    id="check-identity", classes="form-input")
                    with Horizontal(classes="form-row"):
                        yield Static("Object type:", classes="form-label")
                        yield Select(_object_type_options(), value=_DEFAULT_OBJECT_TYPE,
                                     id="check-obj-type", classes="form-select", allow_blank=False)
                    with Horizontal(classes="form-row"):
                        yield Static("Object FQN:", classes="form-label")
                        yield Input(placeholder="DB.SCHEMA.OBJECT",
                                    id="check-obj-name", classes="form-input")
                    with Horizontal(classes="form-row"):
                        yield Static("Privilege:", classes="form-label")
                        yield Select(_priv_opts(default_privs), value=default_privs[0],
                                     id="check-priv", classes="form-select", allow_blank=False)
                    yield Button("Run  (Enter)", id="check-run", variant="primary")
                yield AccessPathsTree("Result will appear here", id="check-result")

            # ----- 2. Who-access -----
            with TabPane("Who-access", id="tab-whoaccess"):
                with Vertical(classes="access-form"):
                    with Horizontal(classes="form-row"):
                        yield Static("Object type:", classes="form-label")
                        yield Select(_object_type_options(), value=_DEFAULT_OBJECT_TYPE,
                                     id="wa-obj-type", classes="form-select", allow_blank=False)
                    with Horizontal(classes="form-row"):
                        yield Static("Object FQN:", classes="form-label")
                        yield Input(placeholder="DB.SCHEMA.OBJECT",
                                    id="wa-obj-name", classes="form-input")
                    with Horizontal(classes="form-row"):
                        yield Static("Privilege:", classes="form-label")
                        yield Select(_priv_opts(default_privs),
                                     id="wa-priv", classes="form-select", allow_blank=True,
                                     prompt="(any)")
                    yield Button("Run  (Enter)", id="wa-run", variant="primary")
                yield Tree("Pick an object and run.", id="wa-result")

            # ----- 3. Create -----
            with TabPane("Create", id="tab-create"):
                with Vertical(classes="access-form"):
                    with Horizontal(classes="form-row"):
                        yield Static("Type:", classes="form-label")
                        yield Select(_IDENTITY_TYPES, value="role",
                                     id="cr-type", classes="form-select", allow_blank=False)
                    with Horizontal(classes="form-row"):
                        yield Static("Identity:", classes="form-label")
                        yield Input(placeholder="role key or username",
                                    id="cr-identity", classes="form-input")
                    with Horizontal(classes="form-row"):
                        yield Static("Privilege:", classes="form-label")
                        yield Select(_priv_opts(_CREATE_PRIVILEGES), value="CREATE TABLE",
                                     id="cr-priv", classes="form-select", allow_blank=False)
                    with Horizontal(classes="form-row"):
                        yield Static("Scope:", classes="form-label")
                        yield Input(placeholder="optional — DB or DB.SCHEMA",
                                    id="cr-scope", classes="form-input")
                    yield Button("Run  (Enter)", id="cr-run", variant="primary")
                yield Tree("Pick an identity + privilege and run.", id="cr-result")

            # ----- 4. Roles (what roles does a user have?) -----
            with TabPane("Roles", id="tab-roles"):
                with Vertical(classes="access-form"):
                    with Horizontal(classes="form-row"):
                        yield Static("User:", classes="form-label")
                        yield Input(placeholder="username",
                                    id="ro-user", classes="form-input")
                    yield Button("Run  (Enter)", id="ro-run", variant="primary")
                yield Tree("Pick a user and run.", id="ro-result")

            # ----- 5. Members (who has this role?) -----
            with TabPane("Members", id="tab-members"):
                with Vertical(classes="access-form"):
                    with Horizontal(classes="form-row"):
                        yield Static("Role:", classes="form-label")
                        yield Input(placeholder="ACCOUNT_ROLE::… or DATABASE_ROLE::DB::…",
                                    id="me-role", classes="form-input")
                    yield Button("Run  (Enter)", id="me-run", variant="primary")
                yield Tree("Pick a role and run.", id="me-result")

            # ----- 6. Path -----
            with TabPane("Path", id="tab-path"):
                with Vertical(classes="access-form"):
                    with Horizontal(classes="form-row"):
                        yield Static("From role:", classes="form-label")
                        yield Input(placeholder="ACCOUNT_ROLE::FOO",
                                    id="pa-from", classes="form-input")
                    with Horizontal(classes="form-row"):
                        yield Static("To role:", classes="form-label")
                        yield Input(placeholder="ACCOUNT_ROLE::SYSADMIN",
                                    id="pa-to", classes="form-input")
                    yield Button("Run  (Enter)", id="pa-run", variant="primary")
                yield Tree("Pick two roles and run.", id="pa-result")

            # ----- 7. Drift -----
            with TabPane("Drift", id="tab-drift"):
                with Vertical(classes="access-form"):
                    with Horizontal(classes="form-row"):
                        yield Static("Compare:", classes="form-label")
                        yield Select(_DRIFT_WINDOWS, value="0",
                                     id="dr-since", classes="form-select", allow_blank=False)
                    yield Button("Run  (Snowflake call)", id="dr-run", variant="warning")
                yield Static("Drift hits Snowflake; runs in a worker.",
                             id="dr-status", classes="hint")
                yield Tree("Pick a window and run.", id="dr-result")

    # --- Mount: wire reactive suggesters ------------------------------

    def on_mount(self) -> None:
        self.watch(self.app, "user_graph",
                   lambda _v: self._refresh_identity_suggesters())
        self.watch(self.app, "role_graph",
                   lambda _v: self._refresh_identity_suggesters())
        self.watch(self.app, "object_index",
                   lambda _v: self._refresh_object_suggesters())

    def _refresh_identity_suggesters(self) -> None:
        users = sorted(self.app.user_graph.assigned_roles.keys()) if self.app.user_graph else []
        roles = sorted(self.app.role_graph.roles.keys()) if self.app.role_graph else []
        if not self.is_mounted:
            return
        try:
            # Check tab — depends on type
            check_type = self.query_one("#check-type", Select).value
            self.query_one("#check-identity", Input).suggester = SuggestFromList(
                users if check_type == "user" else roles, case_sensitive=False
            )
            # Create tab — depends on type
            create_type = self.query_one("#cr-type", Select).value
            self.query_one("#cr-identity", Input).suggester = SuggestFromList(
                users if create_type == "user" else roles, case_sensitive=False
            )
            # Roles tab — user input
            self.query_one("#ro-user", Input).suggester = SuggestFromList(
                users, case_sensitive=False
            )
            # Members tab — role input
            self.query_one("#me-role", Input).suggester = SuggestFromList(
                roles, case_sensitive=False
            )
            # Path tab — both roles
            self.query_one("#pa-from", Input).suggester = SuggestFromList(roles, case_sensitive=False)
            self.query_one("#pa-to", Input).suggester = SuggestFromList(roles, case_sensitive=False)
        except Exception:
            pass

    def _refresh_object_suggesters(self) -> None:
        if not self.is_mounted or self.app.object_index is None:
            return
        try:
            ot = self.query_one("#check-obj-type", Select).value
            self.query_one("#check-obj-name", Input).suggester = SuggestFromList(
                self.app.object_index.get(ot, []), case_sensitive=False
            )
        except Exception:
            pass
        try:
            ot = self.query_one("#wa-obj-type", Select).value
            self.query_one("#wa-obj-name", Input).suggester = SuggestFromList(
                self.app.object_index.get(ot, []), case_sensitive=False
            )
        except Exception:
            pass

    def _update_privilege_options(self, select_id: str, object_type: str, keep_blank: bool) -> None:
        """Narrow a privilege Select's options to those valid for `object_type`."""
        privs = privileges_for_object_type(object_type)
        select = self.query_one(f"#{select_id}", Select)
        select.set_options(_priv_opts(privs))
        # Reset to first valid value (or BLANK on the who-access "any" selector).
        if keep_blank:
            select.clear()
        else:
            select.value = privs[0]

    # --- Events -------------------------------------------------------

    def on_select_changed(self, event: Select.Changed) -> None:
        sid = event.select.id
        if sid in ("check-type", "cr-type"):
            self._refresh_identity_suggesters()
        elif sid == "check-obj-type":
            self._refresh_object_suggesters()
            self._update_privilege_options("check-priv", str(event.value), keep_blank=False)
        elif sid == "wa-obj-type":
            self._refresh_object_suggesters()
            self._update_privilege_options("wa-priv", str(event.value), keep_blank=True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if   bid == "check-run": self._run_check()
        elif bid == "wa-run":    self._run_whoaccess()
        elif bid == "cr-run":    self._run_create()
        elif bid == "ro-run":    self._run_roles()
        elif bid == "me-run":    self._run_members()
        elif bid == "pa-run":    self._run_path()
        elif bid == "dr-run":    self._run_drift()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        active = self.query_one(TabbedContent).active
        runners = {
            "tab-check":     self._run_check,
            "tab-whoaccess": self._run_whoaccess,
            "tab-create":    self._run_create,
            "tab-roles":     self._run_roles,
            "tab-members":   self._run_members,
            "tab-path":      self._run_path,
            "tab-drift":     self._run_drift,
        }
        runner = runners.get(active)
        if runner is not None:
            runner()

    # --- Tab 1: Check -------------------------------------------------

    def _run_check(self) -> None:
        svc = self.app.access_service
        if svc is None:
            self.app.notify("State still loading — try again.", severity="warning")
            return
        ident_type = self.query_one("#check-type", Select).value
        ident = self.query_one("#check-identity", Input).value.strip()
        obj_type = self.query_one("#check-obj-type", Select).value
        obj_name = self.query_one("#check-obj-name", Input).value.strip().upper()
        priv = self.query_one("#check-priv", Select).value

        if not ident or not obj_name:
            self.app.notify("Identity and Object FQN required.", severity="warning")
            return

        try:
            result = svc.inspect_access(
                username=ident if ident_type == "user" else None,
                role=ident if ident_type == "role" else None,
                object_type=obj_type, object_name=obj_name, privilege=priv,
                ignore_excluded_roles=False, refresh_state=False,
            )
        except Exception as e:
            self.app.notify(f"Check failed: {e}", severity="error", timeout=6)
            return
        self.query_one("#check-result", AccessPathsTree).render_result(result, ident)

    # --- Tab 2: Who-access -------------------------------------------

    def _run_whoaccess(self) -> None:
        svc = self.app.access_service
        if svc is None:
            self.app.notify("State still loading.", severity="warning")
            return
        obj_type = self.query_one("#wa-obj-type", Select).value
        obj_name = self.query_one("#wa-obj-name", Input).value.strip().upper()
        priv_val = self.query_one("#wa-priv", Select).value
        priv = priv_val if isinstance(priv_val, str) and priv_val else None
        if not obj_name:
            self.app.notify("Object FQN required.", severity="warning")
            return
        try:
            result = svc.inspect_reverse(object_type=obj_type, object_name=obj_name, privilege=priv)
        except Exception as e:
            self.app.notify(f"Who-access failed: {e}", severity="error", timeout=6)
            return
        self._render_whoaccess(result)

    def _render_whoaccess(self, result: dict) -> None:
        tree = self.query_one("#wa-result", Tree)
        tree.clear()
        if not result.get("object_exists"):
            tree.root.label = f"✗ {result.get('object_name')} not found in cached grants"
            tree.root.expand()
            return
        privileges = result.get("privileges") or {}
        if not privileges:
            tree.root.label = f"No grants matching filter on {result['object_name']}"
            tree.root.expand()
            return
        tree.root.label = f"Who can access {result['object_name']} — {len(privileges)} privilege(s)"
        tree.root.expand()
        for priv, info in privileges.items():
            direct = info.get("direct_roles", [])
            inherited = info.get("inherited_roles", [])
            users = info.get("users", [])
            priv_node = tree.root.add(
                f"{priv}  ·  {len(direct)} direct + {len(inherited)} inherited  ·  {len(users)} users",
                expand=True,
            )
            if direct:
                d = priv_node.add(f"Direct roles ({len(direct)})", expand=False)
                for r in direct: d.add_leaf(r)
            if inherited:
                i = priv_node.add(f"Inherited roles ({len(inherited)})", expand=False)
                for r in inherited[:30]: i.add_leaf(r)
                if len(inherited) > 30:
                    i.add_leaf(f"… and {len(inherited) - 30} more")
            if users:
                u = priv_node.add(f"Users ({len(users)})", expand=False)
                for usr in users[:30]:
                    via = ", ".join(usr.get("via_roles", []))
                    u.add_leaf(f"{usr['user']}  ←  via {via}")
                if len(users) > 30:
                    u.add_leaf(f"… and {len(users) - 30} more")

    # --- Tab 3: Create -----------------------------------------------

    def _run_create(self) -> None:
        svc = self.app.access_service
        if svc is None:
            self.app.notify("State still loading.", severity="warning")
            return
        ident_type = self.query_one("#cr-type", Select).value
        ident = self.query_one("#cr-identity", Input).value.strip()
        priv = self.query_one("#cr-priv", Select).value
        scope = self.query_one("#cr-scope", Input).value.strip() or None
        if not ident:
            self.app.notify("Identity required.", severity="warning")
            return
        try:
            result = svc.inspect_create(
                username=ident if ident_type == "user" else None,
                role=ident if ident_type == "role" else None,
                privilege=priv, scope=scope,
            )
        except Exception as e:
            self.app.notify(f"Create check failed: {e}", severity="error", timeout=6)
            return
        self._render_create(result)

    def _render_create(self, result: dict) -> None:
        tree = self.query_one("#cr-result", Tree)
        tree.clear()
        ident = result["identity"]
        priv = result["privilege"]
        if not result["has_access"]:
            tree.root.label = f"✗ {ident} cannot {priv} anywhere in scope"
            tree.root.expand()
            return
        tree.root.label = f"✓ {ident} can {priv}"
        tree.root.expand()
        if result["account_wide"]:
            n = tree.root.add(
                f"Account-wide (via {len(result['account_wide_roles'])} role(s))",
                expand=True,
            )
            for r in result["account_wide_roles"]: n.add_leaf(r)
        if result["databases"]:
            d = tree.root.add(f"Databases ({len(result['databases'])})", expand=True)
            for db in result["databases"]:
                roles = ", ".join(db["via_roles"])
                d.add_leaf(f"{db['name']}  ←  via {roles}")
        if result["schemas"]:
            s = tree.root.add(f"Schemas ({len(result['schemas'])})", expand=True)
            for sch in result["schemas"]:
                roles = ", ".join(sch["via_roles"])
                s.add_leaf(f"{sch['name']}  ←  via {roles}")
        paths = result.get("access_paths") or []
        if paths:
            p = tree.root.add(f"Inheritance paths to granting roles ({len(paths)})", expand=False)
            for chain in paths[:20]:
                p.add_leaf(" → ".join(chain))
            if len(paths) > 20:
                p.add_leaf(f"… and {len(paths) - 20} more")

    # --- Tab 4: Roles (what roles does a user have?) ----------------

    def _run_roles(self) -> None:
        ug = self.app.user_graph
        rg = self.app.role_graph
        if ug is None or rg is None:
            self.app.notify("State still loading.", severity="warning")
            return
        username = self.query_one("#ro-user", Input).value.strip()
        if not username:
            self.app.notify("Username required.", severity="warning")
            return
        if username not in ug.assigned_roles:
            self.app.notify(f"User '{username}' not found in cached state.", severity="warning")
            return
        direct, excluded = ug.roles_of(username)
        effective = ug.effective_roles(username, rg)
        inherited = effective - set(direct) - set(excluded)
        self._render_roles(username, list(direct), list(excluded), list(inherited), effective)

    def _render_roles(self, user: str, direct: list, excluded: list,
                      inherited: list, effective: set) -> None:
        tree = self.query_one("#ro-result", Tree)
        tree.clear()
        tree.root.label = f"Roles for {user} — {len(effective)} effective"
        tree.root.expand()
        if direct:
            d = tree.root.add(f"Direct ({len(direct)})", expand=True)
            for r in sorted(direct): d.add_leaf(r)
        if excluded:
            e = tree.root.add(f"Excluded by profile ({len(excluded)})", expand=False)
            for r in sorted(excluded): e.add_leaf(r)
        if inherited:
            i = tree.root.add(f"Inherited ({len(inherited)})", expand=False)
            for r in sorted(inherited)[:50]: i.add_leaf(r)
            if len(inherited) > 50:
                i.add_leaf(f"… and {len(inherited) - 50} more")
        if not direct and not inherited:
            tree.root.add_leaf("(user has no roles assigned)")

    # --- Tab 5: Members (who has this role?) ------------------------

    def _run_members(self) -> None:
        ug = self.app.user_graph
        rg = self.app.role_graph
        if ug is None or rg is None:
            self.app.notify("State still loading.", severity="warning")
            return
        role = self.query_one("#me-role", Input).value.strip()
        if not role:
            self.app.notify("Role required.", severity="warning")
            return
        direct: list[str] = []
        inherited: list[str] = []
        for user, assigned in ug.assigned_roles.items():
            if role in assigned:
                direct.append(user)
                continue
            eff = set(assigned)
            for r in assigned:
                eff |= rg.all_ancestors(r)
            if role in eff:
                inherited.append(user)
        self._render_members(role, direct, inherited)

    def _render_members(self, role: str, direct: list[str], inherited: list[str]) -> None:
        tree = self.query_one("#me-result", Tree)
        tree.clear()
        total = len(direct) + len(inherited)
        if total == 0:
            tree.root.label = f"No users hold {role}"
            tree.root.expand()
            return
        tree.root.label = f"Users with {role} — {total} total"
        tree.root.expand()
        if direct:
            d = tree.root.add(f"Directly assigned ({len(direct)})", expand=True)
            for u in sorted(direct)[:50]: d.add_leaf(u)
            if len(direct) > 50:
                d.add_leaf(f"… and {len(direct) - 50} more")
        if inherited:
            i = tree.root.add(f"Inherited ({len(inherited)})", expand=False)
            for u in sorted(inherited)[:50]: i.add_leaf(u)
            if len(inherited) > 50:
                i.add_leaf(f"… and {len(inherited) - 50} more")

    # --- Tab 6: Path -------------------------------------------------

    def _run_path(self) -> None:
        if self.app.role_graph is None:
            self.app.notify("State still loading.", severity="warning")
            return
        from_role = self.query_one("#pa-from", Input).value.strip()
        to_role = self.query_one("#pa-to", Input).value.strip()
        if not from_role or not to_role:
            self.app.notify("Both 'from' and 'to' roles required.", severity="warning")
            return
        rg = self.app.role_graph
        ancestors = rg.all_ancestors(from_role)
        paths = rg.all_paths(from_role, to_role) if to_role in ancestors else []
        self._render_path(from_role, to_role, paths, inherits=to_role in ancestors)

    def _render_path(self, from_role: str, to_role: str, paths: list, inherits: bool) -> None:
        tree = self.query_one("#pa-result", Tree)
        tree.clear()
        if not inherits:
            tree.root.label = f"✗ {from_role} does NOT inherit from {to_role}"
            tree.root.expand()
            return
        tree.root.label = f"✓ {from_role} inherits from {to_role} — {len(paths)} path(s)"
        tree.root.expand()
        for i, chain in enumerate(paths[:30], 1):
            tree.root.add_leaf(f"Path {i}: {' → '.join(chain)}")
        if len(paths) > 30:
            tree.root.add_leaf(f"… and {len(paths) - 30} more")

    # --- Tab 7: Drift ------------------------------------------------

    def _run_drift(self) -> None:
        svc = self.app.access_service
        if svc is None:
            self.app.notify("State still loading.", severity="warning")
            return
        days_str = self.query_one("#dr-since", Select).value
        days = int(days_str) if days_str != "0" else None
        self.query_one("#dr-status", Static).update("Fetching drift… (Snowflake call)")
        self._drift_worker(days=days)

    @work(thread=True, exclusive=True, group="snowflake")
    def _drift_worker(self, *, days: int | None) -> None:
        try:
            result = self.app.access_service.detect_drift(days=days)
        except Exception as e:
            self.app.call_from_thread(self._drift_failed, e)
            return
        self.app.call_from_thread(self._render_drift, result)

    def _drift_failed(self, err: Exception) -> None:
        self.query_one("#dr-status", Static).update(f"Drift failed: {err}")
        self.app.notify(f"Drift failed: {err}", severity="error", timeout=8)

    def _render_drift(self, result: dict) -> None:
        if "error" in result:
            self.query_one("#dr-status", Static).update(result["error"])
            return
        self.query_one("#dr-status", Static).update(f"Changes since {result.get('since', '?')}")

        tree = self.query_one("#dr-result", Tree)
        tree.clear()
        tree.root.label = f"Drift since {result.get('since', '?')}"
        tree.root.expand()

        added = result.get("grants_added") or []
        revoked = result.get("grants_revoked") or []
        roles_added = result.get("roles_added") or {}
        roles_removed = result.get("roles_removed") or {}
        users_added = result.get("users_added") or {}
        users_removed = result.get("users_removed") or {}

        if added:
            n = tree.root.add(f"Grants added ({len(added)})", expand=True)
            for g in added[:30]:
                n.add_leaf(f"{g.get('privilege')} on {g.get('granted_on')} {g.get('fqn')} → {g.get('grantee')}")
            if len(added) > 30: n.add_leaf(f"… and {len(added) - 30} more")
        if revoked:
            n = tree.root.add(f"Grants revoked ({len(revoked)})", expand=True)
            for g in revoked[:30]:
                n.add_leaf(f"{g.get('privilege')} on {g.get('granted_on')} {g.get('fqn')} → {g.get('grantee')}")
            if len(revoked) > 30: n.add_leaf(f"… and {len(revoked) - 30} more")
        if roles_added:
            n = tree.root.add(f"Role-inheritance edges added ({len(roles_added)})", expand=False)
            for parent, children in list(roles_added.items())[:20]:
                for c in children: n.add_leaf(f"{parent} ← {c}")
        if roles_removed:
            n = tree.root.add(f"Role-inheritance edges removed ({len(roles_removed)})", expand=False)
            for parent, children in list(roles_removed.items())[:20]:
                for c in children: n.add_leaf(f"{parent} ← {c}")
        if users_added:
            n = tree.root.add(f"Users / role-grants added ({len(users_added)})", expand=False)
            for user, roles in list(users_added.items())[:20]:
                for r in roles: n.add_leaf(f"{user} got {r}")
        if users_removed:
            n = tree.root.add(f"Users / role-grants removed ({len(users_removed)})", expand=False)
            for user, roles in list(users_removed.items())[:20]:
                for r in roles: n.add_leaf(f"{user} lost {r}")

        if not any([added, revoked, roles_added, roles_removed, users_added, users_removed]):
            tree.root.add_leaf("No changes detected.")
