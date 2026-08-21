"""POST /webhook/github - HMAC-verified, path-based incremental layer sync (CLAUDE.md section 9).

Handles push (the real work), repository, release, and ping. Deletions in a
push are not handled - out of scope for this stage.
"""

from __future__ import annotations

import json
import os
from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request

from src.api.dependencies import get_conn_rw, get_embedder_dep, get_github_client_dep, get_llm_dep
from src.api.webhook_auth import verify_github_signature
from src.ingestion.code import sync_code_file
from src.ingestion.commits import sync_commit
from src.ingestion.documents import record_ingestion_log, sync_document, upsert_project
from src.ingestion.embedder import Embedder
from src.ingestion.exclusion import is_excluded, purge_project_data
from src.ingestion.github_client import CommitInfo, GitHubClient, RepoInfo
from src.ingestion.repo_sync import sync_manifest_for_repo, sync_static_analysis_for_file
from src.ingestion.webhook_layers import affected_layers
from src.query.synthesizer import LLMClient

router = APIRouter()

ConnRWDep = Annotated[psycopg.Connection, Depends(get_conn_rw)]
GitHubClientDep = Annotated[GitHubClient, Depends(get_github_client_dep)]
EmbedderDep = Annotated[Embedder, Depends(get_embedder_dep)]
LLMDep = Annotated[LLMClient, Depends(get_llm_dep)]


def _repo_from_payload(repo_payload: dict[str, Any]) -> RepoInfo:
    return RepoInfo(
        name=repo_payload["name"],
        full_name=repo_payload["full_name"],
        html_url=repo_payload["html_url"],
        description=repo_payload.get("description"),
        default_branch=repo_payload.get("default_branch", "main"),
        # Fail closed: if GitHub ever omits this field, treat the repo as
        # private rather than silently exposing it to the public-tier role.
        is_private=repo_payload.get("private", True),
        fork=repo_payload.get("fork", False),
    )


def _handle_push(
    conn: psycopg.Connection,
    client: GitHubClient,
    embedder: Embedder,
    llm: LLMClient,
    payload: dict[str, Any],
) -> dict[str, Any]:
    repo = _repo_from_payload(payload["repository"])
    project_id = upsert_project(conn, repo)

    if is_excluded(client, repo.full_name):
        purge_counts = purge_project_data(conn, project_id)
        record_ingestion_log(
            conn, "github_webhook", project_id, "exclusion", "success", purge_counts
        )
        conn.commit()
        return {"status": "excluded", **purge_counts}

    changed_files: set[str] = set()
    for commit in payload.get("commits", []):
        changed_files.update(commit.get("added", []))
        changed_files.update(commit.get("modified", []))

    file_layers = {f: affected_layers(f) for f in changed_files}
    layers_touched: set[str] = set().union(*file_layers.values()) if file_layers else set()

    documents_synced = 0
    for file_path, layers in file_layers.items():
        if "documents" not in layers:
            continue
        content = client.get_file(repo.full_name, file_path)
        if content is None:
            continue
        doc_type = "readme" if file_path == "README.md" else "docs"
        sync_document(conn, project_id, doc_type, file_path, content, embedder)
        documents_synced += 1

    code_synced = 0
    for file_path, layers in file_layers.items():
        if "code" not in layers:
            continue
        content = client.get_file(repo.full_name, file_path)
        if content is None:
            continue
        sync_code_file(conn, project_id, file_path, content, embedder)
        code_synced += 1

    # graph-triggering files (project.yaml, requirements.txt, ...) and
    # code-triggering files never overlap, so this never re-fetches a file
    # already handled by the code loop above.
    if "graph" in layers_touched:
        sync_manifest_for_repo(conn, client, repo, project_id, source="github_webhook")
        for file_path, layers in file_layers.items():
            if "graph" not in layers:
                continue
            content = client.get_file(repo.full_name, file_path)
            if content is not None:
                sync_static_analysis_for_file(conn, project_id, file_path, content)

    commits_synced = 0
    if "commits" in layers_touched:
        for commit in payload.get("commits", []):
            commit_files = set(commit.get("added", [])) | set(commit.get("modified", []))
            if not any("commits" in affected_layers(f) for f in commit_files):
                continue
            info = CommitInfo(
                sha=commit["id"],
                message=commit.get("message", ""),
                author=(commit.get("author") or {}).get("name"),
                committed_at=commit.get("timestamp", ""),
            )
            detail = client.get_commit_detail(repo.full_name, info.sha)
            if detail is not None:
                sync_commit(conn, project_id, info, detail, embedder, llm)
                commits_synced += 1

    result: dict[str, int | str] = {
        "files_changed": len(changed_files),
        "layers": ",".join(sorted(layers_touched)),
        "documents_synced": documents_synced,
        "code_synced": code_synced,
        "commits_synced": commits_synced,
    }
    record_ingestion_log(conn, "github_webhook", project_id, "webhook_push", "success", result)
    conn.commit()
    return {"status": "ok", **result}


def _handle_repository(conn: psycopg.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    repo = _repo_from_payload(payload["repository"])
    upsert_project(conn, repo)
    conn.commit()
    return {"status": "ok", "event": "repository"}


def _handle_release(conn: psycopg.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    repo_payload = payload.get("repository")
    if repo_payload:
        upsert_project(conn, _repo_from_payload(repo_payload))
        conn.commit()
    return {"status": "acknowledged", "event": "release"}


@router.post("/webhook/github")
async def github_webhook(
    request: Request, conn: ConnRWDep, client: GitHubClientDep, embedder: EmbedderDep, llm: LLMDep
) -> dict[str, Any]:
    raw_body = await request.body()
    secret = os.environ.get("GITHUB_WEBHOOK_SECRET")
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not secret or not verify_github_signature(raw_body, signature, secret):
        raise HTTPException(status_code=401, detail="invalid signature")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid JSON payload") from exc

    event = request.headers.get("X-GitHub-Event", "")
    if event == "ping":
        return {"status": "pong"}
    if event == "push":
        return _handle_push(conn, client, embedder, llm, payload)
    if event == "repository":
        return _handle_repository(conn, payload)
    if event == "release":
        return _handle_release(conn, payload)

    return {"status": "ignored", "event": event}
