import typer
import pandas as pd
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import FuzzyCompleter
from snowglobe.cli.shell_completer import SnowglobeCompleter
from snowglobe.cli.context import SnowglobeContext
from snowglobe.core.access_service import AccessService
from snowglobe.core.optimizer import QueryOptimizerService
from snowglobe.output import cli


def start_shell(ctx: SnowglobeContext):
    """Start the interactive Snowglobe shell."""

    # Preload access graphs for completions and stateful queries
    access_service = AccessService(ctx)
    ctx.user_graph, ctx.role_graph, ctx.object_index = access_service.get_graphs()

    session = PromptSession(
        completer=FuzzyCompleter(SnowglobeCompleter(ctx))
    )

    typer.echo("Snowglobe Interactive Shell")
    typer.echo("Type 'check' to get started, or 'help' for all commands.\n")

    while True:
        try:
            active = ctx.target_role or ctx.username or ""
            prompt_label = f"snowglobe[{active}]> " if active else "snowglobe> "
            text = session.prompt(prompt_label).strip()

            if not text:
                continue

            if text in {"exit", "quit"}:
                break

            _dispatch(text, ctx)

        except KeyboardInterrupt:
            continue
        except EOFError:
            break


def _dispatch(text: str, ctx: SnowglobeContext):
    """Route shell input to the appropriate handler."""
    parts = text.split()
    cmd = parts[0]
    args = parts[1:]

    handlers = {
        "check": _cmd_check,
        "roles": _cmd_roles,
        "members": _cmd_members,
        "path": _cmd_path,
        "escalation": _cmd_escalation,
        "scan": _cmd_scan,
        "use": _cmd_use,
        "set": _cmd_set,
        "access": _cmd_access,
        "whoaccess": _cmd_whoaccess,
        "create": _cmd_create,
        "cost": _cmd_cost,
        "optimize": _cmd_optimize,
        "drift": _cmd_drift,
        "unused": _cmd_unused,
        "report": _cmd_report,
        "refresh": _cmd_refresh,
        "status": _cmd_status,
        "debug": _cmd_debug,
        "help": _cmd_help,
        "?": _cmd_help,
    }

    handler = handlers.get(cmd)
    if handler:
        handler(ctx, args)
    else:
        typer.secho(f"Unknown command: {cmd}. Type 'help' for available commands.", fg=typer.colors.YELLOW)


# --- Shell commands ---

def _cmd_check(ctx: SnowglobeContext, args: list):
    """Guided wizard for access and privilege checks."""
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import WordCompleter, FuzzyCompleter

    typer.echo("")
    typer.secho("What would you like to check?", fg=typer.colors.CYAN, bold=True)
    typer.echo("  [1] Can a user/role access an object?")
    typer.echo("  [2] Who can access an object?")
    typer.echo("  [3] Where can a role create objects?")
    typer.echo("  [4] What roles does a user have?")
    typer.echo("  [5] Who has a specific role?")
    typer.echo("  [6] Does one role inherit from another?")
    typer.echo("  [7] Can a role escalate to admin privileges?")
    typer.echo("")

    session = PromptSession()
    choice = session.prompt(
        "Choice (1-7): ",
        completer=WordCompleter(["1", "2", "3", "4", "5", "6", "7"]),
    ).strip()

    if choice == "1":
        # Clear object state so user gets prompted fresh
        ctx.object_type = None
        ctx.object_name = None
        ctx.privilege = None
        _cmd_access(ctx, args)
    elif choice == "2":
        _cmd_whoaccess(ctx, args)
    elif choice == "3":
        _cmd_create(ctx, args)
    elif choice == "4":
        _cmd_roles(ctx, args)
    elif choice == "5":
        _cmd_members(ctx, args)
    elif choice == "6":
        _cmd_path(ctx, args)
    elif choice == "7":
        _cmd_escalation(ctx, args)
    else:
        typer.secho("Invalid choice. Please enter 1-7.", fg=typer.colors.YELLOW)

def _cmd_use(ctx: SnowglobeContext, args: list):
    """Set the active user or role for subsequent queries."""
    if len(args) < 2:
        typer.echo("Usage: use role <name> | use user <name>")
        return

    kind, name = args[0], args[1]

    if kind == "role":
        ctx.target_role = name
        ctx.username = None
        typer.secho(f"Using role: {name}", fg=typer.colors.GREEN)
    elif kind == "user":
        ctx.username = name
        ctx.target_role = None
        typer.secho(f"Using user: {name}", fg=typer.colors.GREEN)
    else:
        typer.echo("Usage: use role <name> | use user <name>")


def _cmd_set(ctx: SnowglobeContext, args: list):
    """Set a working state field."""
    if len(args) < 2:
        typer.echo("Usage: set <field> <value>")
        typer.echo("Fields: object_type, object_name, privilege")
        return

    field, value = args[0], " ".join(args[1:])
    valid_fields = {"object_type", "object_name", "privilege"}

    if field not in valid_fields:
        typer.secho(f"Unknown field: {field}. Valid: {', '.join(valid_fields)}", fg=typer.colors.YELLOW)
        return

    setattr(ctx, field, value)
    typer.secho(f"{field} = {value}", fg=typer.colors.GREEN)


def _cmd_access(ctx: SnowglobeContext, args: list):
    """Run access check using current shell state. Prompts for missing fields."""
    from snowglobe.cli.prompts import resolve_access_inputs

    # Resolve missing inputs with interactive prompts + fuzzy completion
    resolved = resolve_access_inputs(
        username=ctx.username,
        role=ctx.target_role,
        object_type=ctx.object_type,
        object_name=ctx.object_name,
        privilege=ctx.privilege,
        user_graph=ctx.user_graph,
        role_graph=ctx.role_graph,
        grants=[],
        object_index=ctx.object_index,
    )

    # Update context state with resolved values for next time
    ctx.username = resolved.get("username")
    ctx.target_role = resolved.get("role")
    ctx.object_type = resolved.get("object_type")
    ctx.object_name = resolved.get("object_name")
    ctx.privilege = resolved.get("privilege")

    access_service = AccessService(ctx)

    try:
        result = access_service.inspect_access(
            username=resolved["username"],
            role=resolved["role"],
            object_type=resolved["object_type"],
            object_name=resolved["object_name"],
            privilege=resolved["privilege"],
            ignore_excluded_roles=False,
            refresh_state=False,
        )
        typer.echo(cli.format_access_text(result))
    except SystemExit:
        pass
    except Exception as e:
        typer.secho(f"Error: {e}", fg=typer.colors.RED)


