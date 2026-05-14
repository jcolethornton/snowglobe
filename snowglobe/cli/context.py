from dataclasses import dataclass
from typing import Optional, Dict, Any
from snowglobe.config.loader import SnowglobeConfig
from snowglobe.snowflake.connection import SnowflakeReadOnly

@dataclass
class SnowglobeContext:
    profile_name: str = "default"
    profile: Optional[Dict[str, Any]] = None
    role: Optional[str] = None
    output: str = "table"
    verbose: bool = False

    def load_profile(self):
        config = SnowglobeConfig()
        self.profile = config.get_profile(self.profile_name)
        if self.role:
            self.profile["role"] = self.role

    def connect(self) -> SnowflakeReadOnly:
        if not hasattr(self, "_sf"):
            self._sf = SnowflakeReadOnly(
                account=self.profile["account"],
                warehouse=self.profile.get("warehouse"),
                user=self.profile["user"],
                role=self.profile.get("role"),
                password=self.profile.get("password"),
                private_key_path=self.profile.get("private_key_path"),
                private_key_pwd=self.profile.get("private_key_pwd")
            )
        return self._sf

class ShellContext:
    def __init__(self, app_context):
        self.app_context = app_context
        self.user_graph = None
        self.role_graph = None
        self.grants = None
        self.resolver = None

        # working state
        self.inspect_type = None
        self.username = None
        self.role = None
        self.object_type = None
        self.object_name = None
        self.privilege = None

    def load_profile(self):
        return self.app_context.load_profile()

    def connect(self):
        return self.app_context.connect()

    @property
    def profile(self):
        return self.app_context.profile

    @property
    def verbose(self):
        return self.app_context.verbose

    @property
    def output(self):
        return self.app_context.output
