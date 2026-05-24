"""
Risk and privilege-escalation analysis for Snowglobe.

Surfaces:
- Privilege escalation paths from each role to privileged admin roles
- Direct dangerous grants (MANAGE GRANTS, CREATE ROLE/USER, OWNERSHIP on DB/WAREHOUSE)
- Dormant users (inactive >N days) holding risk-bearing roles
- Per-scan diff against the previous scan stored in the SQLite cache

Returns plain dicts so the shell, the eventual TUI, and any external caller
can render them however they like.
"""
import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from snowglobe.state.db import StateDB
from snowglobe.graphs.role_graph import RoleGraph
from snowglobe.graphs.user_graph import UserGraph


PRIVILEGED_ROLES = {
    "ACCOUNT_ROLE::ACCOUNTADMIN",
    "ACCOUNT_ROLE::SYSADMIN",
    "ACCOUNT_ROLE::SECURITYADMIN",
    "ACCOUNT_ROLE::USERADMIN",
}

TARGET_WEIGHTS = {
    "ACCOUNT_ROLE::ACCOUNTADMIN": 10,
    "ACCOUNT_ROLE::SECURITYADMIN": 8,
    "ACCOUNT_ROLE::SYSADMIN": 7,
    "ACCOUNT_ROLE::USERADMIN": 6,
}
DEFAULT_TARGET_WEIGHT = 5

DORMANT_DAYS_DEFAULT = 90


