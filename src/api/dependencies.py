"""FastAPI dependency providers.

Query-path endpoints (/v1/query, /v1/impact) only ever use the read-only
connection - matches the non-negotiable "NL query path never writes". The
webhook endpoint is the one exception that legitimately needs write access.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import psycopg
from fastapi import HTTPException

from src.ingestion.embedder import Embedder, get_embedder
from src.ingestion.github_client import GitHubClient
from src.query.synthesizer import LLMClient, get_llm_client


def get_conn() -> Iterator[psycopg.Connection]:
    database_url = os.environ.get("DATABASE_URL_RO")
    if not database_url:
        raise HTTPException(status_code=500, detail="DATABASE_URL_RO is not configured")
    conn = psycopg.connect(database_url)
    try:
        yield conn
    finally:
        conn.close()


def get_conn_rw() -> Iterator[psycopg.Connection]:
    database_url = os.environ.get("DATABASE_URL_RW")
    if not database_url:
        raise HTTPException(status_code=500, detail="DATABASE_URL_RW is not configured")
    conn = psycopg.connect(database_url)
    try:
        yield conn
    finally:
        conn.close()


def get_github_client_dep() -> Iterator[GitHubClient]:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise HTTPException(status_code=500, detail="GITHUB_TOKEN is not configured")
    client = GitHubClient(token=token)
    try:
        yield client
    finally:
        client.close()


def get_embedder_dep() -> Embedder:
    return get_embedder()


def get_llm_dep() -> LLMClient:
    return get_llm_client()
