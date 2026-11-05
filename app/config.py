"""Small, explicit configuration surface for the local application."""

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    database_path: Path = ROOT / "var" / "circles.sqlite3"
    data_dir: Path = ROOT / "data"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_path=Path(os.environ.get("CIRCLES_DATABASE_PATH", str(cls.database_path))),
            data_dir=Path(os.environ.get("CIRCLES_DATA_DIR", str(cls.data_dir))),
        )