def _cmd_whoaccess(ctx: SnowglobeContext, args: list):
    """Reverse lookup: who can access this object? Prompts for object details."""
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import WordCompleter, FuzzyCompleter
    from snowglobe.models.object_type import ObjectType

    session = PromptSession()

    # Parse args: whoaccess [--privilege PRIV]
    privilege = None
    for i, arg in enumerate(args):
        if arg == "--privilege" and i + 1 < len(args):
            privilege = args[i + 1].upper()

    # Prompt for object type
    object_type = ctx.object_type
    if not object_type:
        items = [ot.value for ot in ObjectType]
        word = WordCompleter(items, ignore_case=True)
        fuzzy = FuzzyCompleter(word)
        object_type = session.prompt(
            "Object type: ",
            completer=fuzzy,
            complete_while_typing=True,
        ).strip().upper()

    if not object_type:
        typer.secho("Object type required.", fg=typer.colors.RED)
        return

    # Prompt for object name with FQN completions
    object_name = ctx.object_name
    if not object_name:
        obj_items = []
        if ctx.object_index and object_type in ctx.object_index:
            obj_items = ctx.object_index[object_type]
        word = WordCompleter(obj_items, ignore_case=True, sentence=True)
        fuzzy = FuzzyCompleter(word)
        object_name = session.prompt(
            "Object name (FQN): ",
            completer=fuzzy,
            complete_while_typing=True,
        ).strip()

    if not object_name:
        typer.secho("Object name required.", fg=typer.colors.RED)
        return

    # Run the reverse lookup
    access_service = AccessService(ctx)
    try:
        result = access_service.inspect_reverse(
            object_type=object_type,
            object_name=object_name,
            privilege=privilege,
        )
        typer.echo(cli.format_reverse_text(result))

        # Drill-down: select a role to see its full grants
        privileges_result = result.get("privileges", {})
        if privileges_result:
            all_roles = set()
            for priv_info in privileges_result.values():
                all_roles.update(priv_info.get("direct_roles", []))
            all_roles = sorted(all_roles)
            if all_roles:
                selected = _drill_down_prompt(all_roles, "Inspect role's grants")
                if selected:
                    typer.echo(f"\n  Fetching grants for {selected}...")
                    grant_rows = access_service.db.query_grants_by_grantees({selected})
                    if grant_rows:
                        import pandas as pd_local
                        grant_df = pd_local.DataFrame(grant_rows)[["privilege", "granted_on", "fqn"]]
                        grant_df.columns = ["PRIVILEGE", "OBJECT_TYPE", "OBJECT"]
                        cli.print_table(grant_df, title=f"Grants for {selected}")
                    else:
                        typer.echo(f"  No grants found for {selected}.")
    except Exception as e:
        typer.secho(f"Error: {e}", fg=typer.colors.RED)


def _cmd_create(ctx: SnowglobeContext, args: list):
    """Check CREATE privileges for the active role/user."""
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import WordCompleter, FuzzyCompleter

    CREATE_PRIVILEGES = [
        "CREATE TABLE", "CREATE VIEW", "CREATE SCHEMA", "CREATE DATABASE",
        "CREATE DYNAMIC TABLE", "CREATE STREAMLIT", "CREATE NOTEBOOK",
        "CREATE STAGE", "CREATE STREAM", "CREATE PIPE", "CREATE TASK",
        "CREATE FUNCTION", "CREATE PROCEDURE", "CREATE ALERT",
        "CREATE FILE FORMAT", "CREATE SEQUENCE", "CREATE TAG",
        "CREATE SECRET", "CREATE WAREHOUSE", "CREATE ROLE",
        "CREATE MATERIALIZED VIEW", "CREATE EXTERNAL TABLE",
        "CREATE ICEBERG TABLE", "CREATE MODEL", "CREATE AGENT",
    ]

    session = PromptSession()

    # Resolve role/user — use current context or prompt
    role = ctx.target_role
    username = ctx.username

    if not role and not username:
        # Prompt for inspect type
        items = list(ctx.role_graph.roles.keys()) if ctx.role_graph else []
        word = WordCompleter(items, ignore_case=True)
        fuzzy = FuzzyCompleter(word)
        role = session.prompt(
            "Role: ",
            completer=fuzzy,
            complete_while_typing=True,
        ).strip()
        if not role:
            typer.secho("Role required.", fg=typer.colors.RED)
            return

    # Prompt for CREATE privilege
    privilege = None
    if args:
        privilege = " ".join(args).upper()

    if not privilege:
        word = WordCompleter(CREATE_PRIVILEGES, ignore_case=True)
        fuzzy = FuzzyCompleter(word)
        privilege = session.prompt(
            "CREATE privilege: ",
            completer=fuzzy,
            complete_while_typing=True,
        ).strip().upper()

    if not privilege:
        typer.secho("Privilege required.", fg=typer.colors.RED)
        return

    # Optional scope — offer databases and schemas from the object index
    scope_items = []
    if ctx.object_index:
        scope_items.extend(ctx.object_index.get("DATABASE", []))
        scope_items.extend(ctx.object_index.get("SCHEMA", []))
    scope_word = WordCompleter(sorted(set(scope_items)), ignore_case=True)
    scope_fuzzy = FuzzyCompleter(scope_word)
    scope = session.prompt(
        "Scope (DB or DB.SCHEMA, blank for all): ",
        completer=scope_fuzzy,
        complete_while_typing=True,
    ).strip() or None

    # Run the check
    access_service = AccessService(ctx)
    try:
        result = access_service.inspect_create(
            username=username,
            role=role,
            privilege=privilege,
            scope=scope,
        )
        typer.echo(cli.format_create_text(result))
    except SystemExit:
        pass
    except Exception as e:
        typer.secho(f"Error: {e}", fg=typer.colors.RED)


def _cmd_roles(ctx: SnowglobeContext, args: list):
    """Show all roles a user has (direct + inherited)."""
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import WordCompleter, FuzzyCompleter

    session = PromptSession()

    # Prompt for username
    username = args[0] if args else None
    if not username:
        items = list(ctx.user_graph.assigned_roles.keys())
        word = WordCompleter(items, ignore_case=True)
        fuzzy = FuzzyCompleter(word)
        username = session.prompt(
            "User: ",
            completer=fuzzy,
            complete_while_typing=True,
        ).strip()

    if not username:
        typer.secho("Username required.", fg=typer.colors.RED)
        return

    if username not in ctx.user_graph.assigned_roles:
        typer.secho(f"User '{username}' not found.", fg=typer.colors.RED)
        return

    # Direct roles
    direct_roles, excluded = ctx.user_graph.roles_of(username)
    effective = ctx.user_graph.effective_roles(username, ctx.role_graph)

    typer.echo("")
    typer.secho(f"Roles for user: {username}", fg=typer.colors.CYAN, bold=True)
    typer.echo("")

    typer.secho(f"  Direct roles ({len(direct_roles)}):", fg=typer.colors.GREEN)
    for r in sorted(direct_roles):
        typer.echo(f"    {r}")

    if excluded:
        typer.secho(f"\n  Excluded roles ({len(excluded)}):", fg=typer.colors.YELLOW)
        for r in sorted(excluded):
            typer.echo(f"    {r}")

    inherited = effective - set(direct_roles) - set(excluded)
    if inherited:
        typer.secho(f"\n  Inherited roles ({len(inherited)}):", fg=typer.colors.GREEN)
        for r in sorted(inherited)[:30]:
            typer.echo(f"    {r}")
        if len(inherited) > 30:
            typer.echo(f"    ... and {len(inherited) - 30} more")

    typer.echo(f"\n  Total effective: {len(effective)} roles")


