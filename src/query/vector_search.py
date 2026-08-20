"""Vector search across L1 documents and L2 code chunks.

No intent router yet (that's Stage 7), so both layers are searched separately
and merged by distance - "filter by layer" here means each layer gets its own
scoped query rather than one blind mixed search, not a hard either/or choice.

Runs over the read-only role connection - this is the natural-language query
path, which must never write.
"""

from __future__ import annotations

from dataclasses import dataclass

import psycopg

from src.ingestion.embedder import Embedder, format_vector


@dataclass(frozen=True)
class SearchResult:
    project_name: str
    source_path: str
    content: str
    distance: float
    layer: str = "document"  # 'document' | 'code'
    symbol_name: str | None = None
    symbol_type: str | None = None


def search_documents(
    conn: psycopg.Connection, query: str, embedder: Embedder, limit: int = 5
) -> list[SearchResult]:
    query_vector = embedder.embed([query])[0]
    rows = conn.execute(
        """
        select p.name, d.source_path, d.content, d.embedding <-> %s::vector as distance
        from documents d
        join projects p on p.id = d.project_id
        order by distance asc
        limit %s
        """,
        (format_vector(query_vector), limit),
    ).fetchall()
    return [
        SearchResult(project_name=row[0], source_path=row[1], content=row[2], distance=row[3])
        for row in rows
    ]


def search_code_chunks(
    conn: psycopg.Connection, query: str, embedder: Embedder, limit: int = 5
) -> list[SearchResult]:
    query_vector = embedder.embed([query])[0]
    rows = conn.execute(
        """
        select p.name, c.file_path, c.content, c.embedding <-> %s::vector as distance,
               c.symbol_name, c.symbol_type
        from code_chunks c
        join projects p on p.id = c.project_id
        order by distance asc
        limit %s
        """,
        (format_vector(query_vector), limit),
    ).fetchall()
    return [
        SearchResult(
            project_name=row[0],
            source_path=row[1],
            content=row[2],
            distance=row[3],
            layer="code",
            symbol_name=row[4] or None,
            symbol_type=row[5],
        )
        for row in rows
    ]


def search_all(
    conn: psycopg.Connection, query: str, embedder: Embedder, limit: int = 5
) -> list[SearchResult]:
    combined = [
        *search_documents(conn, query, embedder, limit=limit),
        *search_code_chunks(conn, query, embedder, limit=limit),
    ]
    combined.sort(key=lambda r: r.distance)
    return combined[:limit]
