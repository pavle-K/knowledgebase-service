"""CLI entry point: applies pending migrations using the admin connection.

Role passwords for migrations/0002_roles_and_grants.sql are taken from the
DATABASE_URL_RW / DATABASE_URL_RO connection strings, not set separately -
whatever password is in those URLs is what gets set on the role.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

import psycopg

from src.db.migrate import apply_pending

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def _password_from_url(url: str, var_name: str) -> str:
    password = urlsplit(url).password
    if not password:
        raise ValueError(f"no password found in {var_name}")
    return password


def main() -> int:
    admin_url = os.environ.get("DATABASE_URL_ADMIN")
    rw_url = os.environ.get("DATABASE_URL_RW")
    ro_url = os.environ.get("DATABASE_URL_RO")
    ro_public_url = os.environ.get("DATABASE_URL_RO_PUBLIC")
    if not admin_url or not rw_url or not ro_url or not ro_public_url:
        print(
            "DATABASE_URL_ADMIN, DATABASE_URL_RW, DATABASE_URL_RO, and "
            "DATABASE_URL_RO_PUBLIC must all be set",
            file=sys.stderr,
        )
        return 1

    env = {
        "APP_RW_PASSWORD": _password_from_url(rw_url, "DATABASE_URL_RW"),
        "APP_RO_PASSWORD": _password_from_url(ro_url, "DATABASE_URL_RO"),
        "APP_RO_PUBLIC_PASSWORD": _password_from_url(ro_public_url, "DATABASE_URL_RO_PUBLIC"),
    }

    with psycopg.connect(admin_url) as conn:
        applied = apply_pending(conn, MIGRATIONS_DIR, env)

    if applied:
        print(f"Applied {len(applied)} migration(s):")
        for name in applied:
            print(f"  {name}")
    else:
        print("No pending migrations.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