def _cmd_members(ctx: SnowglobeContext, args: list):
    """Show all users who have a specific role (direct assignment)."""
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import WordCompleter, FuzzyCompleter

    session = PromptSession()

    # Prompt for role
    role = args[0] if args else None
    if not role:
        items = list(ctx.role_graph.roles.keys())
        word = WordCompleter(items, ignore_case=True)
        fuzzy = FuzzyCompleter(word)
        role = session.prompt(
            "Role: ",
            completer=fuzzy,
            complete_while_typing=True,
        ).strip()

    if not role:
        typer.secho("Role required.", fg=typer.colors.RED)
        return

    # Find users with this role (directly assigned)
    direct_users = []
    for user, assigned in ctx.user_graph.assigned_roles.items():
        if role in assigned:
            direct_users.append(user)

    # Find users who inherit this role
    inherited_users = []
    for user, assigned in ctx.user_graph.assigned_roles.items():
        if user in direct_users:
            continue
        effective = set(assigned)
        for r in assigned:
            effective |= ctx.role_graph.all_ancestors(r)
        if role in effective:
            inherited_users.append(user)

    typer.echo("")
    typer.secho(f"Users with role: {role}", fg=typer.colors.CYAN, bold=True)
    typer.echo("")

    if direct_users:
        typer.secho(f"  Directly assigned ({len(direct_users)}):", fg=typer.colors.GREEN)
        for u in sorted(direct_users):
            typer.echo(f"    {u}")
    else:
        typer.echo("  No users directly assigned.")

    if inherited_users:
        typer.secho(f"\n  Inherited ({len(inherited_users)}):", fg=typer.colors.GREEN)
        for u in sorted(inherited_users)[:30]:
            typer.echo(f"    {u}")
        if len(inherited_users) > 30:
            typer.echo(f"    ... and {len(inherited_users) - 30} more")

    total = len(direct_users) + len(inherited_users)
    typer.echo(f"\n  Total: {total} users")


def _cmd_path(ctx: SnowglobeContext, args: list):
    """Check if one role inherits from another and show the path."""
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import WordCompleter, FuzzyCompleter

    session = PromptSession()
    items = list(ctx.role_graph.roles.keys())
    word = WordCompleter(items, ignore_case=True)
    fuzzy = FuzzyCompleter(word)

    # Prompt for source role
    from_role = args[0] if len(args) > 0 else None
    if not from_role:
        from_role = session.prompt(
            "From role: ",
            completer=fuzzy,
            complete_while_typing=True,
        ).strip()

    if not from_role:
        typer.secho("From role required.", fg=typer.colors.RED)
        return

    # Prompt for target role
    to_role = args[1] if len(args) > 1 else None
    if not to_role:
        to_role = session.prompt(
            "To role: ",
            completer=fuzzy,
            complete_while_typing=True,
        ).strip()

    if not to_role:
        typer.secho("To role required.", fg=typer.colors.RED)
        return

    # Check if to_role is in from_role's ancestors
    ancestors = ctx.role_graph.all_ancestors(from_role)
    if to_role not in ancestors:
        typer.echo("")
        typer.secho(f"  {from_role} does NOT inherit from {to_role}", fg=typer.colors.RED)
        return

    # Find all paths
    paths = ctx.role_graph.all_paths(from_role, to_role)

    typer.echo("")
    typer.secho(f"  {from_role} DOES inherit from {to_role}", fg=typer.colors.GREEN, bold=True)
    typer.echo("")

    if paths:
        typer.secho(f"  Inheritance paths ({len(paths)}):", fg=typer.colors.CYAN)
        for i, path in enumerate(paths[:10], 1):
            typer.echo(f"    Path {i}: {' -> '.join(path)}")
        if len(paths) > 10:
            typer.echo(f"    ... and {len(paths) - 10} more paths")


# Privileged target roles (escalation endpoints)
_PRIVILEGED_ROLES = {
    "ACCOUNT_ROLE::ACCOUNTADMIN",
    "ACCOUNT_ROLE::SYSADMIN",
    "ACCOUNT_ROLE::SECURITYADMIN",
    "ACCOUNT_ROLE::USERADMIN",
}


def _get_privileged_targets(ctx: SnowglobeContext) -> set:
    """Get all privileged roles — built-in admins + roles with dangerous account privileges."""
    targets = set(_PRIVILEGED_ROLES)
    # Also include roles with MANAGE GRANTS / CREATE ROLE / CREATE USER from the grants DB
    from snowglobe.state.db import StateDB
    db = StateDB()
    rows = db.conn.execute(
        """SELECT DISTINCT grantee FROM grants
           WHERE privilege IN ('MANAGE GRANTS', 'CREATE ROLE', 'CREATE USER')
           AND granted_on = 'ACCOUNT'"""
    ).fetchall()
    for row in rows:
        targets.add(row["grantee"])
    return targets


