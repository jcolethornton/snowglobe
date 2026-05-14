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
    Collects Snowflake access metadata.
    
    Provides:
      - Role hierarchy
      - Direct object grants
      - User roles
    """

    def __init__(self, connection):
        """
        connection: SnowflakeReadOnly instance
        """
        self.connection = connection

    def collect_user_roles(self) -> UserGraph:
        """
        Collect all users and their directly assigned roles.
        Returns a UserGraph object.
        """
        users_data = {}

        with self.connection:
            users = self.connection.query("SHOW USERS")
            for row in users:
                username = row["name"]
                grants = self.connection.query(f'SHOW GRANTS TO USER "{username}"')
                assigned_roles = []

                for r in grants:
                    if r["granted_on"] == "ROLE":
                        assigned_roles.append(account_role(r["role"]))
                    elif r["granted_on"] == "DATABASE_ROLE":
                        db, role_name = r["role"].split(".")
                        assigned_roles.append(database_role(db, role_name))

                users_data[username] = assigned_roles

        return UserGraph(users_data)

    def collect_role_graph(self) -> RoleGraph:
        """
        Build role inheritance graph including account and database roles.
        """
        parents = defaultdict(set)

        with self.connection:
            # 1️⃣ Account roles
            account_roles = self.connection.query("SHOW ROLES")
            for row in account_roles:
                role = row["name"]
                grants = self.connection.query(f'SHOW GRANTS TO ROLE "{role}"')
                for g in grants:
                    if g["granted_on"] == "ROLE":
                        parents[account_role(role)].add(account_role(g["role"]))
                    elif g["granted_on"] == "DATABASE_ROLE":
                        db, db_role = g["role"].split(".")
                        parents[account_role(role)].add(database_role(db, db_role))

            # 2️⃣ Database roles
            databases = self.connection.query("SHOW DATABASES")
            for db_row in databases:
                db = db_row["name"]
                db_roles = self.connection.query(f'SHOW DATABASE ROLES IN DATABASE "{db}"')
                for r in db_roles:
                    role_name = r["name"]
                    grants = self.connection.query(f'SHOW GRANTS TO DATABASE ROLE "{db}"."{role_name}"')
                    for g in grants:
                        if g["granted_on"] == "DATABASE_ROLE":
                            parent_db, parent_role = g["role"].split(".")
                            parents[database_role(db, role_name)].add(database_role(parent_db, parent_role))

        return RoleGraph(parents)

    def collect_direct_grants(self) -> List[AccessGrant]:
        """
        Collect all direct object grants from Snowflake (no inheritance applied yet)
        """
        grants: list[AccessGrant] = []

        with self.connection:
            # 1️⃣ Account roles
            account_roles = self.connection.query("SHOW ROLES")
            for row in account_roles:
                role = row["name"]
                rows = self.connection.query(f'SHOW GRANTS TO ROLE "{role}"')
                for g in rows:
                    if g["granted_on"] == "ROLE":
                        continue
                    grant = AccessGrant(
                        role=account_role(role),
                        privilege=g["privilege"],
                        object=ObjectRef(
                            object_type=_parse_object_type(g.get("object_type") or g["granted_on"]),
                            name=g.get("object_name") or "<UNKNOWN>",
                        ),
                        granted_on=g["granted_on"],
                        granted_by=g["granted_by"],
                        inherited=False,
                        source_role=None,
                        role_type="ACCOUNT"
                    )
                    grants.append(grant)

            # 2️⃣ Database roles
            databases = self.connection.query("SHOW DATABASES")
            for db_row in databases:
                db = db_row["name"]
                db_roles = self.connection.query(f'SHOW DATABASE ROLES IN DATABASE "{db}"')
                for r in db_roles:
                    role_name = r["name"]
                    rows = self.connection.query(f'SHOW GRANTS TO DATABASE ROLE "{db}"."{role_name}"')
                    for g in rows:
                        if g["granted_on"] == "DATABASE_ROLE":
                            continue

                        grant = AccessGrant(
                            role=database_role(db, role_name),
                            privilege=g["privilege"],
                            object=ObjectRef(
                                object_type=_parse_object_type(g.get("object_type") or g["granted_on"]),
                                name=g.get("object_name") or "<UNKNOWN>",
                            ),
                            granted_on=g["granted_on"],
                            granted_by=g["granted_by"],
                            inherited=False,
                            source_role=None,
                            role_type="DATABASE"
                        )
                        grants.append(grant)

        return grants