class RiskService:
    """Privilege escalation, dangerous grants, and dormant user detection."""

    def __init__(self, context):
        self.context = context
        self.context.load_profile()
        self.db = StateDB()

    # --- Pure scoring ---

    @staticmethod
    def calculate_risk_score(hops: int, user_count: int, target: str) -> float:
        """Composite: target_weight * (1/hops) * log2(user_count + 2)."""
        weight = TARGET_WEIGHTS.get(target, DEFAULT_TARGET_WEIGHT)
        return round(weight * (1 / max(hops, 1)) * math.log2(user_count + 2), 1)

    # --- Privileged target discovery ---

    def get_privileged_targets(self) -> set[str]:
        """
        Built-in admin roles plus any role with dangerous account-level grants,
        database OWNERSHIP, or IMPORTED PRIVILEGES on SNOWFLAKE.
        """
        targets = set(PRIVILEGED_ROLES)

        rows = self.db.conn.execute(
            """SELECT DISTINCT grantee FROM grants
               WHERE privilege IN ('MANAGE GRANTS', 'CREATE ROLE', 'CREATE USER')
                 AND granted_on = 'ACCOUNT'"""
        ).fetchall()
        targets.update(row["grantee"] for row in rows)

        rows = self.db.conn.execute(
            """SELECT DISTINCT grantee FROM grants
               WHERE privilege = 'OWNERSHIP'
                 AND granted_on = 'DATABASE'"""
        ).fetchall()
        targets.update(row["grantee"] for row in rows)

        rows = self.db.conn.execute(
            """SELECT DISTINCT grantee FROM grants
               WHERE privilege = 'IMPORTED PRIVILEGES'
                 AND fqn = 'SNOWFLAKE'"""
        ).fetchall()
        targets.update(row["grantee"] for row in rows)

        return targets

    def get_dangerous_direct_grants(self) -> list[dict]:
        """Roles with dangerous direct grants, independent of inheritance."""
        rows = self.db.conn.execute(
            """SELECT grantee AS ROLE,
                      privilege AS PRIVILEGE,
                      granted_on AS OBJECT_TYPE,
                      fqn AS OBJECT
               FROM grants
               WHERE (privilege IN ('MANAGE GRANTS', 'CREATE ROLE', 'CREATE USER', 'IMPORTED PRIVILEGES')
                      AND granted_on = 'ACCOUNT')
                  OR (privilege = 'OWNERSHIP' AND granted_on IN ('DATABASE', 'WAREHOUSE'))
               ORDER BY privilege, grantee"""
        ).fetchall()
        return [dict(r) for r in rows]

    # --- Single-role escalation ---

    def check_escalation(
        self,
        role: str,
        role_graph: RoleGraph,
        user_graph: UserGraph,
    ) -> dict:
        """
        Can a single role reach admin privileges via inheritance?
        """
        targets = self.get_privileged_targets()

        if role in targets:
            return {
                "role": role,
                "is_privileged": True,
                "reachable_targets": [],
                "affected_users": {"direct": [], "inherited": []},
            }

        ancestors = role_graph.all_ancestors(role)
        reachable = ancestors & targets

        reachable_list = []
        for target in sorted(reachable):
            path = role_graph.shortest_path(role, target)
            if path:
                reachable_list.append({
                    "target": target,
                    "hops": len(path) - 1,
                    "path": path,
                })

        direct_users, inherited_users = self._users_with_role(role, role_graph, user_graph)

        return {
            "role": role,
            "is_privileged": False,
            "reachable_targets": reachable_list,
            "affected_users": {
                "direct": sorted(direct_users),
                "inherited": sorted(inherited_users),
            },
        }

    # --- Full scan ---

    def run_scan(
        self,
        role_graph: RoleGraph,
        user_graph: UserGraph,
        dormant_days: int = DORMANT_DAYS_DEFAULT,
    ) -> dict:
        """
        Scan all roles for escalation paths and return a structured result
        including risk-scored flagged roles, dormant users, dangerous direct
        grants, and a diff against the previous scan if available.
        """
        targets = self.get_privileged_targets()
        all_roles = role_graph.all_roles()

        is_admin: list[str] = []
        no_path: list[str] = []
        flagged: list[dict] = []

        for role in sorted(all_roles):
            if role in targets:
                is_admin.append(role)
                continue

            ancestors = role_graph.all_ancestors(role)
            reachable = ancestors & targets

            if not reachable:
                no_path.append(role)
                continue

            best_path = None
            best_target = None
            for target in reachable:
                path = role_graph.shortest_path(role, target)
                if path and (best_path is None or len(path) < len(best_path)):
                    best_path = path
                    best_target = target

            if not best_path:
                no_path.append(role)
                continue

            hops = len(best_path) - 1
            direct_users, inherited_users = self._users_with_role(role, role_graph, user_graph)
            user_count = len(direct_users) + len(inherited_users)

            flagged.append({
                "role": role,
                "target": best_target,
                "hops": hops,
                "path": best_path,
                "user_count": user_count,
                "risk_score": self.calculate_risk_score(hops, user_count, best_target),
            })

        flagged.sort(key=lambda e: e["risk_score"], reverse=True)

        high_risk = [e for e in flagged if e["risk_score"] >= 10]
        medium_risk = [e for e in flagged if 5 <= e["risk_score"] < 10]
        low_risk = [e for e in flagged if e["risk_score"] < 5]

        diff = self._diff_with_previous(flagged)
        self._save_scan_snapshot(flagged)

        dangerous_grants = self.get_dangerous_direct_grants()
        dormant_users = self._get_dormant_users(flagged, role_graph, user_graph, days=dormant_days)

        return {
            "scan_date": datetime.now(timezone.utc).isoformat(),
            "is_admin": is_admin,
            "no_path": no_path,
            "flagged": flagged,
            "high_risk": high_risk,
            "medium_risk": medium_risk,
            "low_risk": low_risk,
            "dangerous_grants": dangerous_grants,
            "dormant_users": dormant_users,
            "diff": diff,
            "summary": {
                "admin_roles": len(is_admin),
                "high_risk": len(high_risk),
                "medium_risk": len(medium_risk),
                "low_risk": len(low_risk),
                "no_path": len(no_path),
                "direct_privilege_risks": len(dangerous_grants),
                "dormant_with_risk": len({d["user"] for d in dormant_users}),
                "total_scanned": len(all_roles),
            },
        }

    # --- Internals ---

    def _users_with_role(
        self,
        role: str,
        role_graph: RoleGraph,
        user_graph: UserGraph,
    ) -> tuple[list[str], list[str]]:
        direct: list[str] = []
        inherited: list[str] = []
        for user, assigned in user_graph.assigned_roles.items():
            if role in assigned:
                direct.append(user)
                continue
            effective = set(assigned)
            for r in assigned:
                effective |= role_graph.all_ancestors(r)
            if role in effective:
                inherited.append(user)
        return direct, inherited

    def _diff_with_previous(self, current_flagged: list[dict]) -> dict | None:
        previous = self.db.get_json_cache("scan_results_last")
        if not previous:
            return None
        prev_roles = {r["role"] for r in previous}
        curr_roles = {e["role"] for e in current_flagged}
        new_roles = curr_roles - prev_roles
        resolved = prev_roles - curr_roles
        return {
            "new": sorted(new_roles),
            "resolved": sorted(resolved),
            "new_details": [e for e in current_flagged if e["role"] in new_roles],
        }

    def _save_scan_snapshot(self, flagged: list[dict]) -> None:
        snapshot = [
            {"role": e["role"], "target": e["target"], "hops": e["hops"],
             "risk_score": e["risk_score"], "user_count": e["user_count"]}
            for e in flagged
        ]
        self.db.set_json_cache("scan_results_last", snapshot)

    def _get_dormant_users(
        self,
        flagged: list[dict],
        role_graph: RoleGraph,
        user_graph: UserGraph,
        days: int = DORMANT_DAYS_DEFAULT,
    ) -> list[dict]:
        """
        Cross-reference flagged roles against users inactive >`days`.
        Returns one entry per (user, role) pair; callers can dedupe by user
        if they only want to list each user once.
        """
        try:
            conn = self.context.connect()
            with conn:
                rows = conn.query(f"""
                    SELECT NAME, LAST_SUCCESS_LOGIN
                    FROM SNOWFLAKE.ACCOUNT_USAGE.USERS
                    WHERE (LAST_SUCCESS_LOGIN < DATEADD(day, -{days}, CURRENT_TIMESTAMP())
                           OR LAST_SUCCESS_LOGIN IS NULL)
                      AND DELETED_ON IS NULL
                      AND DISABLED = 'false'
                """)
        except Exception:
            return []

        dormant_names = {row["NAME"] for row in rows}
        results: list[dict] = []
        for entry in flagged:
            role = entry["role"]
            for user, assigned in user_graph.assigned_roles.items():
                if user not in dormant_names:
                    continue
                if role in assigned:
                    results.append({"user": user, "role": role, "risk_score": entry["risk_score"]})
                    continue
                effective = set(assigned)
                for r in assigned:
                    effective |= role_graph.all_ancestors(r)
                if role in effective:
                    results.append({"user": user, "role": role, "risk_score": entry["risk_score"]})
        return results

    # --- Exports ---

    @staticmethod
    def export_scan_csv(flagged: list[dict], path: str) -> None:
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["role", "target", "hops", "risk_score", "user_count", "path"],
            )
            writer.writeheader()
            for e in flagged:
                writer.writerow({
                    "role": e["role"],
                    "target": e["target"],
                    "hops": e["hops"],
                    "risk_score": e["risk_score"],
                    "user_count": e["user_count"],
                    "path": " → ".join(e["path"]),
                })

    @staticmethod
    def export_scan_json(scan_result: dict, path: str, dormant_cap: int = 50) -> None:
        export = {
            "scan_date": scan_result["scan_date"],
            "flagged_roles": scan_result["flagged"],
            "direct_privilege_risks": scan_result["dangerous_grants"],
            "dormant_users": scan_result["dormant_users"][:dormant_cap],
            "summary": scan_result["summary"],
        }
        Path(path).write_text(json.dumps(export, indent=2, default=str))