def _cmd_escalation(ctx: SnowglobeContext, args: list):
    """Check if a role can reach admin privileges via inheritance."""
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import WordCompleter, FuzzyCompleter

    session = PromptSession()

    # Prompt for role
    role = args[0] if args else None
    if not role:
        items = list(ctx.role_graph.roles.keys())
        word = WordCompleter(items, ignore_case=True)
        fuzzy = FuzzyCompleter(word)
        role = session.prompt(
            "Role to check: ",
            completer=fuzzy,
            complete_while_typing=True,
        ).strip()

    if not role:
        typer.secho("Role required.", fg=typer.colors.RED)
        return

    targets = _get_privileged_targets(ctx)

    # Check if the role itself IS a privileged role
    if role in targets:
        typer.echo("")
        typer.secho(f"  {role} IS a privileged role.", fg=typer.colors.YELLOW, bold=True)
        return

    # Find which privileged targets are reachable
    ancestors = ctx.role_graph.all_ancestors(role)
    reachable = ancestors & targets

    typer.echo("")
    if not reachable:
        typer.secho(f"  {role} has NO escalation path to admin roles.", fg=typer.colors.GREEN, bold=True)
        typer.echo("  This role cannot reach ACCOUNTADMIN, SYSADMIN, SECURITYADMIN, or any role with MANAGE GRANTS.")
        return

    typer.secho(f"  {role} can reach {len(reachable)} privileged role(s):", fg=typer.colors.RED, bold=True)
    typer.echo("")

    # Show shortest path to each reachable target
    for target in sorted(reachable):
        path = ctx.role_graph.shortest_path(role, target)
        if path:
            hops = len(path) - 1
            color = typer.colors.RED if hops <= 3 else typer.colors.YELLOW
            typer.secho(f"  → {target} ({hops} hops)", fg=color)
            typer.echo(f"    {' → '.join(path)}")
            typer.echo("")

    # Show affected users — who has this role (directly or inherited)?
    direct_users = []
    inherited_users = []
    for user, assigned in ctx.user_graph.assigned_roles.items():
        if role in assigned:
            direct_users.append(user)
        else:
            effective = set(assigned)
            for r in assigned:
                effective |= ctx.role_graph.all_ancestors(r)
            if role in effective:
                inherited_users.append(user)

    total_users = len(direct_users) + len(inherited_users)
    if total_users > 0:
        typer.secho(f"  Users who can escalate via this role ({total_users}):", fg=typer.colors.CYAN)
        if direct_users:
            for u in sorted(direct_users):
                typer.echo(f"    {u} (directly assigned)")
        if inherited_users:
            for u in sorted(inherited_users)[:20]:
                typer.echo(f"    {u} (inherited)")
            if len(inherited_users) > 20:
                typer.echo(f"    ... and {len(inherited_users) - 20} more")
    else:
        typer.echo("  No users currently hold this role.")


def _cmd_scan(ctx: SnowglobeContext, args: list):
    """Scan all roles for privilege escalation paths to admin roles."""
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import WordCompleter

    targets = _get_privileged_targets(ctx)
    all_roles = ctx.role_graph.all_roles()

    # Classify roles
    short_paths = []  # ≤3 hops (risky)
    medium_paths = []  # 4-5 hops
    no_path = []
    is_admin = []

    typer.echo("")
    typer.secho("Privilege Escalation Scan", fg=typer.colors.CYAN, bold=True)
    typer.echo("─" * 50)
    typer.echo(f"Scanning {len(all_roles)} roles against {len(targets)} privileged targets...")
    typer.echo("")

    for role in sorted(all_roles):
        if role in targets:
            is_admin.append(role)
            continue

        ancestors = ctx.role_graph.all_ancestors(role)
        reachable = ancestors & targets

        if not reachable:
            no_path.append(role)
            continue

        # Find shortest path to any target
        best_path = None
        best_target = None
        for target in reachable:
            path = ctx.role_graph.shortest_path(role, target)
            if path and (best_path is None or len(path) < len(best_path)):
                best_path = path
                best_target = target

        if best_path:
            hops = len(best_path) - 1
            entry = {"role": role, "target": best_target, "hops": hops, "path": best_path}
            if hops <= 3:
                short_paths.append(entry)
            elif hops <= 5:
                medium_paths.append(entry)

    # Output results
    flagged = sorted(short_paths + medium_paths, key=lambda e: e["hops"])

    # Compute user counts for each flagged role
    for entry in flagged:
        role = entry["role"]
        count = 0
        for user, assigned in ctx.user_graph.assigned_roles.items():
            if role in assigned:
                count += 1
            else:
                effective = set(assigned)
                for r in assigned:
                    effective |= ctx.role_graph.all_ancestors(r)
                if role in effective:
                    count += 1
        entry["user_count"] = count

    if short_paths:
        typer.secho(f"HIGH RISK — {len(short_paths)} roles with short paths (≤3 hops):", fg=typer.colors.RED, bold=True)
        typer.echo("")
        for i, entry in enumerate(sorted(short_paths, key=lambda e: e["hops"]), 1):
            typer.secho(f"  [{i}] {entry['role']} → {entry['target']} ({entry['hops']} hops, {entry['user_count']} users)", fg=typer.colors.RED)
            typer.echo(f"      {' → '.join(entry['path'])}")
        typer.echo("")

    if medium_paths:
        offset = len(short_paths)
        typer.secho(f"MEDIUM — {len(medium_paths)} roles with moderate paths (4-5 hops):", fg=typer.colors.YELLOW)
        typer.echo("")
        for i, entry in enumerate(sorted(medium_paths, key=lambda e: e["hops"]), offset + 1):
            typer.echo(f"  [{i}] {entry['role']} → {entry['target']} ({entry['hops']} hops, {entry['user_count']} users)")
        typer.echo("")

    # Summary
    typer.secho("Summary:", fg=typer.colors.CYAN)
    typer.echo(f"  Privileged roles (admin):              {len(is_admin)}")
    typer.echo(f"  Roles with short paths (≤3, review):   {len(short_paths)}")
    typer.echo(f"  Roles with moderate paths (4-5):       {len(medium_paths)}")
    typer.echo(f"  Roles with no escalation path:         {len(no_path)}")
    typer.echo(f"  Total roles scanned:                   {len(all_roles)}")

    # Offer drill-down if there are flagged roles
    if flagged:
        typer.echo("")
        session = PromptSession()
        choices = [str(i) for i in range(1, len(flagged) + 1)]
        choice = session.prompt(
            "Drill into a role (number) or press Enter to skip: ",
            completer=WordCompleter(choices),
        ).strip()

        if choice and choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(flagged):
                selected_role = flagged[idx]["role"]
                typer.echo("")
                _cmd_escalation(ctx, [selected_role])


