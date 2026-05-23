from snowglobe.engines.access.resolver import AccessResolver
from snowglobe.graphs.role_graph import RoleGraph
from snowglobe.graphs.user_graph import UserGraph
from snowglobe.models.access import AccessGrant
from snowglobe.models.object_ref import ObjectRef
from snowglobe.models.object_type import ObjectType
from snowglobe.output.cli import format_drift_text, format_user_report


def _make_grant(role, privilege, obj_type, obj_name):
    return AccessGrant(
        role=role,
        privilege=privilege,
        object=ObjectRef(object_type=obj_type, name=obj_name),
        granted_on=obj_type.value,
        granted_by="SECURITYADMIN",
        inherited=False,
        source_role=None,
        role_type="ACCOUNT",
    )


class TestResolverBugFix:
    """Test that all_access_paths_for_role correctly resolves inherited grants."""

    def test_inherited_grants_resolved(self):
        # Role hierarchy: ANALYST inherits from DATA_READER
        role_graph = RoleGraph({
            "ACCOUNT_ROLE::ANALYST": {"ACCOUNT_ROLE::DATA_READER"},
            "ACCOUNT_ROLE::DATA_READER": set(),
        })
        user_graph = UserGraph({"alice": ["ACCOUNT_ROLE::ANALYST"]})

        # Grant is on DATA_READER (the parent role)
        grant = _make_grant("ACCOUNT_ROLE::DATA_READER", "SELECT", ObjectType.TABLE, "DB.SCHEMA.T1")

        resolver = AccessResolver(
            grants=[grant],
            role_graph=role_graph,
            user_graph=user_graph,
        )

        # ANALYST should see this grant through inheritance
        paths = resolver.all_access_paths_for_role("ACCOUNT_ROLE::ANALYST")
        assert len(paths) >= 1
        assert any(p.grant.privilege == "SELECT" for p in paths)

    def test_direct_grants_still_work(self):
        role_graph = RoleGraph({
            "ACCOUNT_ROLE::ANALYST": set(),
        })
        user_graph = UserGraph({"alice": ["ACCOUNT_ROLE::ANALYST"]})

        grant = _make_grant("ACCOUNT_ROLE::ANALYST", "SELECT", ObjectType.TABLE, "DB.SCHEMA.T1")

        resolver = AccessResolver(
            grants=[grant],
            role_graph=role_graph,
            user_graph=user_graph,
        )

        paths = resolver.all_access_paths_for_role("ACCOUNT_ROLE::ANALYST")
        assert len(paths) == 1
        assert paths[0].grant.privilege == "SELECT"


class TestFormatDrift:
    def test_no_changes(self):
        drift = {
            "since": "2025-05-20T10:00:00",
            "grants_added": [],
            "grants_revoked": [],
            "roles_added": {},
            "roles_removed": {},
            "users_added": {},
            "users_removed": {},
        }
        output = format_drift_text(drift)
        assert "No access changes" in output

    def test_shows_added_grants(self):
        drift = {
            "since": "2025-05-20T10:00:00",
            "grants_added": [{"grantee": "ANALYST", "privilege": "SELECT", "fqn": "DB.S.T"}],
            "grants_revoked": [],
            "roles_added": {},
            "roles_removed": {},
            "users_added": {},
            "users_removed": {},
        }
        output = format_drift_text(drift)
        assert "Grants Added" in output
        assert "ANALYST" in output
        assert "SELECT" in output

    def test_shows_error(self):
        drift = {"error": "No previous refresh found."}
        output = format_drift_text(drift)
        assert "No previous refresh" in output


class TestFormatUserReport:
    def test_renders_report(self):
        report = {
            "username": "ALICE",
            "direct_roles": ["ACCOUNT_ROLE::ANALYST", "ACCOUNT_ROLE::PUBLIC"],
            "excluded_roles": [],
            "effective_roles": ["ACCOUNT_ROLE::ANALYST", "ACCOUNT_ROLE::PUBLIC", "ACCOUNT_ROLE::DATA_READER"],
            "role_count": 3,
            "grant_summary": {
                "TABLE": {"object_count": 50, "privileges": ["SELECT", "INSERT"], "objects": ["DB.S.T1"], "total_grants": 75},
                "VIEW": {"object_count": 10, "privileges": ["SELECT"], "objects": ["DB.S.V1"], "total_grants": 10},
            },
            "total_objects": 60,
            "total_grants": 85,
        }
        output = format_user_report(report)
        assert "ALICE" in output
        assert "Effective Roles: 3" in output
        assert "Total Accessible Objects: 60" in output
        assert "TABLE" in output
        assert "VIEW" in output
