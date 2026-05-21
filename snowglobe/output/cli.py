__all__ = [
    "format_json",
    "print_table",
    "format_access_text",
]
import pandas as pd

def format_json(explain: dict):
    from rich import print_json
    return print_json(data=explain)

def print_table(df: pd.DataFrame, title=None, no_wrap=True):
    from rich.table import Table
    from rich.console import Console

    console = Console()
    table = Table(title=title or "", header_style="bold cyan", row_styles=["none", "dim"])

    for col in df.columns:
        table.add_column(str(col), no_wrap=no_wrap, max_width=None if not no_wrap else 80)

    for row in df.itertuples(index=False):
        formatted_row = [
            str(cell).replace("\n", " ").replace("\r", " ") if no_wrap else str(cell)
            for cell in row
        ]
        table.add_row(*formatted_row)

    console.print(table)


def format_access_text(explain: dict) -> str:
    lines = []

    # Determine if this is a user or role query
    identity = explain.get("user") or explain.get("role")
    identity_type = "User" if "user" in explain else "Role"
    access_paths = explain.get("user_access_paths") or explain.get("role_access_paths") or {}
    has_privilege = explain.get("user_has_privilege") or explain.get("role_has_privilege", False)

    if not explain.get("object_exists"):
        lines.append(f"Object '{explain['object_name']}' not found in grants.")
        return "\n".join(lines)

    if has_privilege and access_paths:
        lines.append(f"{identity_type} '{identity}' CAN '{explain['privilege']}' on {explain['object_name']}")

        for privilege, chains in access_paths.items():
            lines.append(f"\nPrivilege: {privilege}")
            for i, chain in enumerate(chains, start=1):
                lines.append(f"  Path {i}: {' -> '.join(chain)}")

    else:
        lines.append(f"{identity_type} '{identity}' CANNOT '{explain['privilege']}' on {explain['object_name']}")
        if explain.get("roles_with_privilege"):
            lines.append("Roles with privilege:")
            for role in explain['roles_with_privilege']:
                lines.append(f"  - {role}")

    return "\n".join(lines)

def format_reverse_text(result: dict) -> str:
    lines = []
    obj_type = result["object_type"]
    obj_name = result["object_name"]

    if not result.get("object_exists"):
        lines.append(f"Object '{obj_name}' ({obj_type}) not found in grants.")
        return "\n".join(lines)

    privilege_filter = result.get("privilege_filter")
    if privilege_filter:
        lines.append(f"Who can '{privilege_filter}' on {obj_type} {obj_name}?")
    else:
        lines.append(f"Who can access {obj_type} {obj_name}?")

    privileges = result.get("privileges", {})
    if not privileges:
        lines.append("  No grants found.")
        return "\n".join(lines)

    for priv, info in privileges.items():
        direct_roles = info["direct_roles"]
        inherited_roles = info["inherited_roles"]
        users = info["users"]

        total_roles = len(direct_roles) + len(inherited_roles)
        lines.append(f"\n  {priv} ({total_roles} roles, {len(users)} users)")

        if direct_roles:
            lines.append(f"    Direct grants:")
            for r in direct_roles:
                lines.append(f"      - {r}")

        if inherited_roles:
            lines.append(f"    Inherited via role hierarchy ({len(inherited_roles)}):")
            for r in inherited_roles[:20]:
                lines.append(f"      - {r}")
            if len(inherited_roles) > 20:
                lines.append(f"      ... and {len(inherited_roles) - 20} more")

        if users:
            lines.append(f"    Users ({len(users)}):")
            for u in users[:30]:
                via = u["via_roles"][0] if len(u["via_roles"]) == 1 else f"{len(u['via_roles'])} roles"
                lines.append(f"      - {u['user']} (via {via})")
            if len(users) > 30:
                lines.append(f"      ... and {len(users) - 30} more")

    return "\n".join(lines)


