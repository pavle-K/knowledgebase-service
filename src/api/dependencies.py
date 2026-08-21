"""FastAPI dependency providers.

Query-path endpoints (/v1/query, /v1/impact) only ever use a read-only
connection - matches the non-negotiable "NL query path never writes". Which
read-only role depends on the caller's tier: privileged callers get app_ro,
everyone else gets app_ro_public, whose row-level security hides private
projects. The webhook endpoint is the one exception that needs write access.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import psycopg
from fastapi import HTTPException, Request

from src.ingestion.embedder import Embedder, get_embedder
from src.ingestion.github_client import GitHubClient
from src.query.synthesizer import LLMClient, get_llm_client


def get_conn(request: Request) -> Iterator[psycopg.Connection]:
    privileged = getattr(request.state, "privileged", False)
    var_name = "DATABASE_URL_RO" if privileged else "DATABASE_URL_RO_PUBLIC"
    database_url = os.environ.get(var_name)
    if not database_url:
        raise HTTPException(status_code=500, detail=f"{var_name} is not configured")
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