def _cmd_cost(ctx: SnowglobeContext, args: list):
    """Cost analysis wizard — or use subcommands: cost summary|warehouses|users|ai|ai-users|services|queries"""
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import WordCompleter
    from snowglobe.core.cost_service import CostService

    cost_service = CostService(ctx)

    # Parse common flags from args
    days = 30
    csv_path = None
    refresh = False
    sub_args = args[1:] if args else []
    for i, a in enumerate(sub_args):
        if a == "--days" and i + 1 < len(sub_args):
            days = int(sub_args[i + 1])
        elif a == "--csv" and i + 1 < len(sub_args):
            csv_path = sub_args[i + 1]
        elif a == "--refresh":
            refresh = True

    # If a subcommand is given directly, route to it
    if args:
        sub = args[0].lower()

        if sub == "summary":
            _cost_summary(cost_service, days, csv_path, refresh)
        elif sub == "warehouses":
            _cost_warehouses(cost_service, days, csv_path, refresh)
        elif sub == "users":
            _cost_users(cost_service, min(days, 7), csv_path, refresh)
        elif sub == "ai":
            _cost_ai(cost_service, days, csv_path, refresh)
        elif sub == "ai-users":
            _cost_ai_users(cost_service, days, csv_path, refresh)
        elif sub == "services":
            _cost_services(cost_service, days, csv_path, refresh)
        elif sub == "queries":
            _cost_queries(cost_service, min(days, 7), csv_path, refresh)
        elif sub == "trend":
            _cost_trend(cost_service, days, csv_path, refresh)
        elif sub == "storage":
            _cost_storage(cost_service, days, csv_path, refresh)
        elif sub == "budget":
            _cost_budget(cost_service, csv_path)
        elif sub == "replication":
            _cost_replication(cost_service, days, csv_path, refresh)
        elif sub in ("materialized-views", "mv"):
            _cost_materialized_views(cost_service, days, csv_path, refresh)
        else:
            typer.secho(f"Unknown subcommand: {sub}. Use: summary, warehouses, users, ai, ai-users, services, queries, trend, storage, budget, replication, mv", fg=typer.colors.YELLOW)
        return

    # Interactive wizard
    typer.echo("")
    typer.secho("Cost Analysis", fg=typer.colors.CYAN, bold=True)
    typer.echo("  [1]  Account summary — total spend by service type")
    typer.echo("  [2]  Warehouse breakdown — cost per warehouse")
    typer.echo("  [3]  User breakdown — all costs per user (warehouse + AI)")
    typer.echo("  [4]  AI services — token costs by service type")
    typer.echo("  [5]  AI by user — token costs per user per service")
    typer.echo("  [6]  Services breakdown — pipes, tasks, SPCS, clustering")
    typer.echo("  [7]  Top expensive queries")
    typer.echo("  [8]  Daily trend — day-over-day spend with rolling average")
    typer.echo("  [9]  Storage — per-database storage breakdown")
    typer.echo("  [10] Budget — Snowflake budget status & projected spend")
    typer.echo("  [11] Replication — cross-region replication costs")
    typer.echo("  [12] Materialized views — MV refresh costs")
    typer.echo("")

    session = PromptSession()
    choice = session.prompt(
        "Choice (1-12): ",
        completer=WordCompleter(["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"]),
    ).strip()

    if choice == "1":
        _cost_summary(cost_service, 30, None, False)
    elif choice == "2":
        _cost_warehouses(cost_service, 30, None, False)
    elif choice == "3":
        _cost_users(cost_service, 7, None, False)
    elif choice == "4":
        _cost_ai(cost_service, 30, None, False)
    elif choice == "5":
        _cost_ai_users(cost_service, 30, None, False)
    elif choice == "6":
        _cost_services(cost_service, 30, None, False)
    elif choice == "7":
        _cost_queries(cost_service, 7, None, False)
    elif choice == "8":
        _cost_trend(cost_service, 30, None, False)
    elif choice == "9":
        _cost_storage(cost_service, 30, None, False)
    elif choice == "10":
        _cost_budget(cost_service, None)
    elif choice == "11":
        _cost_replication(cost_service, 30, None, False)
    elif choice == "12":
        _cost_materialized_views(cost_service, 30, None, False)
    else:
        typer.secho("Invalid choice.", fg=typer.colors.YELLOW)


def _export_csv(df, csv_path: str | None):
    """Export DataFrame to CSV if path is given. Returns True if exported."""
    if csv_path:
        df.to_csv(csv_path, index=False)
        typer.secho(f"  Exported to: {csv_path}", fg=typer.colors.GREEN)
        return True
    return False


def _cache_indicator(cache_age: int | None) -> str:
    """Return a cache status string for display."""
    if cache_age is None:
        return ""
    return f" (cached {cache_age} min ago)"


def _drill_down_prompt(items: list[str], label: str = "Drill down") -> str | None:
    """
    Show a numbered selection prompt after displaying results.
    Returns the selected item string, or None if user skips.
    """
    import sys
    if not sys.stdin.isatty() or not items:
        return None

    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import WordCompleter

    typer.echo("")
    choices = [str(i + 1) for i in range(len(items))] + ["q"]
    session = PromptSession()
    selection = session.prompt(
        f"  {label} (1-{len(items)}, q to skip): ",
        completer=WordCompleter(choices),
    ).strip()

    if not selection or selection.lower() == "q":
        return None
    try:
        idx = int(selection) - 1
        if 0 <= idx < len(items):
            return items[idx]
    except ValueError:
        pass
    return None


def _display_daily_trend(df, title: str):
    """Render a daily trend DataFrame as a sparkline table."""
    if df.empty:
        typer.echo("  No data for this selection.")
        return
    typer.echo("")
    typer.secho(f"  {title}", fg=typer.colors.CYAN, bold=True)
    typer.echo(f"  {'DATE':<12} {'CREDITS':>10}  {'TREND'}")
    typer.echo(f"  {'─' * 12} {'─' * 10}  {'─' * 20}")
    max_credits = df["CREDITS"].max() if not df.empty else 1
    for _, row in df.iterrows():
        bar_len = int((row["CREDITS"] / max_credits) * 20) if max_credits > 0 else 0
        bar = "▓" * bar_len
        typer.echo(f"  {str(row['DATE']):<12} {row['CREDITS']:>10,.2f}  {bar}")
    typer.echo("")


def _cost_summary(cost_service, days: int, csv_path: str | None, refresh: bool):
    """Display account cost summary by service type."""
    typer.echo(f"\nFetching account summary (last {days} days)...")
    df, cache_age = cost_service.get_account_summary(days, refresh=refresh)
    if df.empty:
        typer.echo("  No cost data found.")
        return

    if _export_csv(df, csv_path):
        return

    typer.echo("")
    total = df["CREDITS"].sum()
    typer.secho(f"  Total: {total:,.2f} credits ({days} days){_cache_indicator(cache_age)}", fg=typer.colors.GREEN, bold=True)
    typer.echo("")
    for i, (_, row) in enumerate(df.iterrows(), 1):
        bar_len = int(row["PCT"] / 2)
        bar = "█" * bar_len
        typer.echo(f"  [{i:>2}] {row['SERVICE_TYPE']:<38} {row['CREDITS']:>10,.2f}  {row['PCT']:>5.1f}%  {bar}")
    typer.echo("")

    # Drill-down
    service_types = df["SERVICE_TYPE"].tolist()
    selected = _drill_down_prompt(service_types, "View daily trend for service")
    if selected:
        typer.echo(f"\n  Fetching daily trend for {selected}...")
        detail_df = cost_service.get_service_daily_trend(selected, days)
        _display_daily_trend(detail_df, f"Daily Trend: {selected} ({days} days)")


