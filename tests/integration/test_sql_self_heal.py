import psycopg
import pytest

from src.query.sql_exec import MAX_ATTEMPTS, execute_readonly_sql, run_sql_with_self_heal
from tests.integration.conftest import MigratedDb


class _SequencedLLMClient:
    """Returns responses in order, one per call. For testing multi-attempt recovery."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self.call_count = 0

    def complete(self, system: str, user: str) -> str:
        response = self._responses[min(self.call_count, len(self._responses) - 1)]
        self.call_count += 1
        return response


class _AlwaysBadLLMClient:
    def __init__(self, bad_sql: str) -> None:
        self._bad_sql = bad_sql
        self.call_count = 0

    def complete(self, system: str, user: str) -> str:
        self.call_count += 1
        return self._bad_sql


def test_self_heal_exhausts_retries_and_returns_clean_error(
    db_conn: psycopg.Connection,
) -> None:
    llm = _AlwaysBadLLMClient("select nonexistent_column from projects")

    result = run_sql_with_self_heal(db_conn, "bad query", llm, "projects: id (uuid), name (text)")

    assert result.rows is None
    assert result.error is not None
    assert "nonexistent_column" in result.error
    assert result.attempts == MAX_ATTEMPTS
    assert llm.call_count == MAX_ATTEMPTS


def test_self_heal_recovers_after_a_failed_attempt(db_conn: psycopg.Connection) -> None:
    llm = _SequencedLLMClient(
        ["select nonexistent_column from projects", "select name from projects limit 1"]
    )

    result = run_sql_with_self_heal(db_conn, "how many projects", llm, "projects: name (text)")

    assert result.error is None
    assert result.rows is not None
    assert result.attempts == 2
    assert llm.call_count == 2  # stopped retrying once it succeeded


def test_self_heal_succeeds_on_first_attempt_uses_one_call(db_conn: psycopg.Connection) -> None:
    llm = _SequencedLLMClient(["select name from projects limit 1"])

    result = run_sql_with_self_heal(db_conn, "list projects", llm, "projects: name (text)")

    assert result.error is None
    assert result.attempts == 1
    assert llm.call_count == 1


def test_readonly_role_rejects_write_through_sql_exec_path(migrated_db: MigratedDb) -> None:
    with psycopg.connect(migrated_db.app_ro_url) as ro_conn:
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            execute_readonly_sql(ro_conn, "insert into projects (name) values ('hacked')")
