"""L4 commit ingestion: noise-filtered, secret-scanned, LLM-summarized, embedded.

Raw diffs are never stored - used only in-memory to build a summary, then discarded.
Commits are immutable once ingested (unique on project_id+sha), so no content_hash
skip logic is needed here, just an existence check.
"""

from __future__ import annotations

import uuid

import psycopg

from src.ingestion.commit_summarizer import build_diff_text, is_noise_commit, summarize_commit
from src.ingestion.documents import record_secret_finding
from src.ingestion.embedder import Embedder, format_vector
from src.ingestion.github_client import CommitDetail, CommitInfo
from src.ingestion.secrets import scan_for_secrets
from src.query.synthesizer import LLMClient


def commit_exists(conn: psycopg.Connection, project_id: uuid.UUID, sha: str) -> bool:
    row = conn.execute(
        "select 1 from commits where project_id = %s and sha = %s", (project_id, sha)
    ).fetchone()
    return row is not None


def sync_commit(
    conn: psycopg.Connection,
    project_id: uuid.UUID,
    info: CommitInfo,
    detail: CommitDetail,
    embedder: Embedder,
    llm: LLMClient,
) -> str:
    """Returns one of: 'ingested', 'skipped_noise', 'skipped_existing', 'skipped_secret'."""
    if commit_exists(conn, project_id, info.sha):
        return "skipped_existing"
    if is_noise_commit(detail.files):
        return "skipped_noise"

    diff_text = build_diff_text(detail.files)
    findings = scan_for_secrets(f"{info.message}\n\n{diff_text}")

    diff_summary: str | None = None
    embedding_literal: str | None = None
    status = "ingested"

    if findings:
        for finding in findings:
            record_secret_finding(conn, project_id, f"commit:{info.sha}", finding.rule_id)
        status = "skipped_secret"
    else:
        diff_summary = summarize_commit(info.message, diff_text, llm)
        embedding = embedder.embed([f"{info.message}\n\n{diff_summary}"])[0]
        embedding_literal = format_vector(embedding)

    conn.execute(
        """
        insert into commits
            (project_id, sha, message, author, committed_at, files_changed,
             additions, deletions, diff_summary, embedding)
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector)
        on conflict (project_id, sha) do nothing
        """,
        (
            project_id,
            info.sha,
            info.message,
            info.author,
            info.committed_at,
            [f.filename for f in detail.files],
            detail.additions,
            detail.deletions,
            diff_summary,
            embedding_literal,
        ),
    )
    return status
