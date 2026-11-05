"""SQLite connections with explicit ownership and foreign-key enforcement."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path


def parse_time(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError(f"Timestamp must have a timezone: {value}")
    return result.astimezone(UTC)


def utc_text(value: str | datetime) -> str:
    parsed = parse_time(value) if isinstance(value, str) else value
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Timestamp must have a timezone")
    return parsed.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


@contextmanager
def connect(path: Path, *, readonly: bool = False) -> Iterator[sqlite3.Connection]:
    if readonly:
        connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
    finally:
        connection.close()
