from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest

from src.db.migrate import apply_pending

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


def _role_url(admin_url: str, role: str, password: str) -> str:
    parts = urlsplit(admin_url)
    netloc = f"{role}:{password}@{parts.hostname}"
    if parts.port:
        netloc += f":{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


@dataclass
class MigratedDb:
    admin_url: str
    app_rw_url: str
    app_ro_url: str


@pytest.fixture(scope="session")
def migrated_db() -> Iterator[MigratedDb]:
    admin_url = os.environ.get("TEST_DATABASE_URL")
    if not admin_url:
        pytest.skip("TEST_DATABASE_URL is not set")

    rw_password = os.environ.get("APP_RW_PASSWORD", "test_rw_password")
    ro_password = os.environ.get("APP_RO_PASSWORD", "test_ro_password")

    try:
        conn = psycopg.connect(admin_url)
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres not reachable at TEST_DATABASE_URL: {exc}")

    with conn:
        with conn.transaction():
            conn.execute("drop role if exists app_rw")
            conn.execute("drop role if exists app_ro")
            conn.execute("drop schema public cascade")
            conn.execute("create schema public")

        apply_pending(
            conn,
            MIGRATIONS_DIR,
            {"APP_RW_PASSWORD": rw_password, "APP_RO_PASSWORD": ro_password},
        )

    yield MigratedDb(
        admin_url=admin_url,
        app_rw_url=_role_url(admin_url, "app_rw", rw_password),
        app_ro_url=_role_url(admin_url, "app_ro", ro_password),
    )
    conn.close()


@pytest.fixture
def db_conn(migrated_db: MigratedDb) -> Iterator[psycopg.Connection]:
    conn = psycopg.connect(migrated_db.admin_url)
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()
