"""Read-only SQL execution with a bounded self-healing retry loop.

On error, the failed statement's error is fed back to the SQL generator and
retried, up to MAX_ATTEMPTS total, then fails cleanly rather than fabricating
an answer. Never generates SQL beyond this bounded loop.
"""

from __future__ import annotations

from dataclasses import dataclass

import psycopg

from src.query.sql_generator import generate_sql
from src.query.synthesizer import LLMClient

MAX_ATTEMPTS = 3


@dataclass(frozen=True)
class SqlResult:
    rows: list[dict[str, object]] | None
    sql: str | None
    attempts: int
    error: str | None


def execute_readonly_sql(conn: psycopg.Connection, sql: str) -> list[dict[str, object]]:
    cur = conn.execute(sql)
    if cur.description is None:
        return []
    columns = [desc.name for desc in cur.description]
    return [dict(zip(columns, row, strict=True)) for row in cur.fetchall()]


def run_sql_with_self_heal(
    conn: psycopg.Connection, query: str, llm: LLMClient, schema_description: str
) -> SqlResult:
    previous_error: str | None = None
    last_sql: str | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        sql = generate_sql(query, schema_description, llm, previous_error)
        last_sql = sql
        try:
            rows = execute_readonly_sql(conn, sql)
            return SqlResult(rows=rows, sql=sql, attempts=attempt, error=None)
        except psycopg.Error as exc:
            conn.rollback()  # failed statement leaves the transaction aborted - must reset
            previous_error = str(exc)

    return SqlResult(rows=None, sql=last_sql, attempts=MAX_ATTEMPTS, error=previous_error)