def _cost_warehouses(cost_service, days: int, csv_path: str | None, refresh: bool):
    """Display warehouse cost breakdown."""
    typer.echo(f"\nFetching warehouse costs (last {days} days)...")
    df, cache_age = cost_service.get_warehouse_breakdown(days, refresh=refresh)
    if df.empty:
        typer.echo("  No warehouse data found.")
        return

    if _export_csv(df, csv_path):
        return

    typer.echo("")
    if cache_age is not None:
        typer.secho(f"  {_cache_indicator(cache_age).strip()}", fg=typer.colors.BRIGHT_BLACK)
    cli.print_table(df, title=f"Warehouse Costs ({days} days)")

    # Drill-down
    if not df.empty and "WAREHOUSE_NAME" in df.columns:
        warehouses = df["WAREHOUSE_NAME"].tolist()
        selected = _drill_down_prompt(warehouses, "View daily trend for warehouse")
        if selected:
            typer.echo(f"\n  Fetching daily trend for {selected}...")
            detail_df = cost_service.get_warehouse_daily_trend(selected, days)
            _display_daily_trend(detail_df, f"Daily Trend: {selected} ({days} days)")


def _cost_users(cost_service, days: int, csv_path: str | None, refresh: bool):
    """Display complete cost per user — warehouse + all AI services."""
    typer.echo(f"\nFetching user costs (last {days} days)...")
    df, cache_age = cost_service.get_user_breakdown(days, refresh=refresh)
    if df.empty:
        typer.echo("  No user data found.")
        return

    if _export_csv(df, csv_path):
        return

    typer.echo("")
    if cache_age is not None:
        typer.secho(f"  {_cache_indicator(cache_age).strip()}", fg=typer.colors.BRIGHT_BLACK)
    cli.print_table(df, title=f"User Cost Attribution ({days} days)")

    # Drill-down
    if not df.empty and "USER_NAME" in df.columns:
        users = df["USER_NAME"].tolist()
        selected = _drill_down_prompt(users, "View warehouse breakdown for user")
        if selected:
            typer.echo(f"\n  Fetching detail for {selected}...")
            detail_df = cost_service.get_user_detail(selected, days)
            if detail_df.empty:
                typer.echo("  No query attribution data for this user.")
            else:
                cli.print_table(detail_df, title=f"Warehouse Breakdown: {selected} ({days} days)")


def _cost_ai(cost_service, days: int, csv_path: str | None, refresh: bool):
    """Display AI/ML token costs by service type."""
    typer.echo(f"\nFetching AI costs (last {days} days)...")
    df, cache_age = cost_service.get_ai_costs(days, refresh=refresh)
    if df.empty:
        typer.echo("  No AI usage found.")
        return

    if _export_csv(df, csv_path):
        return

    typer.echo("")
    total = df["TOTAL_CREDITS"].astype(float).sum()
    typer.secho(f"  Total AI credits: {total:,.2f} ({days} days){_cache_indicator(cache_age)}", fg=typer.colors.GREEN, bold=True)
    typer.echo("")
    for _, row in df.iterrows():
        bar_len = int(row["PCT"] / 2)
        bar = "█" * bar_len
        typer.echo(f"  {row['SERVICE']:<30} {float(row['TOTAL_CREDITS']):>10,.2f}  {row['PCT']:>5.1f}%  {bar}")
    typer.echo("")


def _cost_ai_users(cost_service, days: int, csv_path: str | None, refresh: bool):
    """Display AI/ML token costs per user with service breakdown."""
    typer.echo(f"\nFetching AI costs by user (last {days} days)...")
    df, cache_age = cost_service.get_ai_costs_by_user(days, refresh=refresh)
    if df.empty:
        typer.echo("  No AI usage found.")
        return

    if _export_csv(df, csv_path):
        return

    typer.echo("")
    if cache_age is not None:
        typer.secho(f"  {_cache_indicator(cache_age).strip()}", fg=typer.colors.BRIGHT_BLACK)
    cli.print_table(df, title=f"AI Token Costs by User ({days} days)")


def _cost_services(cost_service, days: int, csv_path: str | None, refresh: bool):
    """Display non-warehouse service costs (pipes, tasks, SPCS, clustering)."""
    typer.echo(f"\nFetching service costs (last {days} days)...")
    df, cache_age = cost_service.get_service_breakdown(days, refresh=refresh)
    if df.empty:
        typer.echo("  No service cost data found.")
        return

    if _export_csv(df, csv_path):
        return

    typer.echo("")
    # Group totals by service type
    totals = df.groupby("SERVICE")["CREDITS"].sum().sort_values(ascending=False)
    typer.secho(f"  Service totals:{_cache_indicator(cache_age)}", fg=typer.colors.GREEN, bold=True)
    for svc, credits in totals.items():
        typer.echo(f"    {svc:<25} {credits:>10,.2f} credits")
    typer.echo("")
    cli.print_table(df, title=f"Service Resource Costs ({days} days)")


def _cost_queries(cost_service, days: int, csv_path: str | None, refresh: bool):
    """Display top expensive queries."""
    typer.echo(f"\nFetching top queries (last {days} days)...")
    df, cache_age = cost_service.get_top_queries(days, refresh=refresh)
    if df.empty:
        typer.echo("  No query data found.")
        return

    if _export_csv(df, csv_path):
        return

    typer.echo("")
    cli.print_table(df, title=f"Top Expensive Queries ({days} days)")


def _cost_trend(cost_service, days: int, csv_path: str | None, refresh: bool):
    """Display daily cost trend with day-over-day change and rolling 7-day average."""
    typer.echo(f"\nFetching daily trend (last {days} days)...")
    df, cache_age = cost_service.get_daily_trend(days, refresh=refresh)
    if df.empty:
        typer.echo("  No trend data found.")
        return

    if _export_csv(df, csv_path):
        return

    typer.echo("")
    total = df["CREDITS"].sum()
    avg_daily = df["CREDITS"].mean()
    typer.secho(f"  Total: {total:,.2f} credits | Avg daily: {avg_daily:,.2f}{_cache_indicator(cache_age)}", fg=typer.colors.GREEN, bold=True)
    typer.echo("")

    # Sparkline-style table showing date, credits, delta, and rolling avg
    typer.echo(f"  {'DATE':<12} {'CREDITS':>10} {'DELTA %':>9} {'7D AVG':>10}  {'TREND'}")
    typer.echo(f"  {'─' * 12} {'─' * 10} {'─' * 9} {'─' * 10}  {'─' * 20}")
    max_credits = df["CREDITS"].max() if not df.empty else 1
    for _, row in df.iterrows():
        bar_len = int((row["CREDITS"] / max_credits) * 20) if max_credits > 0 else 0
        bar = "▓" * bar_len
        delta_str = f"{row['DELTA_PCT']:+.1f}%" if pd.notna(row["DELTA_PCT"]) else "    —"
        avg_str = f"{row['ROLLING_7D_AVG']:,.2f}" if pd.notna(row["ROLLING_7D_AVG"]) else "—"
        typer.echo(f"  {str(row['DATE']):<12} {row['CREDITS']:>10,.2f} {delta_str:>9} {avg_str:>10}  {bar}")
    typer.echo("")


