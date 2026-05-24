"""
Snowglobe TUI — main app shell.

A persistent header / nav / footer plus seven content widgets swapped via a
ContentSwitcher. State (role graph, user graph, object index, AccessService
instance) is loaded once at startup in a background thread worker and
exposed as reactive attributes on the App for child widgets to watch.
"""
from datetime import datetime, timezone
from typing import Any

from textual import events, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.theme import Theme
from textual.widgets import ContentSwitcher, DataTable, Footer, Input, ListView, Tree


# --- Snowglobe themes ---------------------------------------------------------
# Two branded themes registered on the App. Ctrl-P → "Change theme" cycles
# through these plus Textual's built-ins (textual-dark, textual-light, monokai…).

_SNOWGLOBE_DARK = Theme(
    name="snowglobe-dark",
    primary="#009ED8",        # Hero Blue — buttons, borders, accents
    secondary="#003660",      # Deep Blue — header, nav, side panels
    accent="#FFC528",         # Yellow — highlights, stale-cache warnings
    foreground="#C1E0F4",     # Sky — primary text
    background="#0d1117",     # near-black main screen
    surface="#1D292E",        # slightly lifted (table backgrounds, inputs)
    panel="#003660",          # branded panel (= secondary in dark)
    warning="#FFC528",
    error="#E53935",
    success="#6EE7A7",
    dark=True,
    variables={
        "snowglobe-diff": "#FF7043",    # orange callout line
        "snowglobe-sky":  "#C1E0F4",
    },
)

_SNOWGLOBE_LIGHT = Theme(
    name="snowglobe-light",
    primary="#009ED8",
    secondary="#003660",
    accent="#FFC528",
    foreground="#003660",
    background="#FFFFFF",
    surface="#F5F8FA",
    panel="#C1E0F4",          # Sky as the panel background on light
    warning="#FF8A00",        # darker orange — Yellow disappears on white
    error="#E53935",
    success="#2E7D32",
    dark=False,
    variables={
        "snowglobe-diff": "#D84315",
        "snowglobe-sky":  "#003660",
    },
)

from snowglobe.cli.context import SnowglobeContext
from snowglobe.tui.widgets.header import SnowglobeHeader
from snowglobe.tui.widgets.nav import NavSidebar
from snowglobe.tui.screens.home import HomeScreen
from snowglobe.tui.screens.access import AccessScreen
from snowglobe.tui.screens.risk import RiskScreen
from snowglobe.tui.screens.cost import CostScreen
from snowglobe.tui.screens.tune import TuneScreen
from snowglobe.tui.screens.reports import ReportsScreen
from snowglobe.tui.screens.refresh import RefreshScreen


class SnowglobeApp(App):
    """Top-level Textual app for Snowglobe."""

    CSS_PATH = "styles.tcss"
    TITLE = "Snowglobe"

    BINDINGS = [
        ("1", "switch('home')",    "Home"),
        ("2", "switch('access')",  "Access"),
        ("3", "switch('risk')",    "Risk"),
        ("4", "switch('cost')",    "Cost"),
        ("5", "switch('tune')",    "Tune"),
        ("6", "switch('reports')", "Reports"),
        ("7", "switch('refresh')", "Refresh"),
        ("q", "quit", "Quit"),
    ]

    # Reactive global state — child widgets watch these.
    cache_age_minutes: reactive[int | None] = reactive(None)
    connection_ok: reactive[bool] = reactive(True)
    user_graph: reactive[Any | None] = reactive(None)
    role_graph: reactive[Any | None] = reactive(None)
    object_index: reactive[dict[str, list[str]] | None] = reactive(None)

    # Shared service instances.
    access_service: Any | None = None  # populated by _load_state_worker
    _cost_service: Any | None = None   # lazy

    def get_cost_service(self) -> Any:
        """Lazy singleton — CostService is cheap to construct but holds a session storage rate cache."""
        if self._cost_service is None:
            from snowglobe.core.cost_service import CostService
            self._cost_service = CostService(self.context)
        return self._cost_service

    def __init__(self, context: SnowglobeContext | None = None) -> None:
        super().__init__()
        # Themes must register BEFORE compose() runs, because styles.tcss
        # references variables defined on them (`$snowglobe-diff`).
        self.register_theme(_SNOWGLOBE_DARK)
        self.register_theme(_SNOWGLOBE_LIGHT)
        self.theme = "snowglobe-dark"

        self.context = context or SnowglobeContext()
        try:
            self.context.load_profile()
        except FileNotFoundError:
            # No config yet — surface in the header but don't crash the UI.
            self.context.profile = {}

    def compose(self) -> ComposeResult:
        yield SnowglobeHeader()
        with Horizontal(id="main"):
            yield NavSidebar()
            with ContentSwitcher(initial="home", id="content"):
                yield HomeScreen(id="home")
                yield AccessScreen(id="access")
                yield RiskScreen(id="risk")
                yield CostScreen(id="cost")
                yield TuneScreen(id="tune")
                yield ReportsScreen(id="reports")
                yield RefreshScreen(id="refresh")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_cache_age()
        self.set_interval(30.0, self._refresh_cache_age)
        self._load_state_worker()

    def action_switch(self, name: str) -> None:
        """Bound to number keys and called by the nav sidebar."""
        switcher = self.query_one(ContentSwitcher)
        switcher.current = name

    def _refresh_cache_age(self) -> None:
        """Read the latest refresh timestamp from SQLite and update the reactive."""
        try:
            from snowglobe.state.db import StateDB
            db = StateDB()
            refreshed_at = db.get_refreshed_at()
            if not refreshed_at:
                self.cache_age_minutes = None
                return
            refreshed = datetime.fromisoformat(refreshed_at)
            age = datetime.now(timezone.utc) - refreshed
            self.cache_age_minutes = int(age.total_seconds() / 60)
        except Exception:
            self.cache_age_minutes = None

    @work(thread=True, exclusive=True, group="state")
    def _load_state_worker(self) -> None:
        """Load role / user graphs + object index from SQLite into memory."""
        from snowglobe.core.access_service import AccessService, CallableRefreshProgress
        try:
            svc = AccessService(self.context)
            svc.setup_state()
            # Silent progress — staleness is conveyed by the header cache badge.
            silent = CallableRefreshProgress(lambda level, msg: None)
            svc.load_state(progress=silent)
        except Exception as e:
            self.call_from_thread(
                self.notify, f"Could not load state: {e}", severity="error", timeout=8
            )
            return
        self.call_from_thread(self._on_state_loaded, svc)

    def _on_state_loaded(self, svc: Any) -> None:
        self.access_service = svc
        self.user_graph = svc.user_graph
        self.role_graph = svc.role_graph
        self.object_index = svc.object_index
        users = len(svc.user_graph.assigned_roles) if svc.user_graph else 0
        roles = len(svc.role_graph.parents) if svc.role_graph else 0
        self.notify(f"State loaded — {users} users, {roles} roles.", timeout=3)


