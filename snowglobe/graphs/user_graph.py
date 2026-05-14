from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Set, Tuple
from snowglobe.graphs.role_graph import RoleGraph

@dataclass
class UserGraph:
    """
    Represents Snowflake users and their assigned roles.

    assigned_roles:
        username -> list of directly assigned roles
    """

    def __init__(self, assigned_roles: Dict[str, List[str]] = {}, **args):
        self.assigned_roles = assigned_roles
        self.exclude_list_raw = args.get('exclude_roles',[])

    def excluded_roles(self):
        return {f"ACCOUNT_ROLE::{r}" for r in self.exclude_list_raw}

    def roles_of(self, username: str) -> Tuple[List[str],List[str]]:
        """Directly assigned roles"""
        roles = self.assigned_roles.get(username, [])
        role_list: List[str] = []
        exclude_list: List[str] = []
        exclude = self.excluded_roles()
        for role in roles:
            if role in exclude:
                exclude_list.append(role)
            else:
                role_list.append(role)
        return role_list, exclude_list

    def all_users(self) -> List[str]:
        self.users = self.assigned_roles.keys()
        return list(self.users)

    def effective_roles(
        self,
        username: str,
        role_graph: RoleGraph,
    ) -> Set[str]:
        """
        Return ALL effective roles for a user, including inherited.
        """
        direct_roles = self.roles_of(username)[0]

        effective: Set[str] = set(direct_roles)

        for role in direct_roles:
            effective |= role_graph.all_ancestors(role)

        return effective

    def to_dict(self) -> Dict[str, List[str]]:
        """JSON-safe representation"""
        return {user: sorted(roles) for user, roles in self.assigned_roles.items()}

    def from_dict(self, data: Dict[str, List[str]]) -> "UserGraph":
        self.assigned_roles.update({user: list(roles) for user, roles in data.items()})
        return self
