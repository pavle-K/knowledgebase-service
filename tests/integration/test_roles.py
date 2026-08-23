import psycopg
import pytest

from tests.integration.conftest import MigratedDb


def test_app_ro_can_select(migrated_db: MigratedDb) -> None:
    with psycopg.connect(migrated_db.app_ro_url) as conn:
        conn.execute("select count(*) from projects").fetchone()


def test_app_ro_cannot_insert(migrated_db: MigratedDb) -> None:
    # default_transaction_read_only (migrations/0007) rejects writes at the
    # transaction level before the SELECT-only grant is even checked.
    with psycopg.connect(migrated_db.app_ro_url) as conn:
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            conn.execute("insert into projects (name) values ('should not be allowed')")


def test_app_ro_cannot_drop_table(migrated_db: MigratedDb) -> None:
    with psycopg.connect(migrated_db.app_ro_url) as conn:
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            conn.execute("drop table projects")


def test_app_ro_statement_timeout_is_set(migrated_db: MigratedDb) -> None:
    with psycopg.connect(migrated_db.app_ro_url) as conn:
        assert conn.execute("show statement_timeout").fetchone() == ("4s",)
    with psycopg.connect(migrated_db.app_ro_public_url) as conn:
        assert conn.execute("show statement_timeout").fetchone() == ("4s",)


def test_app_ro_statement_timeout_cancels_a_slow_query(migrated_db: MigratedDb) -> None:
    with psycopg.connect(migrated_db.app_ro_url) as conn:
        with pytest.raises(psycopg.errors.QueryCanceled):
            conn.execute("select pg_sleep(5)")


def test_app_rw_can_insert_and_it_is_visible(migrated_db: MigratedDb) -> None:
    with psycopg.connect(migrated_db.app_rw_url) as rw_conn:
        rw_conn.execute("insert into projects (name) values ('rw-role-test-project')")
        rw_conn.commit()

    with psycopg.connect(migrated_db.app_ro_url) as ro_conn:
        row = ro_conn.execute(
            "select name from projects where name = 'rw-role-test-project'"
        ).fetchone()
        assert row is not None

    with psycopg.connect(migrated_db.app_rw_url) as rw_conn:
        rw_conn.execute("delete from projects where name = 'rw-role-test-project'")
        rw_conn.commit()
