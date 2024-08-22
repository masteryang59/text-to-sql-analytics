"""Fixtures. Database tests run against real Postgres.

By default a private server is started once per test session from the `pgserver`
wheel (no Docker needed). Set TEST_DATABASE_URL to use another server instead, for
example the one from `docker compose up db`. The role needs CREATEDB and CREATEROLE.

Seeding takes a few seconds, so one seeded database is shared by every test that
only reads; tests that change data get a fresh database of their own.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from datetime import date
from pathlib import Path

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from sqlchat import seed
from sqlchat.catalog import load_catalog
from sqlchat.config import Settings
from sqlchat.db import Database
from sqlchat.offline import OfflineGenerator
from sqlchat.service import AnalyticsService

ROOT = Path(__file__).resolve().parent.parent
TODAY = date(2026, 9, 30)  # the bundled data's last day; gold answers assume it


@pytest.fixture(scope="session")
def pg_admin_url():
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        yield url
        return
    try:
        import pgserver
    except ImportError:
        pytest.skip("needs TEST_DATABASE_URL or the pgserver package")
    directory = tempfile.mkdtemp(prefix="sqlchat-test-pg-")
    server = pgserver.get_server(directory, cleanup_mode="stop")
    yield server.get_uri()
    server.cleanup()
    # On Windows the server's log file can stay locked for a moment after it stops.
    shutil.rmtree(directory, ignore_errors=True)


def _create_db(admin_url: str) -> str:
    name = f"t_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    return name


def _drop_db(admin_url: str, name: str) -> None:
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture
def pg_url(pg_admin_url):
    """An empty database for this test only."""
    name = _create_db(pg_admin_url)
    yield make_conninfo(pg_admin_url, dbname=name)
    _drop_db(pg_admin_url, name)


@pytest.fixture(scope="session")
def seeded_url(pg_admin_url):
    """A database with the demo data, shared by tests that don't change it."""
    name = _create_db(pg_admin_url)
    url = make_conninfo(pg_admin_url, dbname=name)
    db = Database(url, max_size=2)
    db.init(auto_seed=True, query_role="sqlchat_reader")
    db.close()
    yield url
    _drop_db(pg_admin_url, name)


def make_settings(**overrides) -> Settings:
    base = dict(database_url="unused", openai_api_key="", openai_base_url="", static_dir=Path("does-not-exist"),
                reference_date=TODAY)
    base.update(overrides)
    return Settings(_env_file=None, **base)


@pytest.fixture
def settings():
    return make_settings()


@pytest.fixture(scope="session")
def seeded_db(seeded_url):
    db = Database(seeded_url, max_size=6)
    yield db
    db.close()


@pytest.fixture(scope="session")
def catalog(seeded_db):
    with seeded_db.connection() as conn:
        return load_catalog(conn, query_role="sqlchat_reader")


@pytest.fixture
def service(seeded_db, catalog, settings):
    return AnalyticsService(seeded_db, catalog, OfflineGenerator(catalog), settings)


@pytest.fixture
def conn(seeded_db):
    with seeded_db.connection() as c:
        yield c


@pytest.fixture(scope="session")
def generated():
    return seed.generate(17)

def debounce_input(data=None):
    if data is None:
        return None
    return data

def debounce_input(data=None):
    if data is None:
        return None
    return data