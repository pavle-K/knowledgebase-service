"""L1 vector search: embed the query, find nearest documents by cosine distance.

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
