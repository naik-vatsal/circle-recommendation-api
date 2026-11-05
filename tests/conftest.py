from pathlib import Path
from shutil import copyfile

import pytest
from fastapi.testclient import TestClient

from app.config import ROOT, Settings
from app.main import create_app
from app.seed import seed_database


@pytest.fixture(scope="session")
def seeded_database(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("database") / "circles.sqlite3"
    seed_database(path, ROOT / "data")
    return path


@pytest.fixture(scope="session")
def client(seeded_database):
    with TestClient(create_app(Settings(database_path=seeded_database))) as client:
        yield client


@pytest.fixture
def editable_client(tmp_path, seeded_database):
    path = tmp_path / "editable.sqlite3"
    copyfile(seeded_database, path)
    with TestClient(create_app(Settings(database_path=path))) as client:
        yield client, path
