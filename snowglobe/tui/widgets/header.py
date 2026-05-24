"""Persistent header showing the app title, active profile/role, and cache freshness."""
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

from snowglobe.tui.widgets.cache_badge import CacheBadge


class SnowglobeHeader(Horizontal):
    """Top bar — title on the left, profile / role / cache on the right."""

    def compose(self) -> ComposeResult:
        yield Static("Snowglobe", classes="header-title")
        yield Static(self._profile_text(), classes="header-meta", id="header-profile")
        yield CacheBadge()

    def _profile_text(self) -> str:
        ctx = self.app.context
        profile = ctx.profile or {}
        role = profile.get("role", "—")
        return f"  ·  profile: {ctx.profile_name}  ·  role: {role}  ·  "
