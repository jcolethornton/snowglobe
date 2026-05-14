from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Set, List

@dataclass
class RoleGraph:
    parents: Dict[str, Set[str]]
    _ancestors: Dict[str, Set[str]] | None = None

    def __init__(self, roles: Dict[str, set] | None = None):
        self.roles: Dict[str, set] = roles or {}
        self.parents: Dict[str, Set[str]] = {}
        self._ancestors: Dict[str, Set[str]] | None = None
        self.build_index()


    def build_index(self) -> None:
        """Precompute all ancestors for every role"""
        ancestors: Dict[str, Set[str]] = {}

        def dfs(role: str, visited: Set[str]) -> Set[str]:
            result = set()
            for parent in self.parents.get(role, set()):
                if parent not in visited:
                    visited.add(parent)
                    result.add(parent)
                    result |= dfs(parent, visited)
            return result

        for role in self.parents.keys():
            ancestors[role] = dfs(role, set())

        self._ancestors = ancestors


    def parents_of(self, role_id: str) -> Set[str]:
        return self.parents.get(role_id, set())

    def all_ancestors(self, role_id: str) -> Set[str]:
        """
        Return all ancestors of role_id
        """
        visited: Set[str] = set()
        stack = [role_id]
        while stack:
            current = stack.pop()
            for parent in self.parents.get(current, set()):
                if parent in visited:
                    continue
                visited.add(parent)
                stack.append(parent)

        return visited

    # def all_ancestors_for_roles(self, role_ids: List[str]) -> Set[str]:
    #     """Return all ancestors for multiple roles"""
    #     result: Set[str] = set(role_ids)
    #     for r in role_ids:
    #         result |= self.all_ancestors(r)
    #     return result

    def all_paths(self, from_role: str, to_role: str) -> List[List[str]]:
        paths: List[List[str]] = []

        def dfs(current: str, path: List[str], visited: Set[str]):
            if current == to_role:
                paths.append(path[:])
                return
            for parent in self.parents.get(current, set()):
                if parent in visited:
                    continue
                visited.add(parent)
                path.append(parent)
                dfs(parent, path, visited)
                path.pop()
                visited.remove(parent)

        dfs(from_role, [from_role], {from_role})
        return paths

    def all_roles(self) -> List[str]:
        return list(self.parents.keys())

    def to_dict(self) -> Dict[str, List[str]]:
        """Serialize to dict: role -> list of parent roles"""
        return {r: sorted(p) for r, p in self.parents.items()}


    def from_dict(self, data: Dict[str, List[str]]) -> "RoleGraph":
        self.roles = {role: set(perms) for role, perms in data.items()}
        self.parents = self.roles
        self.build_index()
        return self
