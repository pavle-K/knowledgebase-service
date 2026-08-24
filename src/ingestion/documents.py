"""L1 document ingestion: chunk, secret-scan, embed, and upsert with content_hash-based skip."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping
from typing import cast

import psycopg
from psycopg.types.json import Json

from src.ingestion.chunker_markdown import chunk_markdown
from src.ingestion.embedder import Embedder, format_vector
from src.ingestion.github_client import AccountInfo, RepoInfo
from src.ingestion.secrets import is_excluded_path, scan_for_secrets


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def upsert_project(conn: psycopg.Connection, repo: RepoInfo) -> uuid.UUID:
    row = conn.execute(
        """
        insert into projects
            (name, repo_url, description, source, default_branch, is_private,
             repo_created_at, repo_pushed_at, stargazers_count, language,
             forks_count, open_issues_count)
        values (%s, %s, %s, 'github', %s, %s, %s, %s, %s, %s, %s, %s)
        on conflict (repo_url) do update set
            name = excluded.name,
            description = excluded.description,
            default_branch = excluded.default_branch,
            is_private = excluded.is_private,
            repo_created_at = excluded.repo_created_at,
            repo_pushed_at = excluded.repo_pushed_at,
            stargazers_count = excluded.stargazers_count,
            language = excluded.language,
            forks_count = excluded.forks_count,
            open_issues_count = excluded.open_issues_count,
            updated_at = now()
        returning id
        """,
        (
            repo.name,
            repo.html_url,
            repo.description,
            repo.default_branch,
            repo.is_private,
            repo.created_at,
            repo.pushed_at,
            repo.stargazers_count,
            repo.language,
            repo.forks_count,
            repo.open_issues_count,
        ),
    ).fetchone()
    assert row is not None
    return cast(uuid.UUID, row[0])


def upsert_account_info(conn: psycopg.Connection, account: AccountInfo) -> None:
    conn.execute(
        """
        insert into github_account
            (login, name, bio, company, blog, location, account_created_at,
             public_repos, private_repos, followers, following, synced_at)
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
        on conflict (login) do update set
            name = excluded.name,
            bio = excluded.bio,
            company = excluded.company,
            blog = excluded.blog,
            location = excluded.location,
            account_created_at = excluded.account_created_at,
            public_repos = excluded.public_repos,
            private_repos = excluded.private_repos,
            followers = excluded.followers,
            following = excluded.following,
            synced_at = now()
        """,
        (
            account.login,
            account.name,
            account.bio,
            account.company,
            account.blog,
            account.location,
            account.created_at,
            account.public_repos,
            account.private_repos,
            account.followers,
            account.following,
        ),
    )


def record_secret_finding(
    conn: psycopg.Connection, project_id: uuid.UUID, file_path: str, rule_id: str
) -> None:
    conn.execute(
        "insert into secret_scan_findings (project_id, file_path, rule_id) values (%s, %s, %s)"
        " on conflict (project_id, file_path, rule_id) do nothing",
        (project_id, file_path, rule_id),
    )


def record_ingestion_log(
    conn: psycopg.Connection,
    source: str,
    project_id: uuid.UUID | None,
    layer: str,
    status: str,
    detail: Mapping[str, int | str],
) -> None:
    conn.execute(
        "insert into ingestion_log (source, project_id, layer, status, detail)"
        " values (%s, %s, %s, %s, %s)",
        (source, project_id, layer, status, Json(detail)),
    )


def sync_document(
    conn: psycopg.Connection,
    project_id: uuid.UUID,
    doc_type: str,
    source_path: str,
    content: str,
    embedder: Embedder,
) -> dict[str, int]:
    stats = {"chunks": 0, "embedded": 0, "skipped_unchanged": 0, "skipped_secret": 0}

    if is_excluded_path(source_path):
        return stats

    for index, chunk_content in enumerate(chunk_markdown(content)):
        stats["chunks"] += 1

        findings = scan_for_secrets(chunk_content)
        if findings:
            for finding in findings:
                record_secret_finding(conn, project_id, source_path, finding.rule_id)
            stats["skipped_secret"] += 1
            continue

        chash = content_hash(chunk_content)
        existing = conn.execute(
            "select content_hash from documents"
            " where project_id = %s and source_path = %s and chunk_index = %s",
            (project_id, source_path, index),
        ).fetchone()

        if existing is not None and existing[0] == chash:
            stats["skipped_unchanged"] += 1
            continue

        embedding = embedder.embed([chunk_content])[0]
        conn.execute(
            """
            insert into documents
                (project_id, doc_type, source_path, chunk_index, content, embedding, content_hash)
            values (%s, %s, %s, %s, %s, %s::vector, %s)
            on conflict (project_id, source_path, chunk_index) do update set
                content = excluded.content,
                embedding = excluded.embedding,
                content_hash = excluded.content_hash
            """,
            (
                project_id,
                doc_type,
                source_path,
                index,
                chunk_content,
                format_vector(embedding),
                chash,
            ),
        )
        stats["embedded"] += 1

    return stats
