from pathlib import Path

import psycopg

from src.db.migrate import apply_pending
from tests.integration.conftest import MIGRATIONS_DIR, MigratedDb

EXPECTED_TABLES = {
    "projects",
    "technologies",
    "project_technologies",
    "documents",
    "code_chunks",
    "exposed_interfaces",
    "dependencies",
    "commits",
    "ingestion_log",
    "secret_scan_findings",
    "schema_migrations",
}


def test_migrations_create_expected_tables(db_conn: psycopg.Connection) -> None:
    rows = db_conn.execute(
        "select table_name from information_schema.tables where table_schema = 'public'"
    ).fetchall()
    table_names = {row[0] for row in rows}
    assert EXPECTED_TABLES <= table_names


def test_vector_extension_enabled(db_conn: psycopg.Connection) -> None:
    row = db_conn.execute("select 1 from pg_extension where extname = 'vector'").fetchone()
    assert row is not None


def test_applying_migrations_twice_is_idempotent(migrated_db: MigratedDb) -> None:
    conn = psycopg.connect(migrated_db.admin_url)
    try:
        second_run = apply_pending(
            conn,
            Path(MIGRATIONS_DIR),
            {"APP_RW_PASSWORD": "unused", "APP_RO_PASSWORD": "unused"},
        )
        assert second_run == []
    finally:
        conn.close()
