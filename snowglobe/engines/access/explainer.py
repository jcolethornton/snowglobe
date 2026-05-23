# snowglobe/core/access_query.py
from typing import List, Dict
from snowglobe.engines.access.resolver import AccessResolver
from snowglobe.models.privilege import Privilege
from snowglobe.models.object_ref import ObjectRef


class AccessExplainer:

    object: ObjectRef

    def __init__(
        self, 
        resolver: AccessResolver,
        **args
    ):
        self.resolver = resolver
        self.object_type = args['object_type'].upper() if args.get('object_type') else None
        self.object_name = args['object_name'].upper() if args.get('object_name') else None
        self.privilege = args['privilege'].upper() if args.get('privilege') else None
        self.database = args.get('database')

    def object_exists(self) -> bool:

        return any(
            g.object.object_type.value == self.object_type
            and g.object.name == self.object_name
            for g in self.resolver.grants
        )

    def roles_with_access(self) -> List[str]:

        privilege = Privilege
        return [
            g.role
            for g in self.resolver.grants
            if g.object.object_type.value == self.object_type
            and g.object.name == self.object_name
            and privilege.matches(g.privilege, self.privilege)
        ]

    def user_access(self, username: str) -> Dict:

        self.username = username

        explain: Dict = {
            'user': self.username,
            'object_type': self.object_type,
            'object_name': self.object_name,
            'privilege': self.privilege,
        }

        exists = self.object_exists()
        if exists:

            explain['object_exists'] = True

            roles_with_privilege = self.roles_with_access()

            explain['roles_with_privilege'] = roles_with_privilege

            access_paths_dict = self.resolver.access_paths_dict(
                object_type=self.object_type,
                object_name=self.object_name,
                privilege=self.privilege,
                username=self.username
            )
            explain['user_access_paths'] = access_paths_dict
            explain['user_has_privilege'] = True if access_paths_dict else False 

        else:
            explain['object_exists'] = False

        self.explain = explain

        return self.explain

    def role_access(self, role: str) -> Dict:

        self.role = role

        explain: Dict = {
            'role': self.role,
            'object_type': self.object_type,
            'object_name': self.object_name,
            'privilege': self.privilege,
            
        }

        exists = self.object_exists()
        if exists:

            explain['object_exists'] = True

            roles_with_privilege = self.roles_with_access()

            explain['roles_with_privilege'] = roles_with_privilege

            access_paths_dict = self.resolver.access_paths_dict(
                object_type=self.object_type,
                object_name=self.object_name,
                privilege=self.privilege,
                role=self.role
            )
            explain['role_access_paths'] = access_paths_dict
            explain['role_has_privilege'] = True if access_paths_dict else False 

        else:
            explain['object_exists'] = False

        self.explain = explain

        return self.explain
