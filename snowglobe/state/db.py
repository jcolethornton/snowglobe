"""
SQLite-backed state store for Snowglobe.

Stores all grants, role hierarchy, and user assignments in a single
indexed database for instant lookups. Replaces per-file JSON state.
"""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

STATE_DIR = Path.home() / ".snowglobe" / "state"
DB_FILE = "snowglobe.db"

SCHEMA_VERSION = 1

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS grants (
    grantee TEXT NOT NULL,
    privilege TEXT NOT NULL,
    granted_on TEXT NOT NULL,
    name TEXT,
    table_catalog TEXT,
    table_schema TEXT,
    granted_by TEXT,
    granted_to TEXT,
    fqn TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS role_edges (
    parent TEXT NOT NULL,
    child TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_roles (
    username TEXT NOT NULL,
    role TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS extra_objects (
    object_type TEXT NOT NULL,
    fqn TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cost_snapshots (
    snapshot_date TEXT NOT NULL,
    service_type TEXT NOT NULL,
    credits REAL NOT NULL,
    PRIMARY KEY (snapshot_date, service_type)
);

CREATE TABLE IF NOT EXISTS cost_warehouse_snapshots (
    snapshot_date TEXT NOT NULL,
    warehouse_name TEXT NOT NULL,
    credits REAL NOT NULL,
    PRIMARY KEY (snapshot_date, warehouse_name)
);

CREATE TABLE IF NOT EXISTS cost_user_snapshots (
    snapshot_date TEXT NOT NULL,
    user_name TEXT NOT NULL,
    warehouse_credits REAL DEFAULT 0,
    qa_credits REAL DEFAULT 0,
    cortex_functions REAL DEFAULT 0,
    cortex_analyst REAL DEFAULT 0,
    cortex_agent REAL DEFAULT 0,
    cortex_code REAL DEFAULT 0,
    snowflake_intelligence REAL DEFAULT 0,
    total_credits REAL NOT NULL,
    PRIMARY KEY (snapshot_date, user_name)
);

CREATE TABLE IF NOT EXISTS cost_trend_snapshots (
    snapshot_date TEXT NOT NULL,
    total_credits REAL NOT NULL,
    rolling_7d_avg REAL,
    PRIMARY KEY (snapshot_date)
);

CREATE TABLE IF NOT EXISTS cost_storage_snapshots (
    snapshot_date TEXT NOT NULL,
    database_name TEXT NOT NULL,
    active_bytes REAL DEFAULT 0,
    failsafe_bytes REAL DEFAULT 0,
    stage_bytes REAL DEFAULT 0,
    PRIMARY KEY (snapshot_date, database_name)
);

CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_grants_object ON grants(granted_on, table_catalog, table_schema, name);
CREATE INDEX IF NOT EXISTS idx_grants_fqn ON grants(granted_on, fqn);
CREATE INDEX IF NOT EXISTS idx_grants_grantee ON grants(grantee);
CREATE INDEX IF NOT EXISTS idx_grants_privilege ON grants(privilege);
CREATE INDEX IF NOT EXISTS idx_role_edges_parent ON role_edges(parent);
CREATE INDEX IF NOT EXISTS idx_role_edges_child ON role_edges(child);
CREATE INDEX IF NOT EXISTS idx_user_roles_user ON user_roles(username);
"""


class StateDB:
    """SQLite state backend for Snowglobe."""

    def __init__(self, path: Optional[str] = None):
        base = Path(path) if path else STATE_DIR
        base.mkdir(parents=True, exist_ok=True)
        self.db_path = base / DB_FILE
        self._conn: Optional[sqlite3.Connection] = None
        self._ensure_schema()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        return self._conn

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def _ensure_schema(self):
        conn = self.conn
        conn.executescript(SCHEMA_SQL)
        conn.commit()

    # --- Metadata ---

    def get_metadata(self, key: str) -> Optional[str]:
        row = self.conn.execute(
            "SELECT value FROM metadata WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def set_metadata(self, key: str, value: str):
        self.conn.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
            (key, value),
        )
        self.conn.commit()

    def get_json_cache(self, key: str) -> Optional[list[dict]]:
        """Retrieve a JSON-serialized list of dicts from metadata."""
        import json
        raw = self.get_metadata(key)
        if not raw:
            return None
        return json.loads(raw)

    def set_json_cache(self, key: str, data: list[dict]):
        """Store a list of dicts as JSON in metadata."""
        import json
        self.set_metadata(key, json.dumps(data))

    def get_refreshed_at(self) -> Optional[str]:
        return self.get_metadata("refreshed_at")

    def set_refreshed_at(self):
        self.set_metadata(
            "refreshed_at", datetime.now(timezone.utc).isoformat()
        )

    def has_state(self) -> bool:
        """Check if any grants exist in the database."""
        row = self.conn.execute("SELECT COUNT(*) as cnt FROM grants").fetchone()
        return row["cnt"] > 0

    # --- Full refresh (bulk replace) ---

    def save_grants(self, rows: list[dict]):
        """Replace all grants with new data."""
        conn = self.conn
        conn.execute("DELETE FROM grants")
        conn.executemany(
            """INSERT INTO grants
               (grantee, privilege, granted_on, name, table_catalog, table_schema, granted_by, granted_to, fqn)
               VALUES (:grantee, :privilege, :granted_on, :name, :table_catalog, :table_schema, :granted_by, :granted_to, :fqn)""",
            rows,
        )
        conn.commit()

    def save_role_edges(self, edges: list[tuple]):
        """Replace all role hierarchy edges. Each tuple is (parent_key, child_key)."""
        conn = self.conn
        conn.execute("DELETE FROM role_edges")
        conn.executemany(
            "INSERT INTO role_edges (parent, child) VALUES (?, ?)", edges
        )
        conn.commit()

    def save_user_roles(self, assignments: dict):
        """Replace all user role assignments. Dict of username -> [role_keys]."""
        conn = self.conn
        conn.execute("DELETE FROM user_roles")
        rows = []
        for username, roles in assignments.items():
            for role in roles:
                rows.append((username, role))
        conn.executemany(
            "INSERT INTO user_roles (username, role) VALUES (?, ?)", rows
        )
        conn.commit()

    def save_extra_objects(self, objects: dict[str, list[str]]):
        """
        Replace extra objects (types not in GRANTS_TO_ROLES).
        Dict of object_type -> [fqn_list].
        """
        conn = self.conn
        conn.execute("DELETE FROM extra_objects")
        rows = []
        for obj_type, fqns in objects.items():
            for fqn in fqns:
                rows.append((obj_type, fqn))
        if rows:
            conn.executemany(
                "INSERT INTO extra_objects (object_type, fqn) VALUES (?, ?)", rows
            )
        conn.commit()

    # --- Incremental refresh ---

    def upsert_grants_incremental(self, upserts: list[dict], deletes: list[dict]):
        """
        Apply incremental grant changes.
        Deletes matched by (grantee, privilege, granted_on, fqn).
        Upserts: delete existing then insert.
        """
        conn = self.conn
        delete_sql = """DELETE FROM grants
                        WHERE grantee = :grantee AND privilege = :privilege
                        AND granted_on = :granted_on AND fqn = :fqn"""

        for d in deletes:
            conn.execute(delete_sql, d)

        for u in upserts:
            conn.execute(delete_sql, u)

        if upserts:
            conn.executemany(
                """INSERT INTO grants
                   (grantee, privilege, granted_on, name, table_catalog, table_schema, granted_by, granted_to, fqn)
                   VALUES (:grantee, :privilege, :granted_on, :name, :table_catalog, :table_schema, :granted_by, :granted_to, :fqn)""",
                upserts,
            )
        conn.commit()

    def upsert_role_edges_incremental(self, added: list[tuple], removed: list[tuple]):
        """Apply incremental role edge changes."""
        conn = self.conn
        for parent, child in removed:
            conn.execute(
                "DELETE FROM role_edges WHERE parent = ? AND child = ?",
                (parent, child),
            )
        if added:
            conn.executemany(
                "INSERT INTO role_edges (parent, child) VALUES (?, ?)", added
            )
        conn.commit()

    def upsert_user_roles_incremental(self, added: dict, removed: dict):
        """
        Apply incremental user role changes.
        added/removed: {username: [role_keys]}
        """
        conn = self.conn
        for username, roles in removed.items():
            for role in roles:
                conn.execute(
                    "DELETE FROM user_roles WHERE username = ? AND role = ?",
                    (username, role),
                )
        rows = []
        for username, roles in added.items():
            for role in roles:
                rows.append((username, role))
        if rows:
            conn.executemany(
                "INSERT INTO user_roles (username, role) VALUES (?, ?)", rows
            )
        conn.commit()

    # --- Query: grants for object ---

    def query_grants_for_object(self, granted_on: str, object_name: str) -> list[dict]:
        """
        Lookup all grants for a specific object.
        Returns list of dicts with grant fields.
        """
        fqn = object_name.upper()
        rows = self.conn.execute(
            """SELECT grantee, privilege, granted_on, name, table_catalog,
                      table_schema, granted_by, granted_to, fqn
               FROM grants
               WHERE granted_on = ? AND fqn = ?""",
            (granted_on.upper(), fqn),
        ).fetchall()
        return [dict(r) for r in rows]

    # --- Query: grants by grantee ---

    def query_grants_by_grantees(self, grantee_keys: set) -> list[dict]:
        """Lookup all grants held by a set of role keys."""
        if not grantee_keys:
            return []
        placeholders = ",".join("?" * len(grantee_keys))
        rows = self.conn.execute(
            f"""SELECT grantee, privilege, granted_on, name, table_catalog,
                       table_schema, granted_by, granted_to, fqn
                FROM grants
                WHERE grantee IN ({placeholders})""",
            list(grantee_keys),
        ).fetchall()
        return [dict(r) for r in rows]

    # --- Query: CREATE grants ---

    def query_create_grants(
        self, privilege: str, grantee_keys: set, scope: Optional[str] = None
    ) -> list[dict]:
        """Lookup CREATE grants for a set of role keys, optionally filtered by scope."""
        if not grantee_keys:
            return []
        placeholders = ",".join("?" * len(grantee_keys))
        params: list = list(grantee_keys)

        sql = f"""SELECT grantee, privilege, granted_on, name, table_catalog, fqn
                  FROM grants
                  WHERE privilege = ? AND grantee IN ({placeholders})"""
        params = [privilege.upper()] + list(grantee_keys)

        if scope:
            parts = scope.upper().split(".")
            if len(parts) == 2:
                sql += " AND table_catalog = ? AND name = ?"
                params.extend(parts)
            elif len(parts) == 1:
                sql += " AND table_catalog = ?"
                params.append(parts[0])

        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    # --- Query: object index (for completions) ---

    def query_object_index(self) -> dict[str, list[str]]:
        """
        Get distinct object FQNs grouped by type.
        Used for shell tab-completion.
        Includes extra_objects (STREAMLIT, NOTEBOOK, etc. from SHOW commands).
        """
        rows = self.conn.execute(
            """SELECT DISTINCT granted_on AS object_type, fqn
               FROM grants
               WHERE granted_on NOT IN ('ACCOUNT')
               AND fqn != ''
               UNION ALL
               SELECT object_type, fqn FROM extra_objects"""
        ).fetchall()

        index: dict[str, list[str]] = {}
        for row in rows:
            obj_type = row["object_type"]
            fqn = row["fqn"]
            index.setdefault(obj_type, []).append(fqn)

        # Deduplicate and sort
        for key in index:
            index[key] = sorted(set(index[key]))

        return index

    # --- Load role graph / user graph into memory ---

    def load_role_graph_data(self) -> dict[str, list[str]]:
        """Load role edges as {parent: [children]} dict for RoleGraph construction."""
        rows = self.conn.execute("SELECT parent, child FROM role_edges").fetchall()
        data: dict[str, list[str]] = {}
        for row in rows:
            data.setdefault(row["parent"], []).append(row["child"])
        return data

    def load_user_roles_data(self) -> dict[str, list[str]]:
        """Load user roles as {username: [role_keys]} dict for UserGraph construction."""
        rows = self.conn.execute("SELECT username, role FROM user_roles").fetchall()
        data: dict[str, list[str]] = {}
        for row in rows:
            data.setdefault(row["username"], []).append(row["role"])
        return data

    # --- Cost snapshot persistence ---

    def save_cost_summary_snapshot(self, date: str, rows: list[dict]):
        """Save account cost summary for a date. Upserts (replaces existing for same date)."""
        conn = self.conn
        conn.execute("DELETE FROM cost_snapshots WHERE snapshot_date = ?", (date,))
        for row in rows:
            conn.execute(
                "INSERT INTO cost_snapshots (snapshot_date, service_type, credits) VALUES (?, ?, ?)",
                (date, row["SERVICE_TYPE"], float(row["CREDITS"])),
            )
        conn.commit()

    def save_cost_warehouse_snapshot(self, date: str, rows: list[dict]):
        """Save warehouse cost breakdown for a date."""
        conn = self.conn
        conn.execute("DELETE FROM cost_warehouse_snapshots WHERE snapshot_date = ?", (date,))
        for row in rows:
            conn.execute(
                "INSERT INTO cost_warehouse_snapshots (snapshot_date, warehouse_name, credits) VALUES (?, ?, ?)",
                (date, row["WAREHOUSE_NAME"], float(row["TOTAL_CREDITS"])),
            )
        conn.commit()

    def save_cost_user_snapshot(self, date: str, rows: list[dict]):
        """Save user cost breakdown for a date."""
        conn = self.conn
        conn.execute("DELETE FROM cost_user_snapshots WHERE snapshot_date = ?", (date,))
        for row in rows:
            conn.execute(
                """INSERT INTO cost_user_snapshots
                   (snapshot_date, user_name, warehouse_credits, qa_credits,
                    cortex_functions, cortex_analyst, cortex_agent, cortex_code,
                    snowflake_intelligence, total_credits)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (date, row["USER_NAME"],
                 float(row.get("WAREHOUSE_CREDITS", 0)),
                 float(row.get("QA_CREDITS", 0)),
                 float(row.get("CORTEX_FUNCTIONS", 0)),
                 float(row.get("CORTEX_ANALYST", 0)),
                 float(row.get("CORTEX_AGENT", 0)),
                 float(row.get("CORTEX_CODE", 0)),
                 float(row.get("SNOWFLAKE_INTELLIGENCE", 0)),
                 float(row.get("TOTAL_CREDITS", 0))),
            )
        conn.commit()

    # --- Cost cache reads ---

    def get_cost_cache_age(self, cache_key: str) -> Optional[float]:
        """Return age in seconds of a cost cache entry, or None if not cached."""
        fetched_at = self.get_metadata(cache_key)
        if not fetched_at:
            return None
        fetched_dt = datetime.fromisoformat(fetched_at)
        age = (datetime.now(timezone.utc) - fetched_dt).total_seconds()
        return age

    def get_cost_summary_cache(self) -> Optional[list[dict]]:
        """Read cached cost summary snapshot (today's date)."""
        from datetime import date
        today = date.today().isoformat()
        rows = self.conn.execute(
            "SELECT service_type AS SERVICE_TYPE, credits AS CREDITS FROM cost_snapshots WHERE snapshot_date = ?",
            (today,),
        ).fetchall()
        if not rows:
            return None
        return [dict(r) for r in rows]

    def get_cost_warehouse_cache(self) -> Optional[list[dict]]:
        """Read cached warehouse cost snapshot (today's date)."""
        from datetime import date
        today = date.today().isoformat()
        rows = self.conn.execute(
            "SELECT warehouse_name AS WAREHOUSE_NAME, credits AS TOTAL_CREDITS FROM cost_warehouse_snapshots WHERE snapshot_date = ?",
            (today,),
        ).fetchall()
        if not rows:
            return None
        return [dict(r) for r in rows]

    def get_cost_user_cache(self) -> Optional[list[dict]]:
        """Read cached user cost snapshot (today's date)."""
        from datetime import date
        today = date.today().isoformat()
        rows = self.conn.execute(
            """SELECT user_name AS USER_NAME, warehouse_credits AS WAREHOUSE_CREDITS,
                      qa_credits AS QA_CREDITS, cortex_functions AS CORTEX_FUNCTIONS,
                      cortex_analyst AS CORTEX_ANALYST, cortex_agent AS CORTEX_AGENT,
                      cortex_code AS CORTEX_CODE, snowflake_intelligence AS SNOWFLAKE_INTELLIGENCE,
                      total_credits AS TOTAL_CREDITS
               FROM cost_user_snapshots WHERE snapshot_date = ?""",
            (today,),
        ).fetchall()
        if not rows:
            return None
        return [dict(r) for r in rows]

    # --- Cost trend snapshots ---

    def save_cost_trend_snapshot(self, rows: list[dict]):
        """Save daily cost trend data. Each row has snapshot_date, total_credits, rolling_7d_avg."""
        conn = self.conn
        for row in rows:
            conn.execute(
                "INSERT OR REPLACE INTO cost_trend_snapshots (snapshot_date, total_credits, rolling_7d_avg) VALUES (?, ?, ?)",
                (row["snapshot_date"], float(row["total_credits"]), row.get("rolling_7d_avg")),
            )
        conn.commit()

    def get_cost_trend_cache(self, days: int) -> Optional[list[dict]]:
        """Read cached daily trend data for last N days."""
        from datetime import date, timedelta
        start = (date.today() - timedelta(days=days)).isoformat()
        rows = self.conn.execute(
            """SELECT snapshot_date, total_credits, rolling_7d_avg
               FROM cost_trend_snapshots
               WHERE snapshot_date >= ?
               ORDER BY snapshot_date""",
            (start,),
        ).fetchall()
        if not rows:
            return None
        return [dict(r) for r in rows]

    # --- Cost storage snapshots ---

    def save_cost_storage_snapshot(self, date: str, rows: list[dict]):
        """Save per-database storage usage for a date."""
        conn = self.conn
        conn.execute("DELETE FROM cost_storage_snapshots WHERE snapshot_date = ?", (date,))
        for row in rows:
            conn.execute(
                """INSERT INTO cost_storage_snapshots
                   (snapshot_date, database_name, active_bytes, failsafe_bytes, stage_bytes)
                   VALUES (?, ?, ?, ?, ?)""",
                (date, row["DATABASE_NAME"],
                 float(row.get("ACTIVE_BYTES", 0)),
                 float(row.get("FAILSAFE_BYTES", 0)),
                 float(row.get("STAGE_BYTES", 0))),
            )
        conn.commit()

    def get_cost_storage_cache(self) -> Optional[list[dict]]:
        """Read cached storage snapshot (today's date)."""
        from datetime import date
        today = date.today().isoformat()
        rows = self.conn.execute(
            """SELECT database_name AS DATABASE_NAME, active_bytes AS ACTIVE_BYTES,
                      failsafe_bytes AS FAILSAFE_BYTES, stage_bytes AS STAGE_BYTES
               FROM cost_storage_snapshots WHERE snapshot_date = ?""",
            (today,),
        ).fetchall()
        if not rows:
            return None
        return [dict(r) for r in rows]

