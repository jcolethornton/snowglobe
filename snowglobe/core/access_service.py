import typer
from typing import Optional
from snowglobe.state.state import StateManager
from snowglobe.collectors.access import AccessCollector
from snowglobe.graphs.role_graph import RoleGraph
from snowglobe.graphs.user_graph import UserGraph
from snowglobe.models.access import AccessGrant
from snowglobe.engines.access.explainer import AccessExplainer
from snowglobe.engines.access.resolver import AccessResolver
from snowglobe.cli.prompts import resolve_access_inputs

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
        return self.user_graph, self.role_graph, self.grants


    def setup_state(self):
        self.state_users = StateManager(file="user_graph.json")
        self.state_roles = StateManager(file="role_graph.json")
        self.state_grants = StateManager(file="grants.json")

    def refresh_state(self):
        sf = self.context.connect()
        collector = AccessCollector(sf)
        # User graph
        self.user_graph = collector.collect_user_roles()
        self.state_users.save(self.user_graph.to_dict())
        # Role graph
        self.role_graph = collector.collect_role_graph()
        self.state_roles.save(self.role_graph.to_dict())
        # Grants
        self.grants = collector.collect_direct_grants()
        self.state_grants.save([g.to_dict() for g in self.grants])

    def load_state(self):
        user_graph = UserGraph(**self.context.profile)
        self.user_graph = user_graph.from_dict(self.state_users.load())
        role_graph = RoleGraph()
        self.role_graph = role_graph.from_dict(self.state_roles.load())
        self.grants = [AccessGrant.from_dict(d) for d in self.state_grants.load()]


    def build_resolver(self):
        self.resolver = AccessResolver(
            user_graph=self.user_graph,
            role_graph=self.role_graph,
            grants=self.grants
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

        if ignore_excluded_roles:
            self.profile['exclude_roles'] = []

        self.setup_state()

        if refresh_state:
            self.refresh_state()

        self.load_state()
        self.build_resolver()

        args = self.resolved_args(
            username=username,
            role=role,
            object_type=object_type,
            object_name=object_name,
            privilege=privilege,
            user_graph=self.user_graph,
            role_graph=self.role_graph,
            grants=self.grants
        )

        query = AccessExplainer(resolver=self.resolver, **args)
        if args['inspect_type'] == "user" and args['username']:
            query_output = query.user_access(username=args['username'])
        elif args['inspect_type'] == "role" and args['role']:
            query_output = query.role_access(role=args['role'])
        else:
            typer.secho("Invalid inspect type. Exiting.", fg=typer.colors.RED)
            raise typer.Exit()

        return query_output

    def resolved_args(self, **kwargs):
        return resolve_access_inputs(
            username=kwargs['username'],
            role=kwargs['role'],
            object_type=kwargs['object_type'],
            object_name=kwargs['object_name'],
            privilege=kwargs['privilege'],
            user_graph=self.user_graph,
            role_graph=self.role_graph,
            grants=self.grants,
        )
