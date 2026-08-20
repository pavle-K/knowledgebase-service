"""Plain-SQL migration runner: applies migrations/*.sql in order, tracked in schema_migrations."""

from __future__ import annotations

import re
from pathlib import Path

import psycopg

MIGRATIONS_TABLE = "schema_migrations"
_PLACEHOLDER = re.compile(r"\$\{(\w+)\}")


def substitute_env_vars(sql: str, env: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in env:
            raise KeyError(f"missing env var for migration placeholder: {name}")
        return env[name]

    return _PLACEHOLDER.sub(replace, sql)


def _ensure_migrations_table(conn: psycopg.Connection) -> None:
    with conn.transaction():
        conn.execute(
            f"create table if not exists {MIGRATIONS_TABLE} ("
            f"  filename text primary key,"
            f"  applied_at timestamptz not null default now()"
            f")"
        )


def _applied_filenames(conn: psycopg.Connection) -> set[str]:
    rows = conn.execute(f"select filename from {MIGRATIONS_TABLE}").fetchall()
    return {row[0] for row in rows}


def apply_pending(conn: psycopg.Connection, migrations_dir: Path, env: dict[str, str]) -> list[str]:
    _ensure_migrations_table(conn)

    applied = _applied_filenames(conn)
    pending = sorted(p for p in migrations_dir.glob("*.sql") if p.name not in applied)

    newly_applied = []
    for path in pending:
        sql = substitute_env_vars(path.read_text(), env)
        with conn.transaction():
            conn.execute(sql)
            conn.execute(f"insert into {MIGRATIONS_TABLE} (filename) values (%s)", (path.name,))
        newly_applied.append(path.name)

    return newly_applied
