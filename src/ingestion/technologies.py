"""Populates technologies/project_technologies from a manifest's declared list.

Manifest-only for now (reliable), matching the project.yaml-first philosophy
used for the L3 graph - not inferred from package deps, which would be guessing.
"""

from __future__ import annotations

import uuid

import psycopg


def sync_technologies(
    conn: psycopg.Connection, project_id: uuid.UUID, technologies: list[str]
) -> int:
    count = 0
    for raw_name in technologies:
        name = raw_name.strip()
        if not name:
            continue

        row = conn.execute(
            """
            insert into technologies (name) values (%s)
            on conflict (name) do update set name = excluded.name
            returning id
            """,
            (name,),
        ).fetchone()
        assert row is not None
        technology_id = row[0]

        conn.execute(
            """
            insert into project_technologies (project_id, technology_id)
            values (%s, %s)
            on conflict do nothing
            """,
            (project_id, technology_id),
        )
        count += 1
    return count
