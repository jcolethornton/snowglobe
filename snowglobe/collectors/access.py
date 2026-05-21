# snowglobe/collectors/access.py
from __future__ import annotations
from typing import List
from collections import defaultdict

from snowglobe.models.access import AccessGrant, ObjectType
from snowglobe.graphs.user_graph import UserGraph
from snowglobe.graphs.role_graph import RoleGraph

from snowglobe.models.object_ref import ObjectRef


def account_role(role: str) -> str:
    return f"ACCOUNT_ROLE::{role}"


def database_role(db: str, role: str) -> str:
    return f"DATABASE_ROLE::{db}::{role}"


def _parse_object_type(obj_type_str: str) -> ObjectType:
    try:
        return ObjectType(obj_type_str)
    except ValueError:
        return ObjectType.UNKNOWN


class AccessCollector:
    """
    Collects Snowflake access metadata using ACCOUNT_USAGE views.

    Uses bulk queries instead of per-role SHOW commands for performance.
    ACCOUNT_USAGE views have up to 45 minutes of latency, which is
    acceptable for a caching observability tool.
    """

    def __init__(self, connection):
        self.connection = connection

    def collect_user_roles(self) -> UserGraph:
        """
        Collect all users and their directly assigned roles.
        Uses SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS (single query).
        """
        users_data: dict[str, list[str]] = {}

        with self.connection:
            sql = """
            SELECT GRANTEE_NAME, ROLE
            FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS
            WHERE DELETED_ON IS NULL
            """
            rows = self.connection.query(sql)

            for row in rows:
                username = row["GRANTEE_NAME"]
                role = row["ROLE"]
                users_data.setdefault(username, [])
                users_data[username].append(account_role(role))

        return UserGraph(users_data)

    def collect_user_roles_incremental(self, since: str) -> dict:
        """
        Fetch user role changes since a timestamp.
        Returns {"added": {user: [roles]}, "removed": {user: [roles]}}
        """
        added: dict[str, list[str]] = {}
        removed: dict[str, list[str]] = {}

        with self.connection:
            sql = f"""
            SELECT GRANTEE_NAME, ROLE, DELETED_ON
            FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS
            WHERE GREATEST(CREATED_ON, COALESCE(DELETED_ON, '1970-01-01')) >= '{since}'
            """
            rows = self.connection.query(sql)

            for row in rows:
                username = row["GRANTEE_NAME"]
                role_key = account_role(row["ROLE"])

                if row["DELETED_ON"] is not None:
                    removed.setdefault(username, []).append(role_key)
                else:
                    added.setdefault(username, []).append(role_key)

        return {"added": added, "removed": removed}

    def collect_role_graph(self) -> RoleGraph:
        """
        Build role inheritance graph using ACCOUNT_USAGE.GRANTS_TO_ROLES.
        Single query for all role→role relationships.
        """
        parents: dict[str, set[str]] = defaultdict(set)

        with self.connection:
            sql = """
            SELECT NAME, GRANTEE_NAME, GRANTED_ON, TABLE_CATALOG
            FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_ROLES
            WHERE PRIVILEGE = 'USAGE'
              AND GRANTED_ON IN ('ROLE', 'DATABASE_ROLE')
              AND DELETED_ON IS NULL
            """
            rows = self.connection.query(sql)

            for row in rows:
                child_role = row["NAME"]
                parent_role = row["GRANTEE_NAME"]
                granted_on = row["GRANTED_ON"]

                # Parent (grantee) is always an account role in this view
                parent_key = account_role(parent_role)

                if granted_on == "ROLE":
                    child_key = account_role(child_role)
                else:
                    # DATABASE_ROLE — use TABLE_CATALOG for database context
                    catalog = row["TABLE_CATALOG"]
                    child_key = database_role(catalog, child_role)

                # Edge: parent inherits from child (parent has USAGE on child)
                parents[parent_key].add(child_key)

        return RoleGraph(parents)

    def collect_role_graph_incremental(self, since: str) -> dict:
        """
        Fetch role hierarchy changes since a timestamp.
        Returns {"added": {parent_key: set(child_keys)}, "removed": {parent_key: set(child_keys)}}
        """
        added: dict[str, set] = defaultdict(set)
        removed: dict[str, set] = defaultdict(set)

        with self.connection:
            sql = f"""
            SELECT NAME, GRANTEE_NAME, GRANTED_ON, DELETED_ON, TABLE_CATALOG
            FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_ROLES
            WHERE PRIVILEGE = 'USAGE'
              AND GRANTED_ON IN ('ROLE', 'DATABASE_ROLE')
              AND GREATEST(MODIFIED_ON, COALESCE(DELETED_ON, '1970-01-01')) >= '{since}'
            """
            rows = self.connection.query(sql)

            for row in rows:
                child_role = row["NAME"]
                parent_role = row["GRANTEE_NAME"]
                granted_on = row["GRANTED_ON"]

                parent_key = account_role(parent_role)

                if granted_on == "ROLE":
                    child_key = account_role(child_role)
                else:
                    catalog = row["TABLE_CATALOG"]
                    child_key = database_role(catalog, child_role)

                if row["DELETED_ON"] is not None:
                    removed[parent_key].add(child_key)
                else:
                    added[parent_key].add(child_key)

        return {"added": dict(added), "removed": dict(removed)}

    def collect_direct_grants(self) -> List[AccessGrant]:
        """
        Collect high-level object grants (DATABASE, WAREHOUSE, ACCOUNT).
        These are small (~7K rows) and cached locally.
        Table/view/schema grants are fetched on-demand via collect_grants_for_object().
        """
        grants: list[AccessGrant] = []

        with self.connection:
            sql = """
            SELECT
                GRANTEE_NAME,
                PRIVILEGE,
                GRANTED_ON,
                NAME,
                TABLE_CATALOG,
                TABLE_SCHEMA,
                GRANTED_BY,
                GRANTED_TO
            FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_ROLES
            WHERE GRANTED_ON NOT IN ('ROLE', 'DATABASE_ROLE')
              AND DELETED_ON IS NULL
              AND GRANTED_ON IN ('DATABASE', 'WAREHOUSE', 'ACCOUNT')
            """
            rows = self.connection.query(sql)

            for row in rows:
                grantee = row["GRANTEE_NAME"]
                granted_to = row["GRANTED_TO"]

                # Determine role key
                if granted_to == "DATABASE_ROLE":
                    catalog = row["TABLE_CATALOG"]
                    role_key = database_role(catalog, grantee)
                    role_type = "DATABASE"
                else:
                    role_key = account_role(grantee)
                    role_type = "ACCOUNT"

                # Build fully qualified object name
                obj_name = row["NAME"]
                catalog = row["TABLE_CATALOG"]
                schema = row["TABLE_SCHEMA"]

                if catalog and schema and obj_name:
                    fqn = f"{catalog}.{schema}.{obj_name}"
                elif catalog and obj_name:
                    fqn = f"{catalog}.{obj_name}"
                else:
                    fqn = obj_name or "<UNKNOWN>"

                grant = AccessGrant(
                    role=role_key,
                    privilege=row["PRIVILEGE"],
                    object=ObjectRef(
                        object_type=_parse_object_type(row["GRANTED_ON"]),
                        name=fqn,
                    ),
                    granted_on=row["GRANTED_ON"],
                    granted_by=row["GRANTED_BY"] or "",
                    inherited=False,
                    source_role=None,
                    role_type=role_type,
                )
                grants.append(grant)

        return grants

    def collect_all_grants_bulk(self) -> list[dict]:
        """
        Fetch ALL object grants from ACCOUNT_USAGE for SQLite storage.
        Returns raw dicts with precomputed grantee key and FQN.
        ~783K rows — stored in SQLite for instant local lookups.
        """
        results = []

        with self.connection:
            sql = """
            SELECT
                GRANTEE_NAME,
                PRIVILEGE,
                GRANTED_ON,
                NAME,
                TABLE_CATALOG,
                TABLE_SCHEMA,
                GRANTED_BY,
                GRANTED_TO
            FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_ROLES
            WHERE GRANTED_ON NOT IN ('ROLE', 'DATABASE_ROLE')
              AND DELETED_ON IS NULL
            """
            rows = self.connection.query(sql)

            for row in rows:
                grantee_name = row["GRANTEE_NAME"]
                granted_to = row["GRANTED_TO"]
                catalog = row["TABLE_CATALOG"]
                schema = row["TABLE_SCHEMA"]
                name = row["NAME"]

                # Build role key
                if granted_to == "DATABASE_ROLE":
                    grantee_key = database_role(catalog, grantee_name)
                else:
                    grantee_key = account_role(grantee_name)

                # Build FQN
                if catalog and schema and name:
                    fqn = f"{catalog}.{schema}.{name}"
                elif catalog and name:
                    fqn = f"{catalog}.{name}"
                else:
                    fqn = name or ""

                results.append({
                    "grantee": grantee_key,
                    "privilege": row["PRIVILEGE"],
                    "granted_on": row["GRANTED_ON"],
                    "name": name,
                    "table_catalog": catalog,
                    "table_schema": schema,
                    "granted_by": row["GRANTED_BY"] or "",
                    "granted_to": granted_to,
                    "fqn": fqn,
                })

        return results

    def collect_all_grants_incremental(self, since: str) -> dict:
        """
        Fetch grant changes since a timestamp for incremental SQLite update.
        Returns {"upsert": [rows], "delete": [rows]} with precomputed keys.
        """
        upserts = []
        deletes = []

        with self.connection:
            sql = f"""
            SELECT
                GRANTEE_NAME,
                PRIVILEGE,
                GRANTED_ON,
                NAME,
                TABLE_CATALOG,
                TABLE_SCHEMA,
                GRANTED_BY,
                GRANTED_TO,
                DELETED_ON
            FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_ROLES
            WHERE GRANTED_ON NOT IN ('ROLE', 'DATABASE_ROLE')
              AND GREATEST(MODIFIED_ON, COALESCE(DELETED_ON, '1970-01-01')) >= '{since}'
            """
            rows = self.connection.query(sql)

            for row in rows:
                grantee_name = row["GRANTEE_NAME"]
                granted_to = row["GRANTED_TO"]
                catalog = row["TABLE_CATALOG"]
                schema = row["TABLE_SCHEMA"]
                name = row["NAME"]

                if granted_to == "DATABASE_ROLE":
                    grantee_key = database_role(catalog, grantee_name)
                else:
                    grantee_key = account_role(grantee_name)

                if catalog and schema and name:
                    fqn = f"{catalog}.{schema}.{name}"
                elif catalog and name:
                    fqn = f"{catalog}.{name}"
                else:
                    fqn = name or ""

                entry = {
                    "grantee": grantee_key,
                    "privilege": row["PRIVILEGE"],
                    "granted_on": row["GRANTED_ON"],
                    "name": name,
                    "table_catalog": catalog,
                    "table_schema": schema,
                    "granted_by": row["GRANTED_BY"] or "",
                    "granted_to": granted_to,
                    "fqn": fqn,
                }

                if row["DELETED_ON"] is not None:
                    deletes.append(entry)
                else:
                    upserts.append(entry)

        return {"upsert": upserts, "delete": deletes}

    def collect_all_create_grants(self) -> list:
        """
        Fetch ALL CREATE grants for caching. Returns a list of compact dicts.
        Called during refresh. ~233K rows, stored as JSON for instant lookups.
        """
        results = []

        with self.connection:
            sql = """
            SELECT PRIVILEGE, GRANTED_ON, NAME, TABLE_CATALOG, GRANTEE_NAME
            FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_ROLES
            WHERE PRIVILEGE ILIKE 'CREATE%'
              AND DELETED_ON IS NULL
            """
            rows = self.connection.query(sql)

            for row in rows:
                results.append({
                    "privilege": row["PRIVILEGE"],
                    "granted_on": row["GRANTED_ON"],
                    "name": row["NAME"],
                    "catalog": row["TABLE_CATALOG"],
                    "grantee": row["GRANTEE_NAME"],
                })

        return results

    def collect_create_grants_incremental(self, since: str) -> dict:
        """
        Fetch CREATE grant changes since a timestamp.
        Returns {"upsert": [rows to add/update], "delete": [rows to remove]}
        """
        upsert = []
        delete = []

        with self.connection:
            sql = f"""
            SELECT PRIVILEGE, GRANTED_ON, NAME, TABLE_CATALOG, GRANTEE_NAME, DELETED_ON
            FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_ROLES
            WHERE PRIVILEGE ILIKE 'CREATE%'
              AND GREATEST(MODIFIED_ON, COALESCE(DELETED_ON, '1970-01-01')) >= '{since}'
            """
            rows = self.connection.query(sql)

            for row in rows:
                entry = {
                    "privilege": row["PRIVILEGE"],
                    "granted_on": row["GRANTED_ON"],
                    "name": row["NAME"],
                    "catalog": row["TABLE_CATALOG"],
                    "grantee": row["GRANTEE_NAME"],
                }

                if row["DELETED_ON"] is not None:
                    delete.append(entry)
                else:
                    upsert.append(entry)

        return {"upsert": upsert, "delete": delete}

    @staticmethod
    def resolve_create_grants_from_cache(
        create_grants_cache: list,
        privilege: str,
        role_keys: set,
        scope: str | None = None,
    ) -> dict:
        """
        Resolve CREATE privilege grants from cached data (no Snowflake query).
        Same logic as collect_create_grants but reads from local cache.
        """
        result = {
            "privilege": privilege,
            "account_wide": False,
            "account_wide_roles": [],
            "databases": [],
            "schemas": [],
        }

        # Extract bare role names from keys for matching
        role_names = set()
        for key in role_keys:
            if key.startswith("ACCOUNT_ROLE::"):
                role_names.add(key.replace("ACCOUNT_ROLE::", ""))
            elif key.startswith("DATABASE_ROLE::"):
                parts = key.replace("DATABASE_ROLE::", "").split("::", 1)
                if len(parts) == 2:
                    role_names.add(f"{parts[0]}.{parts[1]}")

        if not role_names:
            return result

        privilege_upper = privilege.upper()

        for row in create_grants_cache:
            if row["privilege"] != privilege_upper:
                continue
            if row["grantee"] not in role_names:
                continue

            granted_on = row["granted_on"]
            name = row["name"]
            catalog = row["catalog"]
            role_key = f"ACCOUNT_ROLE::{row['grantee']}"

            if granted_on == "ACCOUNT":
                result["account_wide"] = True
                result["account_wide_roles"].append(role_key)

            elif granted_on == "DATABASE":
                db_name = name
                if scope:
                    scope_parts = scope.upper().split(".")
                    if scope_parts[0] == db_name:
                        result["databases"].append({"name": db_name, "via_role": role_key})
                else:
                    result["databases"].append({"name": db_name, "via_role": role_key})

            elif granted_on == "SCHEMA":
                schema_fqn = f"{catalog}.{name}" if catalog else name
                if scope:
                    scope_upper = scope.upper()
                    if schema_fqn == scope_upper or schema_fqn.startswith(f"{scope_upper}."):
                        result["schemas"].append({"name": schema_fqn, "via_role": role_key})
                else:
                    result["schemas"].append({"name": schema_fqn, "via_role": role_key})

        # Deduplicate
        seen_dbs = {}
        for d in result["databases"]:
            seen_dbs.setdefault(d["name"], []).append(d["via_role"])
        result["databases"] = sorted(
            [{"name": k, "via_roles": sorted(set(v))} for k, v in seen_dbs.items()],
            key=lambda x: x["name"]
        )

        seen_schemas = {}
        for s in result["schemas"]:
            seen_schemas.setdefault(s["name"], []).append(s["via_role"])
        result["schemas"] = sorted(
            [{"name": k, "via_roles": sorted(set(v))} for k, v in seen_schemas.items()],
            key=lambda x: x["name"]
        )

        result["account_wide_roles"] = sorted(set(result["account_wide_roles"]))

        return result

    def collect_create_grants(self, privilege: str, role_keys: set, scope: str | None = None) -> dict:
        """
        Fetch CREATE privilege grants for a set of roles (including inherited).
        Returns a structured dict with grants grouped by scope level.

        Args:
            privilege: e.g. "CREATE TABLE", "CREATE SCHEMA", "CREATE DATABASE"
            role_keys: set of role keys (e.g. {"ACCOUNT_ROLE::SYSADMIN", ...})
            scope: optional DB or DB.SCHEMA to filter results
        """
        result = {
            "privilege": privilege,
            "account_wide": False,
            "account_wide_roles": [],
            "databases": [],
            "schemas": [],
        }

        # Extract bare role names from keys for matching
        role_names = set()
        for key in role_keys:
            if key.startswith("ACCOUNT_ROLE::"):
                role_names.add(key.replace("ACCOUNT_ROLE::", ""))
            elif key.startswith("DATABASE_ROLE::"):
                parts = key.replace("DATABASE_ROLE::", "").split("::", 1)
                if len(parts) == 2:
                    role_names.add(f"{parts[0]}.{parts[1]}")

        if not role_names:
            return result

        with self.connection:
            # Query all grants for this privilege — filtered server-side by privilege only
            # Post-filter by role in Python (faster than large IN clause)
            sql = f"""
            SELECT GRANTED_ON, NAME, TABLE_CATALOG, GRANTEE_NAME
            FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_ROLES
            WHERE PRIVILEGE = '{privilege.upper()}'
              AND DELETED_ON IS NULL
            """
            rows = self.connection.query(sql)

            for row in rows:
                grantee = row["GRANTEE_NAME"]
                if grantee not in role_names:
                    continue

                granted_on = row["GRANTED_ON"]
                name = row["NAME"]
                catalog = row["TABLE_CATALOG"]
                role_key = f"ACCOUNT_ROLE::{grantee}"

                if granted_on == "ACCOUNT":
                    result["account_wide"] = True
                    result["account_wide_roles"].append(role_key)

                elif granted_on == "DATABASE":
                    db_name = name
                    if scope:
                        scope_parts = scope.upper().split(".")
                        if scope_parts[0] == db_name:
                            result["databases"].append({"name": db_name, "via_role": role_key})
                    else:
                        result["databases"].append({"name": db_name, "via_role": role_key})

                elif granted_on == "SCHEMA":
                    schema_fqn = f"{catalog}.{name}" if catalog else name
                    if scope:
                        scope_upper = scope.upper()
                        if schema_fqn == scope_upper or schema_fqn.startswith(f"{scope_upper}."):
                            result["schemas"].append({"name": schema_fqn, "via_role": role_key})
                    else:
                        result["schemas"].append({"name": schema_fqn, "via_role": role_key})

        # Deduplicate (by name, keep role info)
        seen_dbs = {}
        for d in result["databases"]:
            seen_dbs.setdefault(d["name"], []).append(d["via_role"])
        result["databases"] = sorted(
            [{"name": k, "via_roles": sorted(set(v))} for k, v in seen_dbs.items()],
            key=lambda x: x["name"]
        )

        seen_schemas = {}
        for s in result["schemas"]:
            seen_schemas.setdefault(s["name"], []).append(s["via_role"])
        result["schemas"] = sorted(
            [{"name": k, "via_roles": sorted(set(v))} for k, v in seen_schemas.items()],
            key=lambda x: x["name"]
        )

        result["account_wide_roles"] = sorted(set(result["account_wide_roles"]))

        return result

    def collect_grants_for_object(self, object_type: str, object_name: str) -> List[AccessGrant]:
        """
        Fetch grants for a specific object on-demand.
        Uses ACCOUNT_USAGE for most types, falls back to SHOW GRANTS ON
        for types not tracked there (e.g., STREAMLIT).
        """
        obj_type_upper = object_type.upper()

        # Types not in GRANTS_TO_ROLES — use SHOW GRANTS ON
        show_grant_types = {"STREAMLIT", "NOTEBOOK", "DYNAMIC TABLE", "ALERT", "TAG", "SECRET"}
        if obj_type_upper in show_grant_types:
            return self._collect_grants_via_show(obj_type_upper, object_name)

        return self._collect_grants_via_account_usage(obj_type_upper, object_name)

    def _collect_grants_via_account_usage(self, object_type: str, object_name: str) -> List[AccessGrant]:
        """Fetch grants from ACCOUNT_USAGE.GRANTS_TO_ROLES for a specific object."""
        grants: list[AccessGrant] = []

        parts = object_name.upper().split(".")
        if len(parts) == 3:
            catalog, schema, name = parts
            name_filter = f"AND TABLE_CATALOG = '{catalog}' AND TABLE_SCHEMA = '{schema}' AND NAME = '{name}'"
        elif len(parts) == 2:
            catalog, name = parts
            name_filter = f"AND TABLE_CATALOG = '{catalog}' AND NAME = '{name}'"
        else:
            name_filter = f"AND NAME = '{parts[0]}'"

        with self.connection:
            sql = f"""
            SELECT
                GRANTEE_NAME,
                PRIVILEGE,
                GRANTED_ON,
                NAME,
                TABLE_CATALOG,
                TABLE_SCHEMA,
                GRANTED_BY,
                GRANTED_TO
            FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_ROLES
            WHERE GRANTED_ON = '{object_type}'
              AND DELETED_ON IS NULL
              {name_filter}
            """
            rows = self.connection.query(sql)

            for row in rows:
                grantee = row["GRANTEE_NAME"]
                granted_to = row["GRANTED_TO"]

                if granted_to == "DATABASE_ROLE":
                    catalog = row["TABLE_CATALOG"]
                    role_key = database_role(catalog, grantee)
                    role_type = "DATABASE"
                else:
                    role_key = account_role(grantee)
                    role_type = "ACCOUNT"

                obj_name = row["NAME"]
                catalog = row["TABLE_CATALOG"]
                schema_name = row["TABLE_SCHEMA"]

                if catalog and schema_name and obj_name:
                    fqn = f"{catalog}.{schema_name}.{obj_name}"
                elif catalog and obj_name:
                    fqn = f"{catalog}.{obj_name}"
                else:
                    fqn = obj_name or "<UNKNOWN>"

                grant = AccessGrant(
                    role=role_key,
                    privilege=row["PRIVILEGE"],
                    object=ObjectRef(
                        object_type=_parse_object_type(row["GRANTED_ON"]),
                        name=fqn,
                    ),
                    granted_on=row["GRANTED_ON"],
                    granted_by=row["GRANTED_BY"] or "",
                    inherited=False,
                    source_role=None,
                    role_type=role_type,
                )
                grants.append(grant)

        return grants

    def _collect_grants_via_show(self, object_type: str, object_name: str) -> List[AccessGrant]:
        """Fetch grants via SHOW GRANTS ON for types not in ACCOUNT_USAGE."""
        grants: list[AccessGrant] = []

        # Extract database from FQN for database role key construction
        parts = object_name.upper().split(".")
        obj_database = parts[0] if len(parts) >= 2 else None

        with self.connection:
            sql = f'SHOW GRANTS ON {object_type} {object_name}'
            rows = self.connection.query(sql)

            for row in rows:
                privilege = row["privilege"]
                granted_on = row["granted_on"]
                grantee = row["grantee_name"]
                granted_to = row["granted_to"]
                granted_by = row["granted_by"]

                if granted_to == "DATABASE_ROLE":
                    if obj_database:
                        role_key = database_role(obj_database, grantee)
                    else:
                        role_key = database_role("UNKNOWN", grantee)
                    role_type = "DATABASE"
                else:
                    role_key = account_role(grantee)
                    role_type = "ACCOUNT"

                grant = AccessGrant(
                    role=role_key,
                    privilege=privilege,
                    object=ObjectRef(
                        object_type=_parse_object_type(granted_on),
                        name=object_name.upper(),
                    ),
                    granted_on=granted_on,
                    granted_by=granted_by or "",
                    inherited=False,
                    source_role=None,
                    role_type=role_type,
                )
                grants.append(grant)

        return grants

    def collect_object_index(self) -> dict[str, list[str]]:
        """
        Collect a lightweight index of object FQNs grouped by type.
        Used for shell tab-completion. Only includes objects that have grants.
        Also enumerates object types not tracked in ACCOUNT_USAGE (e.g., STREAMLIT).
        """
        index: dict[str, list[str]] = {}

        with self.connection:
            # Bulk: objects tracked in GRANTS_TO_ROLES
            sql = """
            SELECT GRANTED_ON AS OBJECT_TYPE,
                   CONCAT(
                       COALESCE(TABLE_CATALOG, ''), '.',
                       COALESCE(TABLE_SCHEMA, ''), '.',
                       NAME
                   ) AS FQN
            FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_ROLES
            WHERE DELETED_ON IS NULL
              AND GRANTED_ON NOT IN ('ROLE', 'DATABASE_ROLE', 'ACCOUNT')
              AND NAME IS NOT NULL
            GROUP BY 1, 2
            """
            rows = self.connection.query(sql)

            for row in rows:
                obj_type = row["OBJECT_TYPE"]
                fqn = row["FQN"].strip(".")

                # Clean up FQNs — remove empty segments from NULL catalog/schema
                parts = [p for p in fqn.split(".") if p]
                clean_fqn = ".".join(parts)

                if clean_fqn:
                    index.setdefault(obj_type, [])
                    index[obj_type].append(clean_fqn)

            # Streamlits — not in GRANTS_TO_ROLES, enumerate via SHOW
            try:
                streamlits = self.connection.query("SHOW STREAMLITS IN ACCOUNT")
                for row in streamlits:
                    db = row["database_name"]
                    schema = row["schema_name"]
                    name = row["name"]
                    fqn = f"{db}.{schema}.{name}"
                    index.setdefault("STREAMLIT", [])
                    index["STREAMLIT"].append(fqn)
            except Exception:
                pass

            # Notebooks — not in GRANTS_TO_ROLES
            try:
                notebooks = self.connection.query("SHOW NOTEBOOKS IN ACCOUNT")
                for row in notebooks:
                    db = row["database_name"]
                    schema = row["schema_name"]
                    name = row["name"]
                    fqn = f"{db}.{schema}.{name}"
                    index.setdefault("NOTEBOOK", [])
                    index["NOTEBOOK"].append(fqn)
            except Exception:
                pass

            # Dynamic Tables — not in GRANTS_TO_ROLES
            try:
                dts = self.connection.query("SHOW DYNAMIC TABLES IN ACCOUNT")
                for row in dts:
                    db = row["database_name"]
                    schema = row["schema_name"]
                    name = row["name"]
                    fqn = f"{db}.{schema}.{name}"
                    index.setdefault("DYNAMIC TABLE", [])
                    index["DYNAMIC TABLE"].append(fqn)
            except Exception:
                pass

            # Alerts — not in GRANTS_TO_ROLES
            try:
                alerts = self.connection.query("SHOW ALERTS IN ACCOUNT")
                for row in alerts:
                    db = row["database_name"]
                    schema = row["schema_name"]
                    name = row["name"]
                    fqn = f"{db}.{schema}.{name}"
                    index.setdefault("ALERT", [])
                    index["ALERT"].append(fqn)
            except Exception:
                pass

        # Deduplicate and sort
        for key in index:
            index[key] = sorted(set(index[key]))

        return index

    def collect_extra_objects(self) -> dict[str, list[str]]:
        """
        Collect FQNs for object types NOT in GRANTS_TO_ROLES.
        These require SHOW commands and are stored separately for completions.
        """
        index: dict[str, list[str]] = {}

        with self.connection:
            # Streamlits
            try:
                rows = self.connection.query("SHOW STREAMLITS IN ACCOUNT")
                for row in rows:
                    fqn = f"{row['database_name']}.{row['schema_name']}.{row['name']}"
                    index.setdefault("STREAMLIT", []).append(fqn)
            except Exception:
                pass

            # Notebooks
            try:
                rows = self.connection.query("SHOW NOTEBOOKS IN ACCOUNT")
                for row in rows:
                    fqn = f"{row['database_name']}.{row['schema_name']}.{row['name']}"
                    index.setdefault("NOTEBOOK", []).append(fqn)
            except Exception:
                pass

            # Dynamic Tables
            try:
                rows = self.connection.query("SHOW DYNAMIC TABLES IN ACCOUNT")
                for row in rows:
                    fqn = f"{row['database_name']}.{row['schema_name']}.{row['name']}"
                    index.setdefault("DYNAMIC TABLE", []).append(fqn)
            except Exception:
                pass

            # Alerts
            try:
                rows = self.connection.query("SHOW ALERTS IN ACCOUNT")
                for row in rows:
                    fqn = f"{row['database_name']}.{row['schema_name']}.{row['name']}"
                    index.setdefault("ALERT", []).append(fqn)
            except Exception:
                pass

        # Deduplicate and sort
        for key in index:
            index[key] = sorted(set(index[key]))

        return index
