from collections import defaultdict
from typing import Dict, List, Optional

from snowglobe.models.access import AccessGrant
from snowglobe.graphs.role_graph import RoleGraph
from snowglobe.graphs.user_graph import UserGraph
from snowglobe.models.access_path import AccessPath
from snowglobe.models.privilege import Privilege


class AccessResolver:
    """
    Lazy resolver for direct + inherited grants.
    and anything inherited from them.
    """

    def __init__(
        self,
        grants: List[AccessGrant],
        role_graph: RoleGraph,
        user_graph: UserGraph
    ):
        self.grants = grants
        self.role_graph = role_graph
        self.user_graph = user_graph
        self.privilege = Privilege

        # Caches
        self._grants_by_role: Dict[str, List[AccessGrant]] = defaultdict(list)
        self.grant_cache()


    def grant_cache(self):
        for g in self.grants:
            self._grants_by_role[g.role].append(g)


    def grants_for_user(
        self,
        username: str,
        object_db: str | None = None,
    ) -> List[AccessGrant]:
        """
        Return all effective grants for a user.
        Filter database roles by database.
        """
        effective_roles = self.user_graph.effective_roles(username, self.role_graph)

        resolved: List[AccessGrant] = []

        for role in effective_roles:
            for g in self._grants_by_role.get(role, []):
                if object_db and g.role_type == "DATABASE":
                    if not g.role.startswith(f"DATABASE_ROLE::{object_db}::"):
                        continue
                resolved.append(g)

        return resolved

    def all_access_paths_for_user(self, username: str):
        """
        Return all access paths from a user's roles to grants
        """
        paths: List[AccessPath] = []
        user_roles = self.user_graph.roles_of(username)[0]

        for user_role in user_roles:
            effective_roles = {user_role} | self.user_graph.effective_roles(username, self.role_graph)
            for role in effective_roles:
                for grant in self._grants_by_role.get(role, []):

                    chains = self.role_graph.all_paths(user_role, role)

                    for chain in chains:
                        paths.append(AccessPath(id=username, role_chain=chain, grant=grant))

        return paths 

    def access_paths_for_user(
        self,
        username: str,
        object_type: str,
        object_name: str,
        privilege: str,
    ):
        """
        Return all access paths from a user's roles to grants matching the requested object and privilege
        """
        paths: List[AccessPath] = []
        user_roles = self.user_graph.roles_of(username)[0]

        for user_role in user_roles:
            effective_roles = {user_role} | self.user_graph.effective_roles(username, self.role_graph)
            for role in effective_roles:
                for grant in self._grants_by_role.get(role, []):
                    if not self.privilege.matches(grant.privilege, privilege):
                        continue
                    if grant.object.object_type != object_type:
                        continue
                    if grant.object.name != object_name:
                        continue

                    chains = self.role_graph.all_paths(user_role, role)

                    for chain in chains:
                        paths.append(AccessPath(id=username, role_chain=chain, grant=grant))
        return paths 

    def all_access_paths_for_role(self, role: str):
        """
        Return all access paths from a role to grants
        """
        paths: List[AccessPath] = []

        effective_roles = {role} | self.role_graph.all_ancestors(role)
        for inherited_role in effective_roles:
            for grant in self._grants_by_role.get(role, []):

                chains = self.role_graph.all_paths(role, inherited_role)

                for chain in chains:
                    paths.append(AccessPath(id=role, role_chain=chain, grant=grant))

        return paths

    def access_paths_for_role(
        self,
        role: str,
        object_type,
        object_name: str,
        privilege: str,
    ):
        """
        Return all access paths from a role to grants matching the requested object and privilege
        """
        paths: List[AccessPath] = []

        effective_roles = {role} | self.role_graph.all_ancestors(role)
        for inherited_role in effective_roles:
            for grant in self._grants_by_role.get(inherited_role, []):
                if not self.privilege.matches(grant.privilege, privilege):
                    continue
                if grant.object.object_type != object_type:
                    continue
                if grant.object.name != object_name:
                    continue

                chains = self.role_graph.all_paths(role, inherited_role)

                for chain in chains:
                    paths.append(AccessPath(id=role, role_chain=chain, grant=grant))

        return paths

    def get_access_path(
        self,
        object_type: Optional[str] = None,
        object_name: Optional[str] = None,
        privilege: Optional[str] = None,
        username: Optional[str] = None,
        role: Optional[str] = None
    ):
        if username and not role:
            if object_type and object_name and privilege:
                all_paths = self.access_paths_for_user(
                    username,
                    object_type,
                    object_name,
                    privilege
                )
            else:
                all_paths = self.all_access_paths_for_user(username)
        elif role and not username:
            if object_type and object_name and privilege:
                all_paths = self.access_paths_for_role(
                    role,
                    object_type,
                    object_name,
                    privilege
                )
            else:
                all_paths = self.all_access_paths_for_role(role)
        else:
            raise ValueError("Must provide either username or role, not both")
        return all_paths

    def access_paths_dict(self, **kwargs) -> Dict:
        access_paths_dict: Dict = {}
        all_paths = self.get_access_path(**kwargs)
        if all_paths:
            for path in all_paths:
                chain = path.role_chain
                privilege = path.grant.privilege
                access_paths_dict.setdefault(privilege,[])
                access_paths_dict[privilege].append(chain)

        return access_paths_dict