def format_create_text(result: dict) -> str:
    lines = []
    identity = result["identity"]
    identity_type = result["identity_type"].capitalize()
    privilege = result["privilege"]
    scope = result.get("scope")

    if scope:
        # Scoped check — yes/no with role paths
        if result["has_access"]:
            lines.append(f"{identity_type} '{identity}' CAN '{privilege}' on {scope.upper()}")

            # Show which roles provide the access
            if result.get("account_wide"):
                lines.append(f"\n  Via account-wide grant:")
                for r in result.get("account_wide_roles", []):
                    lines.append(f"    - {r}")

            if result.get("databases"):
                lines.append(f"\n  Via database grant:")
                for d in result["databases"]:
                    roles = ", ".join(d["via_roles"])
                    lines.append(f"    - {d['name']} (via {roles})")

            if result.get("schemas"):
                lines.append(f"\n  Via schema grant:")
                for s in result["schemas"]:
                    roles = ", ".join(s["via_roles"])
                    lines.append(f"    - {s['name']} (via {roles})")

            # Show inheritance paths
            if result.get("access_paths"):
                lines.append(f"\n  Role inheritance paths:")
                for i, path in enumerate(result["access_paths"], 1):
                    lines.append(f"    Path {i}: {' -> '.join(path)}")

        else:
            lines.append(f"{identity_type} '{identity}' CANNOT '{privilege}' on {scope.upper()}")
    else:
        # Full scope breakdown (unscoped)
        if not result["has_access"]:
            lines.append(f"{identity_type} '{identity}' CANNOT '{privilege}' anywhere.")
            return "\n".join(lines)

        lines.append(f"{identity_type} '{identity}' CAN '{privilege}':")

        if result["account_wide"]:
            roles = ", ".join(result.get("account_wide_roles", []))
            lines.append(f"\n  Account-wide: Yes (via {roles})")
        else:
            lines.append(f"\n  Account-wide: No")

        if result["databases"]:
            lines.append(f"\n  Databases ({len(result['databases'])}):")
            for d in result["databases"]:
                roles = ", ".join(d["via_roles"])
                lines.append(f"    - {d['name']} (via {roles})")

        if result["schemas"]:
            lines.append(f"\n  Schemas ({len(result['schemas'])}):")
            for s in result["schemas"][:50]:
                roles = ", ".join(s["via_roles"])
                lines.append(f"    - {s['name']} (via {roles})")
            if len(result["schemas"]) > 50:
                lines.append(f"    ... and {len(result['schemas']) - 50} more")

    return "\n".join(lines)

def format_optimizer_suggestions(query_id, suggestions):

        output = f"\nQuery Optimization Suggestions for '{query_id}'.\n"
        output += "-" * 50 + "\n"

        if not suggestions:
            output += "No obvious improvements found.\n"
        else:
            for s in suggestions:
                output += f"• {s}\n"

        return output

def print_operator_tree(op_tree, scores=None):
    tree = op_tree["tree"]
    op_map = op_tree["op_map"]
    roots = op_tree["roots"]

    scores = scores or {}

    def _print(node_id, prefix="", is_last=True):

        if node_id == -1:
            print(f"{prefix}└── QueryPlan")

        else:
            op = op_map[node_id]
            connector = "└── " if is_last else "├── "

            score = scores.get(node_id, {}).get("score", 0)

            heat = ""
            if score > 200:
                heat = " 🔥"
            elif score > 50:
                heat = " ⚠"

            if score > 0:
                label = f"{op.operator_type} (step={op.step_id}, id={op.operator_id}, score={score:.1f}){heat}"
            else:
                label = f"{op.operator_type} (step={op.step_id}, id={op.operator_id})"

            print(f"{prefix}{connector}{label}")

        children = tree.get(node_id, [])

        for i, child_id in enumerate(children):
            last = i == len(children) - 1
            new_prefix = prefix + ("    " if is_last else "│   ")
            _print(child_id, new_prefix, last)

    # Virtual root
    tree[-1] = roots
    _print(-1)

def format_expensive_operators(expensive):

    output = "\nTop Expensive Operators\n"
    output += "-" * 50 + "\n"

    for i, op in enumerate(expensive, 1):

        scan = op.detail["scan_mb"]
        rows = op.detail["rows_m"]

        output += (
            f"{i}. {op.operator_type} (id={op.operator_id}) "
            f"[scan={scan:.1f}MB rows={rows:.1f}M]\n"
        )

    return output

def format_cost_attribution(results):

    output = "\nQuery Cost Breakdown\n"
    output += "-" * 50 + "\n\n"

    for r in results:

        output += f"{r['operator_type']:<18} {r['percent']:.1f}%\n"

    return output
