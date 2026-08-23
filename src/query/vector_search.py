"""Vector search across L1 documents, L2 code chunks, and L4 commits.

No intent router yet (that's Stage 7), so each layer is searched separately
and merged by distance - "filter by layer" here means each layer gets its own
scoped query rather than one blind mixed search, not a hard either/or choice.

Runs over the read-only role connection - this is the natural-language query
path, which must never write.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import psycopg

from src.ingestion.embedder import Embedder, format_vector


@dataclass(frozen=True)
class SearchResult:
    project_name: str
    source_path: str
    content: str
    distance: float
    layer: str = "document"  # 'document' | 'code' | 'commit'
    symbol_name: str | None = None
    symbol_type: str | None = None
    committed_at: dt.datetime | None = None


def search_documents(
    conn: psycopg.Connection,
    query: str,
    embedder: Embedder,
    limit: int = 5,
    project: str | None = None,
) -> list[SearchResult]:
    query_vector = embedder.embed([query])[0]
    rows = conn.execute(
        """
        select p.name, d.source_path, d.content, d.embedding <-> %s::vector as distance
        from documents d
        join projects p on p.id = d.project_id
        where (%s::text is null or p.name = %s)
        order by distance asc
        limit %s
        """,
        (format_vector(query_vector), project, project, limit),
    ).fetchall()
    return [
        SearchResult(project_name=row[0], source_path=row[1], content=row[2], distance=row[3])
        for row in rows
    ]


def search_code_chunks(
    conn: psycopg.Connection,
    query: str,
    embedder: Embedder,
    limit: int = 5,
    project: str | None = None,
) -> list[SearchResult]:
    query_vector = embedder.embed([query])[0]
    rows = conn.execute(
        """
        select p.name, c.file_path, c.content, c.embedding <-> %s::vector as distance,
               c.symbol_name, c.symbol_type
        from code_chunks c
        join projects p on p.id = c.project_id
        where (%s::text is null or p.name = %s)
        order by distance asc
        limit %s
        """,
        (format_vector(query_vector), project, project, limit),
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


def search_commits(
    conn: psycopg.Connection,
    query: str,
    embedder: Embedder,
    limit: int = 5,
    since: dt.datetime | None = None,
    until: dt.datetime | None = None,
    project: str | None = None,
) -> list[SearchResult]:
    query_vector = embedder.embed([query])[0]
    rows = conn.execute(
        """
        select p.name, co.sha, coalesce(co.diff_summary, co.message) as content,
               co.embedding <-> %s::vector as distance, co.committed_at
        from commits co
        join projects p on p.id = co.project_id
        where co.embedding is not null
          and (%s::timestamptz is null or co.committed_at >= %s)
          and (%s::timestamptz is null or co.committed_at <= %s)
          and (%s::text is null or p.name = %s)
        order by distance asc
        limit %s
        """,
        (format_vector(query_vector), since, since, until, until, project, project, limit),
    ).fetchall()
    return [
        SearchResult(
            project_name=row[0],
            source_path=row[1],
            content=row[2],
            distance=row[3],
            layer="commit",
            committed_at=row[4],
        )
        for row in rows
    ]


def search_latest_commits(
    conn: psycopg.Connection, limit: int = 5, project: str | None = None
) -> list[SearchResult]:
    """Most recent commits by date, not similarity - for 'what's the latest/newest'
    questions, where there's no topic to embed and rank against, just a date sort.
    """
    rows = conn.execute(
        """
        select p.name, co.sha, coalesce(co.diff_summary, co.message) as content, co.committed_at
        from commits co
        join projects p on p.id = co.project_id
        where co.committed_at is not null
          and (%s::text is null or p.name = %s)
        order by co.committed_at desc
        limit %s
        """,
        (project, project, limit),
    ).fetchall()
    return [
        SearchResult(
            project_name=row[0],
            source_path=row[1],
            content=row[2],
            distance=0.0,
            layer="commit",
            committed_at=row[3],
        )
        for row in rows
    ]


_LAYER_ALIASES = {
    "documents": "document",
    "document": "document",
    "code": "code",
    "code_chunks": "code",
    "commits": "commit",
    "commit": "commit",
}


def search_all(
    conn: psycopg.Connection,
    query: str,
    embedder: Embedder,
    limit: int = 5,
    layers: list[str] | None = None,
) -> list[SearchResult]:
    active = (
        {_LAYER_ALIASES.get(name.lower(), name.lower()) for name in layers}
        if layers
        else {"document", "code", "commit"}
    )

    combined: list[SearchResult] = []
    if "document" in active:
        combined.extend(search_documents(conn, query, embedder, limit=limit))
    if "code" in active:
        combined.extend(search_code_chunks(conn, query, embedder, limit=limit))
    if "commit" in active:
        combined.extend(search_commits(conn, query, embedder, limit=limit))
    combined.sort(key=lambda r: r.distance)
    return combined[:limit]