def _cost_storage(cost_service, days: int, csv_path: str | None, refresh: bool):
    """Display per-database storage breakdown with estimated monthly cost."""
    typer.echo(f"\nFetching storage usage (avg over last {days} days)...")
    df, cache_age = cost_service.get_storage_usage(days, refresh=refresh)
    if df.empty:
        typer.echo("  No storage data found.")
        return

    if _export_csv(df, csv_path):
        return

    typer.echo("")
    total_tb = df["TOTAL_TB"].sum()
    total_cost = df["EST_MONTHLY_COST"].sum()
    rate = cost_service.get_storage_rate()
    typer.secho(f"  Total storage: {total_tb:,.4f} TB | Est. monthly: ${total_cost:,.2f}{_cache_indicator(cache_age)}", fg=typer.colors.GREEN, bold=True)
    rate_source = "contracted rate" if rate != 23.0 else "on-demand default"
    typer.echo(f"  (Estimated at ${rate:.2f}/TB/month — {rate_source})")
    typer.echo("")

    # Display table with human-readable sizes
    display_df = df[["DATABASE_NAME", "TOTAL_TB", "EST_MONTHLY_COST"]].copy()
    display_df = display_df[display_df["TOTAL_TB"] > 0]
    if not display_df.empty:
        cli.print_table(display_df, title=f"Storage by Database ({days}-day avg)")


def _cost_budget(cost_service, csv_path: str | None):
    """Display Snowflake native budget status."""
    typer.echo("\nFetching budget status...")
    df, error = cost_service.get_budget_status()
    if error:
        typer.secho(f"  {error}", fg=typer.colors.YELLOW)
        return

    if df.empty:
        typer.echo("  No budget spending history found.")
        return

    if _export_csv(df, csv_path):
        return

    typer.echo("")
    typer.secho("  Snowflake Budget — Spending History", fg=typer.colors.CYAN, bold=True)
    typer.echo("")
    cli.print_table(df, title="Budget Spending History")


def _cost_replication(cost_service, days: int, csv_path: str | None, refresh: bool):
    """Display replication costs by group or daily."""
    typer.echo(f"\nFetching replication costs (last {days} days)...")
    df, cache_age = cost_service.get_replication_costs(days, refresh=refresh)
    if df.empty:
        typer.echo("  No replication cost data found.")
        return

    if _export_csv(df, csv_path):
        return

    typer.echo("")
    if cache_age is not None:
        typer.secho(f"  {_cache_indicator(cache_age).strip()}", fg=typer.colors.BRIGHT_BLACK)
    cli.print_table(df, title=f"Replication Costs ({days} days)")


def _cost_materialized_views(cost_service, days: int, csv_path: str | None, refresh: bool):
    """Display materialized view refresh costs."""
    typer.echo(f"\nFetching materialized view costs (last {days} days)...")
    df, cache_age = cost_service.get_materialized_view_costs(days, refresh=refresh)
    if df.empty:
        typer.echo("  No materialized view cost data found.")
        return

    if _export_csv(df, csv_path):
        return

    typer.echo("")
    total = df["CREDITS"].sum() if "CREDITS" in df.columns else 0
    typer.secho(f"  Total MV refresh credits: {total:,.2f}{_cache_indicator(cache_age)}", fg=typer.colors.GREEN, bold=True)
    typer.echo("")
    cli.print_table(df, title=f"Materialized View Costs ({days} days)")


def _cmd_drift(ctx: SnowglobeContext, args: list):
    """Show access changes since last refresh or --days N."""
    days = None
    for i, a in enumerate(args):
        if a == "--days" and i + 1 < len(args):
            days = int(args[i + 1])

    access_service = AccessService(ctx)
    result = access_service.detect_drift(days=days)
    typer.echo(cli.format_drift_text(result))


def _cmd_unused(ctx: SnowglobeContext, args: list):
    """Find roles with granted privileges but no query activity."""
    days = 90
    for i, a in enumerate(args):
        if a == "--days" and i + 1 < len(args):
            days = int(args[i + 1])

    typer.echo(f"\nChecking for unused privileges (inactive >{days} days)...")
    access_service = AccessService(ctx)
    df, error = access_service.detect_unused_privileges(days=days)
    if error:
        typer.secho(f"  {error}", fg=typer.colors.YELLOW)
        return
    if df.empty:
        typer.secho("  All roles with data grants are active.", fg=typer.colors.GREEN)
        return
    typer.echo("")
    cli.print_table(df, title=f"Roles with Unused Privileges (>{days} days inactive)")


def _cmd_report(ctx: SnowglobeContext, args: list):
    """Generate reports. Usage: report <username> | report full | report cost"""
    if not args:
        typer.echo("Usage:")
        typer.echo("  report <username>    Full access report for a user")
        typer.echo("  report full          Cost + AI + storage + queries report (saves .md)")
        typer.echo("  report cost          Cost-only report (saves .md)")
        return

    sub = args[0].lower()

    if sub == "full":
        from snowglobe.core.report_service import ReportService
        days = 30
        for i, a in enumerate(args[1:]):
            if a == "--days" and i + 2 <= len(args[1:]):
                days = int(args[i + 2])

        typer.echo(f"\nGenerating full report ({days} days)...")
        service = ReportService(ctx)
        output_path = f"snowglobe_report_{__import__('datetime').date.today().isoformat()}.md"
        _, data = service.generate_and_save(output_path, days=days)
        typer.echo(service.terminal_summary(data))
        typer.secho(f"  Report saved: {output_path}", fg=typer.colors.GREEN, bold=True)
        typer.echo("")

    elif sub == "cost":
        from snowglobe.core.report_service import ReportService
        days = 30
        for i, a in enumerate(args[1:]):
            if a == "--days" and i + 2 <= len(args[1:]):
                days = int(args[i + 2])

        typer.echo(f"\nGenerating cost report ({days} days)...")
        service = ReportService(ctx)
        data = service.generate_full_report(days=days, top_n=0)
        data["top_queries"] = []
        markdown = service.render_markdown(data)
        output_path = f"snowglobe_cost_{__import__('datetime').date.today().isoformat()}.md"
        from pathlib import Path
        Path(output_path).write_text(markdown)
        typer.echo(service.terminal_summary(data))
        typer.secho(f"  Report saved: {output_path}", fg=typer.colors.GREEN, bold=True)
        typer.echo("")

    else:
        # Treat as username for access report
        username = args[0].upper()
        typer.echo(f"\nGenerating access report for {username}...")
        access_service = AccessService(ctx)
        try:
            result = access_service.inspect_user_report(username)
            typer.echo(cli.format_user_report(result))
        except Exception as e:
            typer.secho(f"  Error: {e}", fg=typer.colors.RED)


