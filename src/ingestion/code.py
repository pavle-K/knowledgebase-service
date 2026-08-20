"""L2 code chunk ingestion: chunk by symbol, secret-scan, embed, upsert with content_hash skip."""

from __future__ import annotations

import uuid

import psycopg

from src.ingestion.chunker_code import chunk_code_file
from src.ingestion.documents import content_hash, record_secret_finding
from src.ingestion.embedder import Embedder, format_vector
from src.ingestion.secrets import is_excluded_path, scan_for_secrets


def sync_code_file(
    conn: psycopg.Connection,
    project_id: uuid.UUID,
    file_path: str,
    content: str,
    embedder: Embedder,
) -> dict[str, int]:
    stats = {"chunks": 0, "embedded": 0, "skipped_unchanged": 0, "skipped_secret": 0}

    if is_excluded_path(file_path):
        return stats

    for chunk in chunk_code_file(file_path, content):
        stats["chunks"] += 1

        findings = scan_for_secrets(chunk.content)
        if findings:
            for finding in findings:
                record_secret_finding(conn, project_id, file_path, finding.rule_id)
            stats["skipped_secret"] += 1
            continue

        chash = content_hash(chunk.content)
        existing = conn.execute(
            "select content_hash from code_chunks"
            " where project_id = %s and file_path = %s"
            " and symbol_name = %s and start_line = %s",
            (project_id, file_path, chunk.symbol_name, chunk.start_line),
        ).fetchone()

        if existing is not None and existing[0] == chash:
            stats["skipped_unchanged"] += 1
            continue

        embedding = embedder.embed([chunk.content])[0]
        conn.execute(
            """
            insert into code_chunks
                (project_id, file_path, symbol_name, symbol_type, language,
                 start_line, end_line, content, docstring, embedding, content_hash)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector, %s)
            on conflict (project_id, file_path, symbol_name, start_line) do update set
                symbol_type = excluded.symbol_type,
                language = excluded.language,
                end_line = excluded.end_line,
                content = excluded.content,
                docstring = excluded.docstring,
                embedding = excluded.embedding,
                content_hash = excluded.content_hash
            """,
            (
                project_id,
                file_path,
                chunk.symbol_name,
                chunk.symbol_type,
                chunk.language,
                chunk.start_line,
                chunk.end_line,
                chunk.content,
                chunk.docstring,
                format_vector(embedding),
                chash,
            ),
        )
        stats["embedded"] += 1

    return stats