# --- Vim navigation overlay ---------------------------------------------------

_VIM_BINDINGS = [
    ("j",      "vim_down",      "↓"),
    ("k",      "vim_up",        "↑"),
    ("h",      "vim_collapse",  "←/collapse"),
    ("l",      "vim_expand",    "→/expand"),
    ("g",      "vim_top",       "top"),
    ("G",      "vim_bottom",    "bottom"),
    ("ctrl+d", "vim_page_down", "½↓"),
    ("ctrl+u", "vim_page_up",   "½↑"),
]


class VimSnowglobeApp(SnowglobeApp):
    """SnowglobeApp variant with vim-style navigation.

    Active bindings (in addition to the base 1-7 / q):
      j / k         cursor down / up    (ListView, DataTable, Tree)
      h / l         collapse / expand   (Tree nodes)
      g / G         top / bottom        (lists, tables)
      Ctrl-d / -u   half-page down/up   (any scrollable)
      Esc          blur the focused Input → j/k now navigate again

    Keys do nothing when an `Input` has focus, because `Input` consumes
    character keypresses before they reach app-level bindings — so typing
    'j' into a username field works normally.
    """

    BINDINGS = SnowglobeApp.BINDINGS + _VIM_BINDINGS

    # --- Cursor movement ---------------------------------------------

    def action_vim_down(self) -> None:
        focused = self.focused
        if focused is not None and hasattr(focused, "action_cursor_down"):
            focused.action_cursor_down()

    def action_vim_up(self) -> None:
        focused = self.focused
        if focused is not None and hasattr(focused, "action_cursor_up"):
            focused.action_cursor_up()

    def action_vim_top(self) -> None:
        focused = self.focused
        if focused is None:
            return
        if isinstance(focused, ListView) and len(focused.children) > 0:
            focused.index = 0
        elif isinstance(focused, DataTable) and focused.row_count > 0:
            focused.move_cursor(row=0)
        elif isinstance(focused, Tree):
            focused.select_node(focused.root)
        elif hasattr(focused, "scroll_home"):
            focused.scroll_home(animate=False)

    def action_vim_bottom(self) -> None:
        focused = self.focused
        if focused is None:
            return
        if isinstance(focused, ListView):
            n = len(focused.children)
            if n > 0:
                focused.index = n - 1
        elif isinstance(focused, DataTable) and focused.row_count > 0:
            focused.move_cursor(row=focused.row_count - 1)
        elif hasattr(focused, "scroll_end"):
            focused.scroll_end(animate=False)

    def action_vim_page_down(self) -> None:
        focused = self.focused
        if focused is None:
            return
        if hasattr(focused, "action_page_down"):
            focused.action_page_down()
        elif hasattr(focused, "scroll_page_down"):
            focused.scroll_page_down(animate=False)

    def action_vim_page_up(self) -> None:
        focused = self.focused
        if focused is None:
            return
        if hasattr(focused, "action_page_up"):
            focused.action_page_up()
        elif hasattr(focused, "scroll_page_up"):
            focused.scroll_page_up(animate=False)

    # --- Tree fold/unfold --------------------------------------------

    def action_vim_expand(self) -> None:
        from textual.widgets import Tree
        if isinstance(self.focused, Tree):
            node = self.focused.cursor_node
            if node is not None:
                node.expand()

    def action_vim_collapse(self) -> None:
        from textual.widgets import Tree
        if isinstance(self.focused, Tree):
            node = self.focused.cursor_node
            if node is not None and node.is_expanded:
                node.collapse()

    # --- Esc blurs Inputs --------------------------------------------

    def on_key(self, event: events.Key) -> None:
        """Esc on a focused Input drops focus so j/k navigate again."""
        if event.key == "escape" and isinstance(self.focused, Input):
            self.set_focus(None)
            event.stop()
