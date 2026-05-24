"""Cache-age indicator. Reads `cache_age_minutes` from the App."""
from textual.widgets import Static


class CacheBadge(Static):
    """One-line status pill: 'cache: 4m ago' / 'cache: 3h ago' / 'cache: missing'."""

    def on_mount(self) -> None:
        # Watch the app-level reactive so this widget updates automatically.
        self.watch(self.app, "cache_age_minutes", self._refresh)
        self._refresh(self.app.cache_age_minutes)

    def _refresh(self, age: int | None) -> None:
        self.remove_class("fresh", "stale", "missing")
        if age is None:
            self.add_class("missing")
            self.update("cache: missing")
            return
        if age < 60:
            self.add_class("fresh")
            self.update(f"cache: {age}m ago")
            return
        if age < 24 * 60:
            self.add_class("stale")
            self.update(f"cache: {age // 60}h ago")
            return
        self.add_class("missing")
        self.update(f"cache: {age // (24 * 60)}d ago")
