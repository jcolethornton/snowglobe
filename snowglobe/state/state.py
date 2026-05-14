import json
import pandas as pd
from pathlib import Path
from typing import Any


class StateManager:
    def __init__(self, file: str, path: str = 'snowglobe/state'):
        self.state_path = Path(path) / file

    def save(self, state: Any) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with self.state_path.open("w") as f:
            json.dump(state, f, indent=2)

    def load(self) -> Any:
        if not self.state_path.exists():
            return None

        with self.state_path.open() as f:
            return json.load(f)

    def get_dataframe(self) -> pd.DataFrame:
        return pd.read_json(self.state_path)


