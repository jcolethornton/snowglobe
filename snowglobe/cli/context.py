from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from snowglobe.config.loader import SnowglobeConfig
from snowglobe.snowflake.connection import SnowflakeReadOnly


@dataclass
class SnowglobeContext:
    profile_name: str = "default"
    profile: Optional[Dict[str, Any]] = None
    role: Optional[str] = None
    output: str = "table"
    verbose: bool = False

    # Working state (used by shell and interactive prompts)
    target_role: Optional[str] = None
    username: Optional[str] = None
    object_type: Optional[str] = None
    object_name: Optional[str] = None
    privilege: Optional[str] = None

    # Preloaded graphs (populated by shell or on-demand)
    user_graph: Any = None
    role_graph: Any = None
    object_index: Optional[Dict[str, List[str]]] = None

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
