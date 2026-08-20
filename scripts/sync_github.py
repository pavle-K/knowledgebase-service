"""Seed sync: fetch repos, docs (L1), code (L2), and the dependency graph (L3).

Manifest-first for L3; static analysis only catches drift. Commits (L4) arrive later.
"""

from __future__ import annotations

import os
import sys
import uuid

import psycopg

from src.ingestion.chunker_code import detect_language, is_candidate_code_file
from src.ingestion.code import sync_code_file
from src.ingestion.documents import record_ingestion_log, sync_document, upsert_project
from src.ingestion.embedder import get_embedder
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

STAT_KEYS = ("chunks", "embedded", "skipped_unchanged", "skipped_secret")

PACKAGE_MANIFEST_PARSERS = {
    "requirements.txt": parse_requirements_txt,
    "pyproject.toml": parse_pyproject_toml,
    "package.json": parse_package_json,
}


def _accumulate(totals: dict[str, int], stats: dict[str, int]) -> None:
    for key in STAT_KEYS:
        totals[key] += stats[key]


def _sync_manifest_for_repo(
    conn: psycopg.Connection, client: GitHubClient, repo: RepoInfo, project_id: uuid.UUID
) -> None:
    content = client.get_file(repo.full_name, "project.yaml")
    if content is None:
        set_manifest_missing(conn, project_id, True)
        return
    try:
        manifest = parse_manifest(content)
    except ManifestError as exc:
        record_ingestion_log(conn, "manual", project_id, "graph", "error", {"error": str(exc)})
        set_manifest_missing(conn, project_id, True)
        return
    stats = sync_manifest(conn, project_id, manifest)
    record_ingestion_log(conn, "manual", project_id, "graph", "success", stats)


def _sync_static_analysis_for_file(
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


def main() -> int:
    github_token = os.environ.get("GITHUB_TOKEN")
    database_url = os.environ.get("DATABASE_URL_RW")
    if not github_token or not database_url:
        print("GITHUB_TOKEN and DATABASE_URL_RW must both be set", file=sys.stderr)
        return 1

    embedder = get_embedder()
    client = GitHubClient(token=github_token)

    with psycopg.connect(database_url) as conn:
        repos = [r for r in client.list_repos() if not r.fork]
        print(f"Found {len(repos)} repos (forks excluded)")

        for repo in repos:
            project_id = upsert_project(conn, repo)

            doc_totals = dict.fromkeys(STAT_KEYS, 0)
            readme = client.get_readme(repo.full_name)
            if readme:
                _accumulate(
                    doc_totals,
                    sync_document(conn, project_id, "readme", "README.md", readme, embedder),
                )
            for doc_path in client.list_docs_files(repo.full_name):
                content = client.get_file(repo.full_name, doc_path)
                if content is not None:
                    _accumulate(
                        doc_totals,
                        sync_document(conn, project_id, "docs", doc_path, content, embedder),
                    )
            record_ingestion_log(conn, "manual", project_id, "documents", "success", doc_totals)

            _sync_manifest_for_repo(conn, client, repo, project_id)

            code_totals = dict.fromkeys(STAT_KEYS, 0)
            graph_edges = 0
            all_files = client.list_all_files(repo.full_name, repo.default_branch)
            for file_path in all_files:
                basename = file_path.rsplit("/", 1)[-1]
                needs_code = is_candidate_code_file(file_path)
                needs_manifest_scan = basename in PACKAGE_MANIFEST_PARSERS
                if not needs_code and not needs_manifest_scan:
                    continue

                content = client.get_file(repo.full_name, file_path)
                if content is None:
                    continue

                if needs_code:
                    stats = sync_code_file(conn, project_id, file_path, content, embedder)
                    _accumulate(code_totals, stats)

                graph_edges += _sync_static_analysis_for_file(conn, project_id, file_path, content)

            record_ingestion_log(conn, "manual", project_id, "code", "success", code_totals)
            record_ingestion_log(
                conn, "manual", project_id, "graph", "success", {"static_edges": graph_edges}
            )

            conn.commit()
            print(
                f"  {repo.full_name}: docs={doc_totals} code={code_totals} "
                f"graph_static_edges={graph_edges}"
            )

    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