def _cmd_optimize(ctx: SnowglobeContext, args: list):
    """Analyze a query by ID."""
    if not args:
        typer.echo("Usage: optimize <query_id>")
        return

    query_id = args[0]
    optimizer_service = QueryOptimizerService(ctx)
    optimizer_service.collect_query_profile(query_id)
    optimizer_service.analyze_query()

    # Snowflake-native insights first
    insights = optimizer_service.collect_insights()
    if insights:
        typer.echo(cli.format_query_insights(query_id, insights))

    # Local rule-based suggestions
    opt_suggestions = optimizer_service.suggestions()
    typer.echo(cli.format_optimizer_suggestions(query_id, opt_suggestions.suggestions))

    tree = optimizer_service.build_operator_tree()
    scores = optimizer_service.score()
    cli.print_operator_tree(tree, scores)

    opt_cost_attribution = optimizer_service.cost_attribution()
    typer.echo(cli.format_cost_attribution(opt_cost_attribution))

    opt_exp = optimizer_service.expensive_operators()
    typer.echo(cli.format_expensive_operators(opt_exp))


def _cmd_status(ctx: SnowglobeContext, args: list):
    """Show current shell working state."""
    from snowglobe.state.db import StateDB
    from datetime import datetime, timezone

    typer.echo("Current state:")
    typer.echo(f"  user:        {ctx.username or '(not set)'}")
    typer.echo(f"  role:        {ctx.target_role or '(not set)'}")
    typer.echo(f"  object_type: {ctx.object_type or '(not set)'}")
    typer.echo(f"  object_name: {ctx.object_name or '(not set)'}")
    typer.echo(f"  privilege:   {ctx.privilege or '(not set)'}")

    # Show cache age
    db = StateDB()
    refreshed_at = db.get_refreshed_at()
    if refreshed_at:
        try:
            refreshed = datetime.fromisoformat(refreshed_at)
            age = datetime.now(timezone.utc) - refreshed
            hours = age.total_seconds() / 3600
            if hours < 1:
                age_str = f"{int(age.total_seconds() / 60)} minutes ago"
            elif hours < 24:
                age_str = f"{int(hours)} hours ago"
            else:
                age_str = f"{int(hours // 24)} days ago"
            typer.echo(f"  cache:       refreshed {age_str}")
        except (ValueError, TypeError):
            typer.echo("  cache:       unknown age")
    else:
        typer.echo("  cache:       not populated")


def _cmd_debug(ctx: SnowglobeContext, args: list):
    """Run connection diagnostics."""
    from snowglobe.cli.debug import run_diagnostics
    run_diagnostics(profile_name=ctx.profile_name, verbose=ctx.verbose)


def _cmd_refresh(ctx: SnowglobeContext, args: list):
    """Refresh cached state from Snowflake. Use 'refresh --full' for complete reload."""
    full = "--full" in args

    access_service = AccessService(ctx)
    access_service.setup_state()

    access_service.refresh_state(full=full)

    # Update context with fresh data
    ctx.user_graph = access_service.user_graph
    ctx.role_graph = access_service.role_graph
    ctx.object_index = access_service.object_index

    typer.secho(f"  Users:        {len(ctx.user_graph.assigned_roles)}", fg=typer.colors.GREEN)
    typer.secho(f"  Roles:        {len(ctx.role_graph.parents)}", fg=typer.colors.GREEN)
    total_objects = sum(len(v) for v in ctx.object_index.values())
    typer.secho(f"  Object index: {total_objects} FQNs", fg=typer.colors.GREEN)
    typer.secho("Done.", fg=typer.colors.GREEN, bold=True)


def _cmd_help(ctx: SnowglobeContext, args: list):
    """Show available shell commands."""
    typer.echo("")
    typer.secho("Commands:", fg=typer.colors.CYAN, bold=True)
    typer.echo("  check              Guided access & privilege checks (start here)")
    typer.echo("  roles <user>       What roles does a user have?")
    typer.echo("  members <role>     Who has this role?")
    typer.echo("  path <from> <to>   Does one role inherit from another?")
    typer.echo("  escalation <role>  Can this role reach admin privileges?")
    typer.echo("  scan               Bulk scan: find all escalation risks")
    typer.echo("  cost               Cost analysis wizard")
    typer.echo("  cost summary       Account spend by service type")
    typer.echo("  cost warehouses    Cost per warehouse")
    typer.echo("  cost users         Cost per user")
    typer.echo("  cost ai            AI token costs by service")
    typer.echo("  cost queries       Top expensive queries")
    typer.echo("  cost trend         Daily spend trend with rolling avg")
    typer.echo("  cost storage       Per-database storage breakdown")
    typer.echo("  cost budget        Snowflake budget status")
    typer.echo("  cost replication   Replication costs by group")
    typer.echo("  cost mv            Materialized view refresh costs")
    typer.echo("  optimize <id>      Analyze a specific query")
    typer.echo("  drift              Show access changes since last refresh")
    typer.echo("  unused             Find roles with unused privileges")
    typer.echo("  report <user>      Full access report for a user")
    typer.echo("  report full        Cost/AI/storage/queries report (saves .md)")
    typer.echo("  report cost        Cost-only report (saves .md)")
    typer.echo("  refresh            Refresh cached state from Snowflake")
    typer.echo("  status             Show current working state")
    typer.echo("  debug              Run connection diagnostics")
    typer.echo("  help / ?           Show this help")
    typer.echo("  exit               Exit the shell")
    typer.echo("")
    typer.secho("Shortcuts:", fg=typer.colors.CYAN)
    typer.echo("  use role <name>    Set active role")
    typer.echo("  use user <name>    Set active user")
    typer.echo("  access             Direct: can user/role access object?")
    typer.echo("  whoaccess          Direct: who can access object?")
    typer.echo("  create             Direct: where can role create objects?")
    typer.echo("")


# --- Typer registration ---

shell_app = typer.Typer(
    help="Interactive Snowglobe shell",
    no_args_is_help=True,
)


@shell_app.command()
def shell(ctx: typer.Context):
    """Launch the interactive Snowglobe shell."""
    start_shell(ctx.obj)
