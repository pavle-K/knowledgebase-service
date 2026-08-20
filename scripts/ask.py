"""CLI: python -m scripts.ask "question" - vector search + LLM synthesis over L1 documents."""

from __future__ import annotations

import os
import sys

import psycopg

from src.ingestion.embedder import get_embedder
from src.query.graph import run_query
from src.query.synthesizer import get_llm_client


def main() -> int:
    if len(sys.argv) < 2:
        print('usage: python -m scripts.ask "<question>"', file=sys.stderr)
        return 1

    query = sys.argv[1]
    database_url = os.environ.get("DATABASE_URL_RO")
    if not database_url:
        print("DATABASE_URL_RO is not set", file=sys.stderr)
        return 1

    embedder = get_embedder()
    llm = get_llm_client()

    with psycopg.connect(database_url) as conn:
        state = run_query(conn, embedder, llm, query)

    print(state["summary"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
