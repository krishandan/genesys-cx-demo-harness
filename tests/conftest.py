"""Test fixtures.

The database URL is forced into the environment before anything under app/ is
imported, because app.db builds its engine at import time. That is why the app
imports below live inside the fixtures rather than at module top.
"""

import os
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import psycopg
import pytest

if TYPE_CHECKING:
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session

PG_USER = os.environ.get("TEST_PG_USER", "backlot")
PG_PASSWORD = os.environ.get("TEST_PG_PASSWORD", "backlot")
PG_HOST = os.environ.get("TEST_PG_HOST", "localhost")
PG_PORT = os.environ.get("TEST_PG_PORT", "5432")
TEST_DB_NAME = "backlot_test"

ADMIN_DSN = f"postgresql://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/postgres"
TEST_DATABASE_URL = (
    f"postgresql+psycopg://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{TEST_DB_NAME}"
)

TEST_API_KEY = "test-key"

os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["API_KEY"] = TEST_API_KEY
os.environ["DEFAULT_TENANT"] = "northwind"
os.environ["APP_ENV"] = "test"

REPO_ROOT = Path(__file__).resolve().parent.parent
TEST_PACKS_DIR = Path(__file__).parent / "packs"


@pytest.fixture(scope="session", autouse=True)
def _database() -> Iterator[None]:
    """Recreate the test database and bring it to head via the real migration."""
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')

    from alembic.config import Config

    from alembic import command

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    command.upgrade(cfg, "head")

    yield


@pytest.fixture(autouse=True)
def _clean_tables() -> Iterator[None]:
    """Each test starts from an empty spine."""
    from sqlalchemy import text

    from app.db import engine

    with engine.begin() as conn:
        conn.execute(
            text("TRUNCATE tenant, party, identity, verification, contact_point CASCADE")
        )
    yield


@pytest.fixture
def client() -> Iterator["TestClient"]:
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def db() -> Iterator["Session"]:
    from app.db import SessionLocal

    with SessionLocal() as session:
        yield session


@pytest.fixture
def auth() -> dict[str, str]:
    return {"X-API-Key": TEST_API_KEY}


@pytest.fixture
def seeded_northwind(db: "Session") -> None:
    """The shipped Northwind pack."""
    from app.seed.generator import seed_tenant

    seed_tenant(db, "northwind")


@pytest.fixture
def seeded_acme(db: "Session") -> None:
    """A second tenant, from a test-only pack, used to prove tenant isolation."""
    from app.seed.generator import seed_tenant

    seed_tenant(db, "acme", packs_dir=TEST_PACKS_DIR)
