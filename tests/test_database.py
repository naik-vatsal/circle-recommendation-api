import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.config import ROOT, Settings
from app.database import connect
from app.main import create_app
from app.seed import seed_database


def test_corrupt_seed_rolls_back_all_rows(tmp_path):
    source = tmp_path / "bad_data"
    source.mkdir()
    for file in (ROOT / "data").glob("*.json"):
        (source / file.name).write_bytes(file.read_bytes())
    memberships = json.loads((source / "memberships.json").read_text())
    memberships[0]["user_id"] = 999999
    (source / "memberships.json").write_text(json.dumps(memberships))
    path = tmp_path / "failed.sqlite3"
    with pytest.raises(sqlite3.IntegrityError):
        seed_database(path, source)
    with connect(path, readonly=True) as connection:
        assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM metadata").fetchone()[0] == 0
    # A corrected source can be imported without manual cleanup.
    assert seed_database(path, ROOT / "data") is True


def test_constraints_reject_orphans_duplicate_memberships_and_bad_counts(seeded_database):
    with connect(seeded_database) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO user_interests VALUES (999999, 1)")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO memberships SELECT * FROM memberships LIMIT 1")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE circles SET member_count=-1 WHERE id=5")


def test_startup_keeps_database_edits_instead_of_reimporting(tmp_path):
    path = tmp_path / "editable.sqlite3"
    seed_database(path, ROOT / "data")
    with connect(path) as connection, connection:
        connection.execute("UPDATE circles SET member_count=max_members + 1 WHERE id=5")
    with TestClient(create_app(Settings(database_path=path))) as client:
        results = client.get("/users/7/recommendations").json()["recommendations"]
    assert 5 not in {item["circle"]["id"] for item in results}
    with connect(path, readonly=True) as connection:
        member_count, max_members = connection.execute(
            "SELECT member_count, max_members FROM circles WHERE id=5"
        ).fetchone()
    assert member_count == max_members + 1
