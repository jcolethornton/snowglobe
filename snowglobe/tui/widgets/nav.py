"""Left-side navigation sidebar — switches the active 'screen' via ContentSwitcher."""
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Label, ListItem, ListView


NAV_ITEMS: list[tuple[str, str]] = [
    ("home",    "Home"),
    ("access",  "Access"),
    ("risk",    "Risk"),
    ("cost",    "Cost"),
    ("tune",    "Tune"),
    ("reports", "Reports"),
    ("refresh", "Refresh"),
]


class NavSidebar(Vertical):
    """Vertical list of screen names. Selection fires app.action_switch(name)."""

    def compose(self) -> ComposeResult:
        items = [
            ListItem(Label(label), id=f"nav-{key}") for key, label in NAV_ITEMS
        ]
        yield ListView(*items, id="nav-list")

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        # Item id is "nav-<key>" — strip the prefix and switch screens.
        if event.item is None or event.item.id is None:
            return
        key = event.item.id.removeprefix("nav-")
        self.app.action_switch(key)
