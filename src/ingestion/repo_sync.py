"""Per-file/per-repo sync helpers shared by the seed sync script and the webhook handler.

Keeping this in one place means webhook-driven incremental sync (Stage 9) can't
drift from what the full seed sync (Stages 2-6) does for the same file types.
"""

from __future__ import annotations

import uuid
from collections import Counter

import psycopg

from src.ingestion.chunker_code import detect_language
from src.ingestion.commits import sync_commit
from src.ingestion.documents import record_ingestion_log
from src.ingestion.embedder import Embedder
from src.ingestion.github_client import GitHubClient, RepoInfo
from src.ingestion.graph import (
    set_manifest_missing,
    sync_manifest,
    sync_static_http_calls,
    sync_static_packages,
    sync_static_routes,
)
from src.ingestion.graph_static_analysis import (
    find_fastapi_routes,
    find_hardcoded_urls,
    parse_package_json,
    parse_pyproject_toml,
    parse_requirements_txt,
)
from src.ingestion.manifest import ManifestError, parse_manifest
from src.ingestion.technologies import sync_technologies
from src.query.synthesizer import LLMClient

# LLM summarization costs real money per commit (unlike embeddings) - capped
# deliberately for the seed sync's per-repo pass. Webhook-driven ingestion doesn't
# use this cap, since it knows exactly which commits are new.
MAX_COMMITS_PER_REPO = 30

PACKAGE_MANIFEST_PARSERS = {
    "requirements.txt": parse_requirements_txt,
    "pyproject.toml": parse_pyproject_toml,
    "package.json": parse_package_json,
}


def sync_manifest_for_repo(
    conn: psycopg.Connection,
    client: GitHubClient,
    repo: RepoInfo,
    project_id: uuid.UUID,
    source: str = "manual",
) -> None:
    content = client.get_file(repo.full_name, "project.yaml")
    if content is None:
        set_manifest_missing(conn, project_id, True)
        return
    try:
        manifest = parse_manifest(content)
    except ManifestError as exc:
        record_ingestion_log(conn, source, project_id, "graph", "error", {"error": str(exc)})
        set_manifest_missing(conn, project_id, True)
        return
    stats = sync_manifest(conn, project_id, manifest)
    record_ingestion_log(conn, source, project_id, "graph", "success", stats)
    sync_technologies(conn, project_id, manifest.technologies)


def sync_static_analysis_for_file(
    conn: psycopg.Connection, project_id: uuid.UUID, file_path: str, content: str
) -> int:
    basename = file_path.rsplit("/", 1)[-1]
    edges = 0

    parser = PACKAGE_MANIFEST_PARSERS.get(basename)
    if parser is not None:
        edges += sync_static_packages(conn, project_id, parser(content), file_path)

    if detect_language(file_path) == "python":
        routes = find_fastapi_routes(content)
        edges += sync_static_routes(conn, project_id, routes, file_path)

    urls = find_hardcoded_urls(content)
    edges += sync_static_http_calls(conn, project_id, urls, file_path)
    return edges


def sync_commits_for_repo(
    conn: psycopg.Connection,
    client: GitHubClient,
    repo: RepoInfo,
    project_id: uuid.UUID,
    embedder: Embedder,
    llm: LLMClient,
    max_count: int = MAX_COMMITS_PER_REPO,
) -> Counter[str]:
    counts: Counter[str] = Counter()
    for info in client.list_commits(repo.full_name, max_count):
        detail = client.get_commit_detail(repo.full_name, info.sha)
        if detail is None:
            continue
        status = sync_commit(conn, project_id, info, detail, embedder, llm)
        counts[status] += 1
    return counts
