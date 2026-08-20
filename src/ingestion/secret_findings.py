"""Manual resolution tracking for secret_scan_findings (e.g. "I rotated this key")."""

from __future__ import annotations

import uuid

import psycopg


def mark_secret_resolved(conn: psycopg.Connection, finding_id: uuid.UUID) -> bool:
    row = conn.execute(
        "update secret_scan_findings set resolved_at = now()"
        " where id = %s and resolved_at is null"
        " returning id",
        (finding_id,),
    ).fetchone()
    return row is not None
