import typer
from typing import Optional
from collections import defaultdict
from snowglobe.state.db import StateDB
from snowglobe.collectors.access import AccessCollector
from snowglobe.graphs.role_graph import RoleGraph
from snowglobe.graphs.user_graph import UserGraph
from snowglobe.models.access import AccessGrant
from snowglobe.models.privilege import Privilege
from snowglobe.models.object_ref import ObjectRef
from snowglobe.models.object_type import ObjectType
from snowglobe.engines.access.explainer import AccessExplainer
from snowglobe.engines.access.resolver import AccessResolver

# Object types not tracked in GRANTS_TO_ROLES — require SHOW GRANTS ON fallback
_SHOW_GRANT_TYPES = {"STREAMLIT", "NOTEBOOK", "DYNAMIC TABLE", "ALERT", "TAG", "SECRET"}


def _parse_object_type(obj_type_str: str) -> ObjectType:
    try:
        return ObjectType(obj_type_str)
    except ValueError:
        return ObjectType.UNKNOWN


def _grant_dicts_to_objects(grant_dicts: list[dict]) -> list[AccessGrant]:
    """Convert raw SQLite grant dicts to AccessGrant objects."""
    grants = []
    for row in grant_dicts:
        grants.append(AccessGrant(
            role=row["grantee"],
            privilege=row["privilege"],
            object=ObjectRef(
                object_type=_parse_object_type(row["granted_on"]),
                name=row["fqn"],
            ),
            granted_on=row["granted_on"],
            granted_by=row.get("granted_by", ""),
            inherited=False,
            source_role=None,
            role_type="DATABASE" if row["grantee"].startswith("DATABASE_ROLE::") else "ACCOUNT",
        ))
    return grants


