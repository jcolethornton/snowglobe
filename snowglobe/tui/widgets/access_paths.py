"""Tree widget that renders the result of AccessService.inspect_access()."""
from typing import Any

from textual.widgets import Tree


class AccessPathsTree(Tree):
    """Visualises ✓/✗ verdict + role-inheritance paths from `inspect_access`."""

    def __init__(self, label: str = "Result", **kwargs: Any) -> None:
        super().__init__(label, **kwargs)
        self.show_root = True
        self.root.expand()

    def render_result(self, result: dict, identity: str) -> None:
        """Replace tree contents with the latest access-check outcome."""
        self.clear()

        if not result.get("object_exists"):
            self.root.label = "✗ Object not found in cached grants"
            self.root.expand()
            return

        priv = result.get("privilege", "?")
        obj = result.get("object_name", "?")
        has_access = (
            result.get("user_has_privilege")
            or result.get("role_has_privilege")
            or False
        )

        if not has_access:
            self.root.label = f"✗ {identity} has no {priv} on {obj}"
            self.root.expand()
            roles_with = result.get("roles_with_privilege", [])
            if roles_with:
                info = self.root.add(
                    f"Roles that DO have {priv} ({len(roles_with)})", expand=False
                )
                for r in sorted(set(roles_with))[:30]:
                    info.add_leaf(r)
                if len(set(roles_with)) > 30:
                    info.add_leaf(f"… and {len(set(roles_with)) - 30} more")
            return

        self.root.label = f"✓ {identity} has {priv} on {obj}"
        self.root.expand()

        paths_dict = (
            result.get("user_access_paths")
            or result.get("role_access_paths")
            or {}
        )
        if not paths_dict:
            self.root.add_leaf("(no inheritance paths returned)")
            return

        for privilege, chains in paths_dict.items():
            priv_node = self.root.add(
                f"{privilege} — {len(chains)} path(s)", expand=True
            )
            for i, chain in enumerate(chains, 1):
                priv_node.add_leaf(f"Path {i}: {' → '.join(chain)}")
