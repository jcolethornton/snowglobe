import os
import yaml
from pathlib import Path
from typing import Dict, Any

class ProfileNotFound(Exception):
    pass

class SnowglobeConfig:
    CONFIG_PATH = Path.home() / ".snowglobe" / "config.yaml"

    def __init__(self):
        self.profiles: Dict[str, Dict[str, Any]] = {}
        self.load()

    
    def _expand_env(self, obj: Any) -> Any:
        """Recursively expand environment variables in strings, preserving types."""
        if isinstance(obj, str):
            return os.path.expandvars(obj)
        if isinstance(obj, list):
            return [self._expand_env(x) for x in obj]
        if isinstance(obj, dict):
            return {k: self._expand_env(v) for k, v in obj.items()}
        return obj

    def load(self):
        if not self.CONFIG_PATH.exists():
            raise FileNotFoundError(f"Config file not found at {self.CONFIG_PATH}")
        with open(self.CONFIG_PATH, "r") as f:
            raw_profiles = yaml.safe_load(f) or {}

        for profile_name, values in raw_profiles.items():
            self.profiles[profile_name] = self._expand_env(values)

    def get_profile(self, profile_name: str) -> Dict[str, Any]:
        if profile_name not in self.profiles:
            raise ProfileNotFound(f"Profile '{profile_name}' not found in config")
        return self.profiles[profile_name]

    def list_profiles(self):
        return list(self.profiles.keys())
