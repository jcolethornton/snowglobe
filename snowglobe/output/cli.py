__all__ = [
    "format_json",
    "print_table",
    "format_access_text",
    "format_query_insights",
    "format_drift_text",
    "format_user_report",
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

    # Columns that should never be truncated
    id_columns = {"QUERY_ID", "MV_NAME", "REPLICATION_GROUP_NAME"}

    for col in df.columns:
        col_str = str(col)
        if col_str.upper() in id_columns:
            table.add_column(col_str, no_wrap=True, overflow="fold")
        else:
            table.add_column(col_str, no_wrap=no_wrap, max_width=80 if no_wrap else None)

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
        time_str = f" time={op.time_pct:.0f}%" if op.time_pct > 0 else ""

        output += (
            f"{i}. {op.operator_type} (id={op.operator_id}) "
            f"[scan={scan:.1f}MB rows={rows:.1f}M{time_str}]\n"
        )

    return output

def format_cost_attribution(results):

    output = "\nQuery Cost Breakdown\n"
    output += "-" * 50 + "\n\n"

    for r in results:

        output += f"{r['operator_type']:<18} {r['percent']:.1f}%\n"

    return output


def format_query_insights(query_id, insights):
    """Format Snowflake-native query insights for display."""
    output = f"\nSnowflake Query Insights for '{query_id}'\n"
    output += "=" * 50 + "\n"

    if not insights:
        output += "  No insights available (may take up to 90 min after execution).\n"
        return output

    for insight in insights:
        topic = insight.get("topic", "UNKNOWN")
        type_id = insight.get("type_id", "")
        is_opp = insight.get("is_opportunity", False)
        marker = "!" if is_opp else "i"

        output += f"\n  [{marker}] {topic}: {type_id}\n"

        # Message is VARIANT — may be a dict or string
        message = insight.get("message")
        if isinstance(message, dict):
            msg_text = message.get("message", str(message))
        elif isinstance(message, str):
            msg_text = message
        else:
            msg_text = str(message) if message else ""
        if msg_text:
            output += f"      {msg_text}\n"

        # Suggestions is an ARRAY of strings
        suggestions = insight.get("suggestions")
        if suggestions:
            for s in suggestions:
                output += f"      -> {s}\n"

    output += "\n"
    return output


def format_drift_text(drift: dict) -> str:
    """Format access drift detection results."""
    if drift.get("error"):
        return f"  {drift['error']}"

    lines = [f"\nAccess Changes (since {drift['since']})", "=" * 50]

    grants_added = drift.get("grants_added", [])
    grants_revoked = drift.get("grants_revoked", [])
    roles_added = drift.get("roles_added", {})
    roles_removed = drift.get("roles_removed", {})
    users_added = drift.get("users_added", {})
    users_removed = drift.get("users_removed", {})

    total_changes = (
        len(grants_added) + len(grants_revoked)
        + sum(len(v) for v in roles_added.values())
        + sum(len(v) for v in roles_removed.values())
        + sum(len(v) for v in users_added.values())
        + sum(len(v) for v in users_removed.values())
    )

    if total_changes == 0:
        lines.append("\n  No access changes detected.")
        return "\n".join(lines)

    # Grant changes
    if grants_added:
        lines.append(f"\n  Grants Added ({len(grants_added)}):")
        for g in grants_added[:20]:
            lines.append(f"    + {g.get('grantee', '?')} : {g.get('privilege', '?')} on {g.get('fqn', '?')}")
        if len(grants_added) > 20:
            lines.append(f"    ... and {len(grants_added) - 20} more")

    if grants_revoked:
        lines.append(f"\n  Grants Revoked ({len(grants_revoked)}):")
        for g in grants_revoked[:20]:
            lines.append(f"    - {g.get('grantee', '?')} : {g.get('privilege', '?')} on {g.get('fqn', '?')}")
        if len(grants_revoked) > 20:
            lines.append(f"    ... and {len(grants_revoked) - 20} more")

    # Role hierarchy changes
    if roles_added:
        lines.append(f"\n  Role Grants Added:")
        for parent, children in list(roles_added.items())[:10]:
            for child in children:
                lines.append(f"    + {parent} granted USAGE on {child}")

    if roles_removed:
        lines.append(f"\n  Role Grants Revoked:")
        for parent, children in list(roles_removed.items())[:10]:
            for child in children:
                lines.append(f"    - {parent} lost USAGE on {child}")

    # User role changes
    if users_added:
        lines.append(f"\n  User Role Assignments Added:")
        for user, roles in list(users_added.items())[:10]:
            for role in roles:
                lines.append(f"    + {user} -> {role}")

    if users_removed:
        lines.append(f"\n  User Role Assignments Removed:")
        for user, roles in list(users_removed.items())[:10]:
            for role in roles:
                lines.append(f"    - {user} -x- {role}")

    lines.append("")
    return "\n".join(lines)


def format_user_report(report: dict) -> str:
    """Format a full user access report."""
    lines = []
    username = report["username"]

    lines.append(f"\nAccess Report: {username}")
    lines.append("=" * 50)

    # Roles
    lines.append(f"\n  Effective Roles: {report['role_count']}")
    lines.append(f"  Direct Roles: {', '.join(report['direct_roles'][:10])}")
    if report.get("excluded_roles"):
        lines.append(f"  Excluded: {', '.join(report['excluded_roles'])}")

    # Summary
    lines.append(f"\n  Total Accessible Objects: {report['total_objects']}")
    lines.append(f"  Total Grants: {report['total_grants']}")

    # By type
    summary = report.get("grant_summary", {})
    if summary:
        lines.append(f"\n  {'OBJECT TYPE':<25} {'OBJECTS':>8} {'PRIVILEGES'}")
        lines.append(f"  {'─' * 25} {'─' * 8} {'─' * 30}")
        for obj_type, info in sorted(summary.items(), key=lambda x: x[1]["object_count"], reverse=True):
            privs = ", ".join(info["privileges"][:5])
            lines.append(f"  {obj_type:<25} {info['object_count']:>8}  {privs}")

    lines.append("")
    return "\n".join(lines)