class AccessService:
    def __init__(self, context):
        self.context = context
        self.load_profile()

    def load_profile(self):
        self.context.load_profile()
        self.profile = self.context.profile

    def get_profile(self):
        return self.profile

    def get_graphs(self):
        self.setup_state()
        self.load_state()
        return self.user_graph, self.role_graph, self.object_index

    def setup_state(self):
        self.db = StateDB()

    def refresh_state(self, full: bool = False):
        """
        Refresh state from Snowflake.
        If full=True or no previous state exists, does a complete refresh.
        Otherwise, does an incremental refresh using the last refresh timestamp.
        """
        sf = self.context.connect()
        collector = AccessCollector(sf)

        # Determine if we can do incremental
        last_refresh = self.db.get_refreshed_at()
        if full or not last_refresh or not self.db.has_state():
            typer.secho("Full refresh...", fg=typer.colors.CYAN)
            self._full_refresh(collector)
        else:
            typer.secho(f"Incremental refresh (since {last_refresh[:19]})...", fg=typer.colors.CYAN)
            self._incremental_refresh(collector, last_refresh)

    def _full_refresh(self, collector):
        """Complete refresh — fetch everything into SQLite."""
        # 1. User roles
        user_graph = collector.collect_user_roles()
        self.db.save_user_roles(user_graph.to_dict())
        self.user_graph = user_graph
        typer.echo(f"  Users: {len(user_graph.assigned_roles)}")

        # 2. Role hierarchy
        role_graph = collector.collect_role_graph()
        edges = []
        for parent, children in role_graph.parents.items():
            for child in children:
                edges.append((parent, child))
        self.db.save_role_edges(edges)
        self.role_graph = role_graph
        typer.echo(f"  Roles: {len(role_graph.parents)}")

        # 3. ALL grants (783K rows)
        typer.echo("  Grants: fetching...")
        grant_rows = collector.collect_all_grants_bulk()
        self.db.save_grants(grant_rows)
        typer.echo(f"  Grants: {len(grant_rows)}")

        # 4. Extra objects (STREAMLIT, NOTEBOOK, DYNAMIC TABLE, ALERT — not in GRANTS_TO_ROLES)
        typer.echo("  Extra objects: fetching...")
        extra_objects = collector.collect_extra_objects()
        self.db.save_extra_objects(extra_objects)
        extra_count = sum(len(v) for v in extra_objects.values())
        typer.echo(f"  Extra objects: {extra_count} FQNs")

        # 5. Update timestamp
        self.db.set_refreshed_at()

        # 6. Load object index from SQLite
        self.object_index = self.db.query_object_index()
        total_objects = sum(len(v) for v in self.object_index.values())
        typer.echo(f"  Object index: {total_objects} FQNs (derived from grants)")

    def _incremental_refresh(self, collector, since: str):
        """
        Incremental refresh — only fetch changes since last refresh.
        """
        # 1. User roles — incremental
        user_changes = collector.collect_user_roles_incremental(since)
        if user_changes["added"] or user_changes["removed"]:
            self.db.upsert_user_roles_incremental(
                added=user_changes["added"],
                removed=user_changes["removed"],
            )
            typer.echo(f"  Users: +{len(user_changes['added'])} / -{len(user_changes['removed'])} changes")
        else:
            typer.echo("  Users: no changes")

        # 2. Role graph — incremental
        role_changes = collector.collect_role_graph_incremental(since)
        if role_changes["added"] or role_changes["removed"]:
            added_edges = []
            for parent_key, children in role_changes["added"].items():
                for child in children:
                    added_edges.append((parent_key, child))
            removed_edges = []
            for parent_key, children in role_changes["removed"].items():
                for child in children:
                    removed_edges.append((parent_key, child))
            self.db.upsert_role_edges_incremental(
                added=added_edges, removed=removed_edges
            )
            typer.echo(f"  Roles: +{len(role_changes['added'])} / -{len(role_changes['removed'])} changes")
        else:
            typer.echo("  Roles: no changes")

        # 3. All grants — incremental
        grant_changes = collector.collect_all_grants_incremental(since)
        if grant_changes["upsert"] or grant_changes["delete"]:
            self.db.upsert_grants_incremental(
                upserts=grant_changes["upsert"],
                deletes=grant_changes["delete"],
            )
            typer.echo(f"  Grants: +{len(grant_changes['upsert'])} / -{len(grant_changes['delete'])} changes")
        else:
            typer.echo("  Grants: no changes")

        # 4. Update timestamp
        self.db.set_refreshed_at()

        # 5. Load graphs into memory
        self.load_state()

    def load_state(self):
        """Load role graph and user graph into memory from SQLite."""
        if not self.db.has_state():
            typer.secho(
                "No cached state found. Fetching from Snowflake...",
                fg=typer.colors.YELLOW
            )
            self.refresh_state()
            return

        # Check staleness
        self._check_staleness()

        # Load role graph
        rg_data = self.db.load_role_graph_data()
        rg = RoleGraph()
        rg = rg.from_dict(rg_data)
        self.role_graph = rg

        # Load user graph
        ug_data = self.db.load_user_roles_data()
        ug = UserGraph(ug_data, **self.context.profile)
        self.user_graph = ug

        # Object index (derived from grants table)
        self.object_index = self.db.query_object_index()

    def _check_staleness(self):
        """Warn if cached state is older than 24 hours."""
        from datetime import datetime, timezone

        refreshed_at = self.db.get_refreshed_at()
        if not refreshed_at:
            return

        try:
            refreshed = datetime.fromisoformat(refreshed_at)
            age = datetime.now(timezone.utc) - refreshed
            hours = age.total_seconds() / 3600

            if hours > 24:
                days = int(hours // 24)
                label = f"{days} day(s)" if days >= 1 else f"{int(hours)} hour(s)"
                typer.secho(
                    f"State is {label} old. Run 'refresh' to update.",
                    fg=typer.colors.YELLOW
                )
        except (ValueError, TypeError):
            pass

    def build_resolver(self, grants: list[AccessGrant]):
        self.resolver = AccessResolver(
            user_graph=self.user_graph,
            role_graph=self.role_graph,
            grants=grants,
        )

    def inspect_access(
        self,
        username: Optional[str],
        role: Optional[str],
        object_type: Optional[str],
        object_name: Optional[str],
        privilege: Optional[str],
        ignore_excluded_roles: bool,
        refresh_state: bool,
    ):
        """
        Run access inspection with fully resolved arguments.
        """
        if ignore_excluded_roles:
            self.profile['exclude_roles'] = []

        self.setup_state()

        if refresh_state:
            self.refresh_state()

        self.load_state()

        # Fetch grants for the object from SQLite (instant)
        object_name_upper = object_name.upper() if object_name else None
        grant_dicts = self.db.query_grants_for_object(object_type, object_name_upper)
        grants = _grant_dicts_to_objects(grant_dicts)

        # Fallback: types not in GRANTS_TO_ROLES (STREAMLIT, NOTEBOOK, etc.)
        if not grants and object_type and object_type.upper() in _SHOW_GRANT_TYPES:
            sf = self.context.connect()
            collector = AccessCollector(sf)
            grants = collector.collect_grants_for_object(object_type, object_name_upper)

        self.build_resolver(grants)

        # Determine inspect type
        if username and not role:
            inspect_type = "user"
        elif role and not username:
            inspect_type = "role"
        else:
            typer.secho("Must provide either --username or --role.", fg=typer.colors.RED)
            raise typer.Exit(1)

        database = object_name_upper.split(".", 1)[0] if object_name_upper else None

        args = {
            "inspect_type": inspect_type,
            "username": username,
            "role": role,
            "object_type": object_type,
            "object_name": object_name_upper,
            "database": database,
            "privilege": privilege,
        }

        query = AccessExplainer(resolver=self.resolver, **args)
        if inspect_type == "user":
            query_output = query.user_access(username=username)
        elif inspect_type == "role":
            query_output = query.role_access(role=role)
        else:
            typer.secho("Invalid inspect type. Exiting.", fg=typer.colors.RED)
            raise typer.Exit()

        return query_output

    def inspect_reverse(
        self,
        object_type: str,
        object_name: str,
        privilege: Optional[str] = None,
    ) -> dict:
        """
        Reverse lookup: who/what can access this object?
        """
        self.setup_state()
        self.load_state()

        # Query grants from SQLite (instant)
        grant_dicts = self.db.query_grants_for_object(object_type, object_name.upper())

        # Fallback: types not in GRANTS_TO_ROLES (STREAMLIT, NOTEBOOK, etc.)
        if not grant_dicts and object_type and object_type.upper() in _SHOW_GRANT_TYPES:
            sf = self.context.connect()
            collector = AccessCollector(sf)
            show_grants = collector.collect_grants_for_object(object_type, object_name)
            # Convert AccessGrant objects to dicts for consistent handling
            grant_dicts = [
                {"grantee": g.role, "privilege": g.privilege, "granted_on": g.granted_on,
                 "name": None, "table_catalog": None, "table_schema": None,
                 "granted_by": g.granted_by, "granted_to": g.role_type, "fqn": g.object.name}
                for g in show_grants
            ]

        if not grant_dicts:
            return {
                "object_type": object_type.upper(),
                "object_name": object_name.upper(),
                "object_exists": False,
                "privileges": {},
            }

        # Group grants by privilege
        grants_by_privilege = defaultdict(list)
        for g in grant_dicts:
            if privilege and not Privilege.matches(g["privilege"], privilege):
                continue
            grants_by_privilege[g["privilege"]].append(g)

        # For each privilege, find all roles (direct + inherited) and users
        privileges_result = {}
        for priv, priv_grants in sorted(grants_by_privilege.items()):
            direct_roles = set()
            for g in priv_grants:
                direct_roles.add(g["grantee"])

            # Find all roles that inherit from the direct roles (descendants)
            all_roles_with_access = set(direct_roles)
            for role_key in direct_roles:
                descendants = self.role_graph.all_descendants(role_key)
                all_roles_with_access.update(descendants)

            # Find users who have any of these roles
            users_with_access = []
            for user, assigned_roles in self.user_graph.assigned_roles.items():
                user_effective = set(assigned_roles)
                for r in assigned_roles:
                    user_effective |= self.role_graph.all_ancestors(r)
                if user_effective & all_roles_with_access:
                    via_roles = user_effective & all_roles_with_access
                    users_with_access.append({
                        "user": user,
                        "via_roles": sorted(via_roles),
                    })

            privileges_result[priv] = {
                "direct_roles": sorted(direct_roles),
                "inherited_roles": sorted(all_roles_with_access - direct_roles),
                "users": sorted(users_with_access, key=lambda u: u["user"]),
            }

        return {
            "object_type": object_type.upper(),
            "object_name": object_name.upper(),
            "object_exists": True,
            "privilege_filter": privilege,
            "privileges": privileges_result,
        }

    def inspect_create(
        self,
        username: Optional[str],
        role: Optional[str],
        privilege: str,
        scope: Optional[str] = None,
    ) -> dict:
        """
        Check CREATE privileges for a user or role.
        """
        self.setup_state()
        self.load_state()

        # Resolve effective roles
        if username and not role:
            identity = username
            identity_type = "user"
            effective_roles = self.user_graph.effective_roles(username, self.role_graph)
            direct_roles = set(self.user_graph.roles_of(username)[0])
            all_roles = effective_roles | direct_roles
        elif role and not username:
            identity = role
            identity_type = "role"
            all_roles = {role} | self.role_graph.all_ancestors(role)
        else:
            typer.secho("Must provide either --username or --role.", fg=typer.colors.RED)
            raise typer.Exit(1)

        # Query CREATE grants from SQLite
        create_rows = self.db.query_create_grants(
            privilege=privilege,
            grantee_keys=all_roles,
            scope=scope,
        )

        # Build result structure
        result = {
            "privilege": privilege,
            "identity": identity,
            "identity_type": identity_type,
            "scope": scope,
            "account_wide": False,
            "account_wide_roles": [],
            "databases": [],
            "schemas": [],
        }

        for row in create_rows:
            granted_on = row["granted_on"]
            name = row["name"]
            catalog = row["table_catalog"]
            grantee_key = row["grantee"]

            if granted_on == "ACCOUNT":
                result["account_wide"] = True
                result["account_wide_roles"].append(grantee_key)

            elif granted_on == "DATABASE":
                db_name = name
                result["databases"].append({"name": db_name, "via_role": grantee_key})

            elif granted_on == "SCHEMA":
                schema_fqn = f"{catalog}.{name}" if catalog else name
                result["schemas"].append({"name": schema_fqn, "via_role": grantee_key})

        # Deduplicate databases
        seen_dbs = {}
        for d in result["databases"]:
            seen_dbs.setdefault(d["name"], []).append(d["via_role"])
        result["databases"] = sorted(
            [{"name": k, "via_roles": sorted(set(v))} for k, v in seen_dbs.items()],
            key=lambda x: x["name"]
        )

        # Deduplicate schemas
        seen_schemas = {}
        for s in result["schemas"]:
            seen_schemas.setdefault(s["name"], []).append(s["via_role"])
        result["schemas"] = sorted(
            [{"name": k, "via_roles": sorted(set(v))} for k, v in seen_schemas.items()],
            key=lambda x: x["name"]
        )

        # Role inheritance paths when scoped
        if scope and (result["schemas"] or result["databases"]):
            access_paths = []
            granting_roles = set()
            for s in result["schemas"]:
                granting_roles.update(s["via_roles"])
            for d in result["databases"]:
                granting_roles.update(d["via_roles"])
            if result["account_wide"]:
                granting_roles.update(result["account_wide_roles"])

            source_role = role if identity_type == "role" else None
            if source_role:
                for granting_role in granting_roles:
                    if granting_role == source_role:
                        access_paths.append([source_role, "(direct grant)"])
                    else:
                        paths = self.role_graph.all_paths(source_role, granting_role)
                        for path in paths:
                            access_paths.append(path)

            result["access_paths"] = access_paths

        # Determine overall access
        has_access = (
            result["account_wide"]
            or len(result["databases"]) > 0
            or len(result["schemas"]) > 0
        )
        result["has_access"] = has_access

        return result

    # --- Drift detection ---

    def detect_drift(self, days: int = None) -> dict:
        """
        Detect access changes since last refresh (or last N days).
        Returns structured dict of added/revoked grants, role changes, user changes.
        """
        self.setup_state()

        if days:
            from datetime import datetime, timezone, timedelta
            since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        else:
            since = self.db.get_refreshed_at()
            if not since:
                return {"error": "No previous refresh found. Run 'refresh' first."}

        sf = self.context.connect()
        collector = AccessCollector(sf)

        # Collect changes
        grant_changes = collector.collect_all_grants_incremental(since)
        role_changes = collector.collect_role_graph_incremental(since)
        user_changes = collector.collect_user_roles_incremental(since)

        return {
            "since": since[:19],
            "grants_added": grant_changes.get("upsert", []),
            "grants_revoked": grant_changes.get("delete", []),
            "roles_added": role_changes.get("added", {}),
            "roles_removed": role_changes.get("removed", {}),
            "users_added": user_changes.get("added", {}),
            "users_removed": user_changes.get("removed", {}),
        }

    # --- Unused privilege detection ---

    def detect_unused_privileges(self, days: int = 90, limit: int = 30) -> tuple:
        """
        Find roles with granted privileges that have had no query activity.
        Compares granted roles against QUERY_HISTORY activity.
        Returns (DataFrame, error_message).
        """
        import pandas as pd

        self.setup_state()

        sql = f"""
        WITH granted_roles AS (
            SELECT DISTINCT grantee AS role_key,
                   REPLACE(grantee, 'ACCOUNT_ROLE::', '') AS role_name
            FROM grants
            WHERE privilege IN ('SELECT', 'INSERT', 'UPDATE', 'DELETE')
              AND granted_on IN ('TABLE', 'VIEW', 'MATERIALIZED VIEW', 'EXTERNAL TABLE')
        ),
        active_roles AS (
            SELECT DISTINCT ROLE_NAME
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
            WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
              AND EXECUTION_STATUS = 'SUCCESS'
              AND QUERY_TYPE IN ('SELECT', 'INSERT', 'UPDATE', 'DELETE', 'MERGE')
        )
        SELECT g.role_name AS ROLE,
               COUNT(DISTINCT gr.fqn) AS GRANTED_OBJECTS,
               CASE WHEN a.ROLE_NAME IS NULL THEN 'INACTIVE' ELSE 'ACTIVE' END AS STATUS
        FROM granted_roles g
        LEFT JOIN grants gr ON gr.grantee = g.role_key
            AND gr.privilege IN ('SELECT', 'INSERT', 'UPDATE', 'DELETE')
            AND gr.granted_on IN ('TABLE', 'VIEW', 'MATERIALIZED VIEW', 'EXTERNAL TABLE')
        LEFT JOIN active_roles a ON a.ROLE_NAME = g.role_name
        GROUP BY g.role_name, a.ROLE_NAME
        HAVING STATUS = 'INACTIVE'
        ORDER BY GRANTED_OBJECTS DESC
        LIMIT {limit}
        """

        # The grants table is local SQLite, but QUERY_HISTORY is on Snowflake.
        # We need a hybrid approach: get active roles from Snowflake, compare locally.
        conn = self.context.connect()
        try:
            with conn:
                rows = conn.query(f"""
                    SELECT DISTINCT ROLE_NAME
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                    WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
                      AND EXECUTION_STATUS = 'SUCCESS'
                      AND QUERY_TYPE IN ('SELECT', 'INSERT', 'UPDATE', 'DELETE', 'MERGE')
                """)
            active_roles = {row["ROLE_NAME"] for row in rows}
        except Exception as e:
            return pd.DataFrame(), f"Could not query activity history: {e}"

        # Get all roles with data grants from local SQLite
        grant_rows = self.db.conn.execute("""
            SELECT grantee, COUNT(DISTINCT fqn) AS object_count
            FROM grants
            WHERE privilege IN ('SELECT', 'INSERT', 'UPDATE', 'DELETE')
              AND granted_on IN ('TABLE', 'VIEW', 'MATERIALIZED VIEW', 'EXTERNAL TABLE')
            GROUP BY grantee
            ORDER BY object_count DESC
        """).fetchall()

        results = []
        for row in grant_rows:
            role_key = row["grantee"]
            # Extract role name from key (ACCOUNT_ROLE::ROLE_NAME)
            if role_key.startswith("ACCOUNT_ROLE::"):
                role_name = role_key.replace("ACCOUNT_ROLE::", "")
            else:
                continue  # Skip database roles for now

            if role_name not in active_roles:
                results.append({
                    "ROLE": role_name,
                    "GRANTED_OBJECTS": row["object_count"],
                    "DAYS_INACTIVE": f">{days}",
                })
            if len(results) >= limit:
                break

        df = pd.DataFrame(results)
        return df, None

    # --- Full user access report ---

    def inspect_user_report(self, username: str) -> dict:
        """
        Full access report for a user: all effective roles and all reachable grants.
        """
        self.setup_state()
        self.load_state()

        # Get effective roles
        direct_roles, excluded_roles = self.user_graph.roles_of(username)
        effective_roles = self.user_graph.effective_roles(username, self.role_graph)

        # Get all grants for effective roles from SQLite
        grant_rows = self.db.query_grants_by_grantees(effective_roles)

        # Group by object type
        by_type: dict[str, list[dict]] = {}
        for g in grant_rows:
            obj_type = g["granted_on"]
            by_type.setdefault(obj_type, []).append(g)

        # Build summary
        summary = {}
        for obj_type, grants in sorted(by_type.items()):
            unique_objects = set(g["fqn"] for g in grants)
            privileges = set(g["privilege"] for g in grants)
            summary[obj_type] = {
                "object_count": len(unique_objects),
                "privileges": sorted(privileges),
                "objects": sorted(unique_objects)[:20],  # Cap for display
                "total_grants": len(grants),
            }

        return {
            "username": username,
            "direct_roles": sorted(direct_roles),
            "excluded_roles": sorted(excluded_roles),
            "effective_roles": sorted(effective_roles),
            "role_count": len(effective_roles),
            "grant_summary": summary,
            "total_objects": sum(s["object_count"] for s in summary.values()),
            "total_grants": sum(s["total_grants"] for s in summary.values()),
        }
