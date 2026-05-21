import json
import pandas as pd
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

STATE_DIR = Path.home() / ".snowglobe" / "state"


class StateManager:
    def __init__(self, file: str, path: str | None = None):
        base = Path(path) if path else STATE_DIR
        self.state_path = base / file

    def save(self, state: Any) -> None:
        """Save state with metadata (timestamp)."""
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        envelope = {
            "refreshed_at": datetime.now(timezone.utc).isoformat(),
            "version": 1,
            "data": state,
        }
        with self.state_path.open("w") as f:
            json.dump(envelope, f, indent=2)

    def load(self) -> Any:
        """Load state data (unwraps envelope if present)."""
        if not self.state_path.exists():
            return None

        with self.state_path.open() as f:
            raw = json.load(f)

        # Support both enveloped and legacy bare formats
        if isinstance(raw, dict) and "data" in raw and "refreshed_at" in raw:
            return raw["data"]
        return raw

    def load_metadata(self) -> Optional[dict]:
        """Load just the metadata (refreshed_at, version) without the full data."""
        if not self.state_path.exists():
            return None

        with self.state_path.open() as f:
            raw = json.load(f)

        if isinstance(raw, dict) and "refreshed_at" in raw:
            return {
                "refreshed_at": raw["refreshed_at"],
                "version": raw.get("version", 0),
            }
        return None

    def get_dataframe(self) -> pd.DataFrame:
        data = self.load()
        if data is None:
            return pd.DataFrame()
        return pd.DataFrame(data)


