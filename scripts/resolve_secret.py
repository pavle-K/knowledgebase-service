"""CLI: manage secret_scan_findings resolution.

python -m scripts.resolve_secret list                  - show unresolved findings
python -m scripts.resolve_secret resolve <finding_id>   - mark one as handled
"""

from __future__ import annotations

import os
import sys
import uuid

import psycopg

from src.ingestion.secret_findings import mark_secret_resolved


def _list_unresolved(conn: psycopg.Connection) -> None:
    rows = conn.execute(
        """
        select f.id, p.name, f.file_path, f.rule_id, f.created_at
        from secret_scan_findings f
        join projects p on p.id = f.project_id
        where f.resolved_at is null
        order by p.name, f.created_at
        """
    ).fetchall()
    if not rows:
        print("No unresolved findings.")
        return
    for finding_id, project_name, file_path, rule_id, created_at in rows:
        print(f"{finding_id}  {project_name}  {file_path}  {rule_id}  (found {created_at})")


def main() -> int:
    database_url = os.environ.get("DATABASE_URL_RW")
    if not database_url:
        print("DATABASE_URL_RW is not set", file=sys.stderr)
        return 1

    if len(sys.argv) < 2 or sys.argv[1] not in ("list", "resolve"):
        print(__doc__, file=sys.stderr)
        return 1

    with psycopg.connect(database_url) as conn:
        if sys.argv[1] == "list":
            _list_unresolved(conn)
            return 0

        if len(sys.argv) < 3:
            print("usage: python -m scripts.resolve_secret resolve <finding_id>", file=sys.stderr)
            return 1

        try:
            finding_id = uuid.UUID(sys.argv[2])
        except ValueError:
            print(f"'{sys.argv[2]}' is not a valid finding id", file=sys.stderr)
            return 1

        resolved = mark_secret_resolved(conn, finding_id)
        conn.commit()
        print("Marked resolved." if resolved else "No matching unresolved finding.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
