"""Per-repo opt-out: a `.kb-exclude` marker file at the repo root.

Checked first, before any other GitHub API call or embedding call, by both the
webhook handler and the seed sync. A repo carrying the marker is skipped, and
any previously-ingested content for it is purged rather than just left stale -
the point is that excluded content stops existing here, not just stops updating.
"""

from __future__ import annotations

import uuid

import psycopg

from src.ingestion.github_client import GitHubClient

EXCLUDE_MARKER_PATH = ".kb-exclude"

_PURGE_TABLES = (
    ("documents", "project_id"),
    ("code_chunks", "project_id"),
    ("commits", "project_id"),
    ("exposed_interfaces", "project_id"),
    ("dependencies", "consumer_project_id"),
)


def is_excluded(client: GitHubClient, full_name: str) -> bool:
    return client.get_file(full_name, EXCLUDE_MARKER_PATH) is not None


def purge_project_data(conn: psycopg.Connection, project_id: uuid.UUID) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table, column in _PURGE_TABLES:
        cur = conn.execute(f"delete from {table} where {column} = %s", (project_id,))
        counts[table] = cur.rowcount
    return counts
